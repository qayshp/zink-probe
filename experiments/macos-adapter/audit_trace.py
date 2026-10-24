"""Offline allowlist audit and sanitized summary of private adapter traces.

No transport imports or printer access. TX frames are attempted writes recorded
before dispatch, not proof of Bluetooth delivery. Full identities stay private.
"""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from zink_probe.protocol import ProtocolError, RfcommParser, validate_request


def audit(path):
    raw = path.read_bytes()
    rows = [json.loads(line) for line in raw.splitlines()]
    read_handles, opcodes, pending, parser = set(), Counter(), None, RfcommParser()
    sessions, errors, tx_bytes, replies = [], [], 0, 0
    for row in rows:
        event = row["event"]
        if event == "adapter_check_started":
            read_handles.clear()
            pending, parser = None, RfcommParser()
        if event in ("adapter_check_failed", "validation_failure"):
            errors.append(row["error"])
        if event == "adapter_check_result":
            r = row["result"]
            sessions.append(
                {
                    "firmware": r["identity"].get("firmware"),
                    "super_model": r["identity"].get("super_model"),
                    "max_message": r["session"].get("max_message"),
                    "capability_bytes": r["capabilities"]["length"],
                    "pages": [r["before"]["pages"], r["after"]["pages"]],
                    "calibrations": [
                        r["before"]["calibrations"],
                        r["after"]["calibrations"],
                    ],
                    "status": r["after"]["status"],
                    "configuration_unchanged": r["configuration_unchanged"],
                    "counters_unchanged": r["counters_unchanged"],
                    "transport": r["transport"],
                }
            )
        if event != "frame" or row.get("transport") != "job-stream":
            continue
        data = bytes.fromhex(row["hex"])
        if row["length"] != len(data):
            raise ProtocolError("Trace length mismatch")
        if row["direction"] == "tx":
            decoder = RfcommParser()
            messages = decoder.feed(data)
            if len(messages) != 1 or decoder.buffer or pending is not None:
                raise ProtocolError("Ambiguous or incomplete outgoing frame")
            pending = messages[0]
            validate_request(pending, read_handles)
            opcodes[f"0x{pending[0]:02X}"] += 1
            tx_bytes += len(data)
        elif row["direction"] == "rx":
            for message in parser.feed(data):
                if message[0] == 3:
                    continue
                if pending is None:
                    raise ProtocolError("Unsolicited reply in trace")
                if message[0] == 1:
                    if len(message) != 3 or message[1] != pending[0]:
                        raise ProtocolError("Uncorrelated error reply in trace")
                elif message[0] != pending[0] + 1:
                    raise ProtocolError("Uncorrelated reply in trace")
                if pending == b"\x2a" and message[0] == 43:
                    if len(message) != 3:
                        raise ProtocolError("Invalid discovered file handle")
                    read_handles.add(message[1])
                if pending[0] == 40 and message[0] == 41:
                    if len(message) < 6 or message[1] != pending[1]:
                        raise ProtocolError("Invalid capability read reply")
                    if int.from_bytes(message[2:6], "little") == 0:
                        read_handles.discard(message[1])
                pending = None
                replies += 1
    return {
        "trace_file": path.name,
        "trace_sha256": hashlib.sha256(raw).hexdigest(),
        "date_utc": rows[0]["time"][:10],
        "all_attempted_requests_read_only": True,
        "request_count": sum(opcodes.values()),
        "reply_count": replies,
        "opcode_counts": dict(sorted(opcodes.items())),
        "attempted_tx_bytes": tx_bytes,
        "pending_request_at_end": pending.hex() if pending else None,
        "errors": errors,
        "successful_sessions": sessions,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("traces", type=Path, nargs="+")
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    output = (
        json.dumps({"traces": [audit(path) for path in args.traces]}, indent=2) + "\n"
    )
    if args.output:
        args.output.write_text(output)
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
