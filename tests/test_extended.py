import asyncio
from types import SimpleNamespace

import pytest

from zink_probe.probe import read_config
from zink_probe.protocol import ProtocolError, bit_view, decode_fields, validate_request


def test_unsolicited_event_never_satisfies_reply_queue():
    from zink_probe.ble import BleConnection
    from zink_probe.protocol import BleAssembler, RfcommParser
    from zink_probe.rfcomm import RfcommConnection

    trace = SimpleNamespace(frame=lambda *a, **k: None, event=lambda *a, **k: None)
    ble = BleConnection.__new__(BleConnection)
    ble.trace, ble.queue, ble.unsolicited = trace, asyncio.Queue(), []
    ble.assembler, ble.ack_period = BleAssembler(), 0
    ble._receive(None, b"\x81\x03\x03\x00")
    assert ble.queue.empty() and ble.unsolicited == ["030300"]
    ble._receive(None, b"\x81\x09\x03\x64")
    assert ble.queue.get_nowait() == b"\x09\x03\x64"
    classic = RfcommConnection.__new__(RfcommConnection)
    classic.trace, classic.queue, classic.unsolicited = trace, asyncio.Queue(), []
    classic.parser = RfcommParser()
    classic._receive(b"HP+\x01\x03\x03\x03\x00HP+\x01\x03\x09\x03\x64")
    assert classic.unsolicited == ["030300"]
    assert classic.queue.get_nowait() == b"\x09\x03\x64"
    assert classic.queue.empty()


def test_native_sdp_serializer():
    native = pytest.importorskip("IOBluetooth")
    from zink_probe.rfcomm import sdp_element

    element = native.IOBluetoothSDPDataElement.withElementValue_([7, "service"])
    decoded = sdp_element(element)
    assert decoded["type"] == 6
    assert [entry["value"] for entry in decoded["value"]] == [7, "service"]


def test_config_typed_values_and_raw_rgb():
    decoded = decode_fields(
        b"\x1b\x01\x03\x00\x02\x3c\x00\x03\x12\x34\x56\x04\x00\x05\x03", config=True
    )
    assert decoded == {
        "sleep_timer_minutes": 3,
        "auto_off_minutes": 60,
        "led_rgb": [18, 52, 86],
        "pause_printing_raw": 0,
        "hosts_threshold_raw": 3,
    }
    with pytest.raises(ProtocolError):
        decode_fields(b"\x1b\x03\x12\x34", config=True)


@pytest.mark.parametrize(
    "message",
    [b"\x1a", b"\x1a\xff", b"\x1a\x01\x00", b"\x1c\x01\x00\x00", b"\x3a\xff\xff"],
)
def test_config_allowlist_excludes_writes_and_unmapped_queries(message):
    with pytest.raises(ProtocolError):
        validate_request(message)


def test_bits_are_not_assigned_speculative_meanings():
    view = bit_view(0x21, 8)
    assert view["set_bit_positions"] == [0, 5]
    assert view["binary"] == "00100001"
    assert "undecoded" in view["meaning"]
    assert decode_fields(b"\x05\x0e\x00\x00\x00\x00", True) == {"born_on_timestamp": 0}


def test_rejected_and_missing_optional_config_fields_are_reported():
    class Connection:
        async def exchange(self, request):
            if request[1] == 3:
                return b"\x1b"  # Valid reply but requested field omitted.
            return b"\x01\x1a\x02"

    result = asyncio.run(read_config(Connection()))
    assert not result["values"]
    assert result["errors"]["led_rgb"] == {"missing": "1b"}
    assert len(result["errors"]) == 5
