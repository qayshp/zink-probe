"""Reproduce sanitized CAL-03 evidence from private local trace files.

Run from the repository root. Reads logs and writes only the public evidence
summary; never contacts a device. Leading-end confirmation is the operator's
2026-10-24 report, not a conclusion inferred from protocol traffic.
"""

import collections
import hashlib
import json
import struct
from pathlib import Path

from zink_probe.protocol import RfcommParser, validate_request

root = Path.cwd()
result = json.loads((root / "logs/cal03-print-result.json").read_text())


def trace_items(record):
    records = [
        json.loads(line) for line in Path(record["log"]).read_text().splitlines()
    ]
    tx = []
    rx = []
    p = RfcommParser()
    for r in records:
        if r.get("event") != "frame":
            continue
        if r.get("direction") == "tx":
            tx.extend(p.feed(bytes.fromhex(r["hex"])))
        elif r.get("layer") == "message":
            rx.append(bytes.fromhex(r["hex"]))
    assert not p.buffer
    return tx, rx


sent, replies = trace_items(result)
mut = [m for m in sent if m[0] in (12, 48, 14)]
assert [m[0] for m in mut] == [12, 48] + [14] * 152
start = next(r for r in replies if r[0] == 13)
assert int.from_bytes(start[2:], "little") == result["job_id"] == 14
handle = start[1]
assert handle == result["file_handle"] == 5
payload = b"".join(m[2:] for m in mut[2:])
assert (
    payload == (root / "experiments/jpeg-quality/q100-444-optimized.jpg").read_bytes()
)
assert hashlib.sha256(payload).hexdigest() == result["payload_sha256"]
assert mut[0] == b"\x0c\x01" + struct.pack("<I", len(payload))
name = b"SELECT-CAL-03"
assert (
    mut[1]
    == b"\x30" + struct.pack("<H", 14) + b"\x03\x01\x01" + bytes([len(name)]) + name
)
acks = [r for r in replies if r[0] == 15]
assert len(acks) == 152
position = 0
for i, (message, ack) in enumerate(zip(mut[2:], acks)):
    position += len(message) - 2
    assert message[1] == handle and len(message) <= 1000
    assert ack == b"\x0f" + struct.pack(
        "<BBII", handle, 2 if i == 151 else 1, position, len(payload)
    )
for m in sent:
    if m[0] not in (12, 48, 14):
        validate_request(m, read_handles={m[1]} if m[0] == 40 else ())
samples = result["samples"]
printing = [s for s in samples if s["status"].get("print_status_code") == 7]
assert (
    printing
    and result["page_counter_delta"] == 1
    and result["calibration_counter_delta"] == 0
    and result["configuration_unchanged"]
)
failed = []
for filename in ["cal03-name-rejection.json", "cal03-handle-rejection.json"]:
    r = json.loads((root / "logs" / filename).read_text())
    tx, rx = trace_items(r)
    mutations = [m for m in tx if m[0] in (12, 48, 14)]
    assert not any(m[0] == 15 for m in rx)
    failed.append(
        {
            "stage": filename.removesuffix(".json"),
            "job_id": r["job_id"],
            "file_handle": r["file_handle"],
            "mutation_opcodes": [hex(m[0]) for m in mutations],
            "final_reply": rx[-1].hex(),
            "acknowledged_image_chunks": 0,
        }
    )
evidence = {
    "date_local": "2026-10-24",
    "timezone": "America/Los_Angeles",
    "firmware": "G1L1FA2105AR",
    "payload_sha256": result["payload_sha256"],
    "payload_bytes": len(payload),
    "jpeg_quality": 100,
    "sampling": "4:4:4",
    "copies": 1,
    "operator_confirmation": {
        "sheet_emerged": True,
        "leading_end": "B / TWO",
        "source": "User report in this chat",
    },
    "job_id": 14,
    "file_handle": 5,
    "job_name_max": 16,
    "successful_transaction_opcode_counts": {
        f"{k:02x}": v
        for k, v in sorted(collections.Counter(m[0] for m in sent).items())
    },
    "upload_seconds": result["upload_seconds"],
    "chunks": 152,
    "last_chunk_payload": len(mut[-1]) - 2,
    "first_printing_observation_seconds": printing[0]["elapsed"],
    "last_printing_observation_seconds": printing[-1]["elapsed"],
    "first_idle_after_print_seconds": next(
        s["elapsed"]
        for s in samples
        if s["elapsed"] > printing[-1]["elapsed"]
        and s["status"]["print_status_code"] == 1
    ),
    "page_counter_before": result["before"]["metrics"]["values"]["1"]["value"],
    "page_counter_after": result["after_metrics"]["values"]["1"]["value"],
    "calibration_counter_before": result["before"]["metrics"]["values"]["3"]["value"],
    "calibration_counter_after": result["after_metrics"]["values"]["3"]["value"],
    "configuration_unchanged": result["configuration_unchanged"],
    "all_upload_ack_offsets_verified": True,
    "rejected_transactions": failed,
    "events": result["events"],
    "wire_vectors": {
        "start_request": mut[0].hex(),
        "start_reply": start.hex(),
        "properties_request": mut[1].hex(),
        "properties_reply": "31",
        "file_write_replies": [r.hex() for r in acks],
    },
    "samples": [
        {
            "elapsed": round(s["elapsed"], 3),
            "print_status": s["status"]["print_status"],
            "system_flags": s["status"]["system_flags"],
            "current_job_id": s["status"]["current_job_id"],
            "progress": s["status"]["print_progress_percent"],
            "battery_status": s["status"]["battery_status"],
            "battery_percent": s["status"]["battery_percent"],
            "jobs": s["jobs"],
        }
        for s in samples
    ],
}
out = root / "experiments/calibration/package-v3/print-evidence.json"
out.write_text(json.dumps(evidence, indent=2) + "\n")
print(
    json.dumps(
        {
            k: evidence[k]
            for k in (
                "job_id",
                "upload_seconds",
                "chunks",
                "last_chunk_payload",
                "page_counter_before",
                "page_counter_after",
                "first_idle_after_print_seconds",
                "operator_confirmation",
            )
        }
    )
)
