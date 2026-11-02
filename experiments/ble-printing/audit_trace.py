#!/usr/bin/env python3
"""Offline audit of this investigation's private BLE application-frame traces.

No Bluetooth imports or device access. Emits counts, not device identifiers or
raw frames. This audits recorded application traffic, not unrecorded OS/HCI work.
"""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from zink_probe.protocol import BleAssembler

FIXED = {
    bytes.fromhex(value)
    for value in (
        "0a0100",  # Connection-local BLE interface configuration.
        "240010",  # Host receive-message bound; no job allocation.
        "0401",  # Firmware.
        "0402",  # Protocol version (first incomplete attempt).
        "0409",  # SuperModel.
        "080102030405060709",  # Status only.
        "2a",  # Discover capability-table read handle.
    )
}


def audit(events):
    assembler = BleAssembler()
    handle = None
    pending = None
    assembled = None
    ack_period = 0
    opcodes = Counter()
    tx_lengths, rx_lengths = [], []
    response_lengths = []
    config = None
    connected_at = disconnected_at = None
    for event in events:
        if event.get("event") in ("gatt_read_request", "gatt_write_request"):
            raise ValueError("Direct characteristic operation outside audit scope")
        if event.get("event") == "connected":
            if event.get("transport") != "ble":
                raise ValueError("Non-BLE connection")
            connected_at = event["monotonic"]
        if event.get("event") == "disconnected":
            disconnected_at = event["monotonic"]
        if event.get("event") != "frame":
            continue
        if event.get("transport") != "ble":
            raise ValueError("Non-BLE frame")
        data = bytes.fromhex(event["hex"])
        if event["length"] != len(data):
            raise ValueError("Frame length mismatch")
        if event["direction"] == "tx":
            if event["layer"] != "wire" or not data:
                raise ValueError("Unexpected transmit layer")
            tx_lengths.append(len(data))
            if data == b"\x00":
                continue
            if data[0] != 0x81 or pending is not None:
                raise ValueError("Unexpected fragmentation or overlapping request")
            request = data[1:]
            scoped_read = (
                len(request) == 3
                and request[0] == 0x28
                and handle is not None
                and request[1:] == bytes([handle, 1])
            )
            metrics_read = len(request) == 4 and request[:2] == b"\x3a\x01"
            if request not in FIXED and not scoped_read and not metrics_read:
                raise ValueError("Transmit outside investigation read-only allowlist")
            pending = request
            opcodes[str(request[0])] += 1
        elif event["direction"] == "rx" and event["layer"] == "wire":
            rx_lengths.append(len(data))
            if assembled is not None:
                raise ValueError("Missing assembled-message record")
            assembled, _ = assembler.feed(data, ack_period)
        elif event["direction"] == "rx" and event["layer"] == "message":
            if data != assembled or pending is None:
                raise ValueError("Message does not match wire data/request")
            if not data or data[0] != pending[0] + 1:
                raise ValueError("Unexpected response opcode")
            response_lengths.append(len(data))
            if pending == b"\x0a\x01\x00":
                if len(data) != 5 or data[1] != 1:
                    raise ValueError("Malformed BLE configuration")
                ack_period = data[4]
                config = {
                    "reported_protocol_mtu": int.from_bytes(data[2:4], "little"),
                    "ack_period": ack_period,
                }
            if pending == b"\x2a":
                if len(data) != 3:
                    raise ValueError("Malformed capability-handle response")
                handle = data[1]
            if pending[0] == 0x28:
                if len(data) < 6 or data[1] != handle:
                    raise ValueError("Mismatched capability read handle")
                if int.from_bytes(data[2:6], "little") == 0:
                    handle = None
            pending = assembled = None
        else:
            raise ValueError("Unexpected frame kind")
    if pending is not None or assembled is not None:
        raise ValueError("Incomplete exchange")
    return {
        "request_counts_decimal_opcode": dict(
            sorted(opcodes.items(), key=lambda x: int(x[0]))
        ),
        "tx_wire_packets": len(tx_lengths),
        "rx_wire_packets": len(rx_lengths),
        "tx_wire_bytes": sum(tx_lengths),
        "rx_wire_bytes": sum(rx_lengths),
        "max_rx_wire_packet": max(rx_lengths, default=0),
        "responses": len(response_lengths),
        "configuration": config,
        "connected_seconds": (
            round(disconnected_at - connected_at, 3)
            if connected_at is not None and disconnected_at is not None
            else None
        ),
        "all_requests_within_read_only_allowlist": True,
        "scope": "Recorded application traffic only; no HCI capture",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("traces", nargs="+", type=Path)
    args = parser.parse_args()
    reports = []
    for path in args.traces:
        raw = path.read_bytes()
        report = audit([json.loads(line) for line in raw.splitlines()])
        reports.append({"trace_sha256": hashlib.sha256(raw).hexdigest(), **report})
    print(json.dumps(reports, indent=2))
