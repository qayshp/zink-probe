import asyncio
import copy

import pytest

from zink_probe import settings
from zink_probe.protocol import (
    SELECT_LED_COLORS,
    ProtocolError,
    encode_rfcomm,
    validate_request,
)


@pytest.mark.parametrize("payload", [b"\x1c\x01\x05\0", b"\x1c\x03\x00\x2e\xe0"])
def test_exact_write_grant_is_required_and_revocable(payload):
    grants = set()
    with pytest.raises(ProtocolError):
        validate_request(payload)
    grants.add(payload)
    assert encode_rfcomm(payload, (), grants).endswith(payload)
    grants.clear()
    with pytest.raises(ProtocolError):
        encode_rfcomm(payload, (), grants)


@pytest.mark.parametrize(
    "payload",
    [
        b"\x0c\x01",
        b"\x0e\x01",
        b"\x10\x01",
        b"\x12\x01",
        b"\x38\x02",
        b"\x1c\x04\0",
        b"\x1c\x04\x01",
        b"\x1c\x02\0\0",
        b"\x1c\x01\x01\0",
        b"\x1c\x03\x01\0\0",
        b"\x1c\x03\xff\xff",
        b"\x1c\x01\x05\0\x04\0",
    ],
)
def test_dangerous_or_malformed_grant_cannot_authorize_request(payload):
    with pytest.raises(ProtocolError):
        encode_rfcomm(payload, (), {payload})


class Trace:
    def __init__(self):
        self.events = []

    def event(self, event, **data):
        self.events.append((event, data))


def harness(
    monkeypatch, lost_ack=False, busy=False, bad_original=False, fail_restore=False
):
    state = {
        "sleep_timer_minutes": 3,
        "auto_off_minutes": 0,
        "led_rgb": [1, 0, 0] if bad_original else [255, 255, 255],
        "pause_printing_raw": 0,
        "hosts_threshold_raw": 3,
    }
    writes = []

    class Connection:
        def __init__(self, name):
            self.name = name
            self.config_writes = set()

        async def exchange(self, payload):
            nonlocal lost_ack
            validate_request(payload, (), self.config_writes)
            if payload == b"\x2c":
                return b"\x2d"
            writes.append((self.name, payload))
            if fail_restore and payload == b"\x1c\x01\x03\0":
                raise TimeoutError("restoration unavailable")
            if payload[1] == 1:
                state["sleep_timer_minutes"] = int.from_bytes(payload[2:], "little")
            else:
                state["led_rgb"] = list(payload[2:])
            if lost_ack:
                lost_ack = False
                raise TimeoutError("applied write, lost acknowledgement")
            return b"\x1d"

    async def config(c):
        return {"values": copy.deepcopy(state), "errors": {}}

    async def status(c):
        return {
            "print_status_code": 7 if busy else 1,
            "current_job_id": 0,
            "queue_status_code": 1,
        }

    async def caps(c):
        return {
            "table": {
                "requests": [28],
                "sys_cfg": [1, 3],
                "color_palette": ["#" + v.hex() for v in SELECT_LED_COLORS],
            }
        }

    async def metrics(c):
        return {"values": {"1": {"value": 10}, "3": {"value": 2}}}

    monkeypatch.setattr(settings, "read_config", config)
    monkeypatch.setattr(settings, "read_status", status)
    monkeypatch.setattr(settings, "read_capabilities", caps)
    monkeypatch.setattr(settings, "read_metrics", metrics)
    return Connection("ble"), Connection("rfcomm"), state, writes


def test_cross_transport_roundtrip_restores_all_settings_and_revokes(monkeypatch):
    ble, rfcomm, state, writes = harness(monkeypatch)
    original = copy.deepcopy(state)
    result = {}
    asyncio.run(settings.settings_test(ble, rfcomm, Trace(), result))
    assert result["restored"] and state == original
    assert writes == [
        ("ble", b"\x1c\x01\x05\0"),
        ("rfcomm", b"\x1c\x01\x03\0"),
        ("rfcomm", b"\x1c\x03\x00\x2e\xe0"),
        ("ble", b"\x1c\x03\xff\xff\xff"),
    ]
    assert not ble.config_writes and not rfcomm.config_writes
    assert all(e["restored"] for e in result["experiments"])


def test_lost_write_ack_still_restores_and_stops_further_experiments(monkeypatch):
    ble, rfcomm, state, writes = harness(monkeypatch, lost_ack=True)
    result = {}
    with pytest.raises(ProtocolError, match="experiment failed"):
        asyncio.run(settings.settings_test(ble, rfcomm, Trace(), result))
    assert state["sleep_timer_minutes"] == 3
    assert len(writes) == 2 and result["experiments"][0]["restored"]
    assert "experiment_error" in result["experiments"][0]
    assert not ble.config_writes and not rfcomm.config_writes


@pytest.mark.parametrize("options", [{"busy": True}, {"bad_original": True}])
def test_preflight_failure_never_writes(monkeypatch, options):
    ble, rfcomm, state, writes = harness(monkeypatch, **options)
    with pytest.raises(ProtocolError):
        asyncio.run(settings.settings_test(ble, rfcomm, Trace(), {}))
    assert not writes and not ble.config_writes and not rfcomm.config_writes


def test_failed_restoration_is_not_reported_as_success(monkeypatch):
    ble, rfcomm, state, writes = harness(monkeypatch, fail_restore=True)
    result = {}
    with pytest.raises(ProtocolError):
        asyncio.run(settings.settings_test(ble, rfcomm, Trace(), result))
    assert not result["experiments"][0]["restored"]
    assert len(result["experiments"][0]["restore_attempts"]) == 2
    assert (
        not result.get("restored")
        and not ble.config_writes
        and not rfcomm.config_writes
    )


def test_cancellation_after_mutation_attempts_restore_and_revokes(monkeypatch):
    ble, rfcomm, state, writes = harness(monkeypatch)
    exchange = ble.exchange

    async def cancelled(payload):
        response = await exchange(payload)
        if payload == b"\x1c\x01\x05\0":
            raise asyncio.CancelledError
        return response

    ble.exchange = cancelled
    trace = Trace()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(settings.settings_test(ble, rfcomm, trace, {}))
    assert state["sleep_timer_minutes"] == 3
    assert len(writes) == 2 and not ble.config_writes and not rfcomm.config_writes
    assert trace.events[-1][1]["result"]["restored"]


def test_missing_before_counters_prevents_mutation(monkeypatch):
    ble, rfcomm, state, writes = harness(monkeypatch)

    async def missing(c):
        return {"error": "unavailable", "values": {}}

    monkeypatch.setattr(settings, "read_metrics", missing)
    with pytest.raises(ProtocolError, match="counters unavailable"):
        asyncio.run(settings.settings_test(ble, rfcomm, Trace(), {}))
    assert not writes
