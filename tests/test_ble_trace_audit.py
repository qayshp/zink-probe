import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "ble_trace_audit",
    Path(__file__).parents[1] / "experiments/ble-printing/audit_trace.py",
)
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def frame(direction, value, layer="wire"):
    return {
        "event": "frame",
        "transport": "ble",
        "direction": direction,
        "layer": layer,
        "hex": value,
        "length": len(bytes.fromhex(value)),
    }


def test_auditor_decodes_observed_mtu_and_ack():
    report = AUDIT.audit(
        [
            frame("tx", "810a0100"),
            frame("rx", "810b01020200"),
            frame("rx", "0b01020200", "message"),
        ]
    )
    assert report["configuration"] == {"reported_protocol_mtu": 514, "ack_period": 0}


@pytest.mark.parametrize(
    "payload",
    [
        "0c",
        "0e0100",
        "3001",
        "381122",
        "060101",
        "280101",
        "0a0101",
    ],
)
def test_auditor_rejects_jobs_uploads_allocation_settings_and_unscoped_reads(payload):
    with pytest.raises(ValueError, match="read-only allowlist"):
        AUDIT.audit([frame("tx", "81" + payload)])


def test_auditor_rejects_message_record_not_matching_received_wire():
    with pytest.raises(ValueError, match="does not match"):
        AUDIT.audit(
            [
                frame("tx", "810a0100"),
                frame("rx", "810b01020200"),
                frame("rx", "0b01140000", "message"),
            ]
        )


def test_capability_handle_expires_at_end_of_read():
    events = [
        frame("tx", "812a"),
        frame("rx", "812b0702"),
        frame("rx", "2b0702", "message"),
        frame("tx", "81280701"),
        frame("rx", "81290700000000"),
        frame("rx", "290700000000", "message"),
    ]
    assert AUDIT.audit(events)["responses"] == 2
    with pytest.raises(ValueError, match="read-only allowlist"):
        AUDIT.audit(events + [frame("tx", "81280701")])
