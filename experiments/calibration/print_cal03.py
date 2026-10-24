"""One authorized CAL-03 quality-100 4:4:4 sheet; default is validation only.

Keeps the completed CAL-02 sender and its persistent claim unchanged. Reuses its
acknowledgement checks and native transport, with a separate pinned payload,
fresh preflight, exact previously tested unit, and permanent attempt claims.
Two explicit recovery flags document this experiment's name and stale-handle
rejections. Each verifies the specific prior trace and has a separate spent
claim. They are not generic retry/resume logic and are not used by the engine.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from first_print import (
    CalibrationConnection,
    PrintPlan,
    check,
    claim_attempt,
    idle_preflight,
    list_jobs,
)

from zink_probe.capabilities import read_capabilities, read_metrics
from zink_probe.probe import (
    negotiate,
    read_config,
    read_identity,
    read_status,
    require_select,
)
from zink_probe.protocol import RfcommParser
from zink_probe.trace import Trace

ROOT = Path(__file__).resolve().parents[2]
PAYLOAD = ROOT / "experiments/jpeg-quality/q100-444-optimized.jpg"
SHA256 = "50b58d8cc26ba7349e7874861e8c76b16b4b0f5ac6d2962fa0051d970de83944"
PREFLIGHT = ROOT / "logs/cal03-preflight.json"
CLAIM = ROOT / "logs/cal03-one-print-attempt.json"
RESULT = ROOT / "logs/cal03-print-result.json"
NAME = b"SELECT-CAL-03"
CORRECTION_CLAIM = ROOT / "logs/cal03-metadata-correction-attempt.json"
FRESH_CLAIM = ROOT / "logs/cal03-fresh-after-rejected-handle-attempt.json"


def verify_rejected_handle(record):
    check(record.get("payload_sha256") == SHA256, "Wrong prior payload")
    check(
        record.get("continuing_allocated_job") and not record.get("upload_complete"),
        "Wrong recovery phase",
    )
    messages, replies = [], []
    parser = RfcommParser()
    for line in Path(record["log"]).read_text().splitlines():
        item = json.loads(line)
        if item.get("event") != "frame":
            continue
        if item.get("direction") == "tx":
            messages.extend(parser.feed(bytes.fromhex(item["hex"])))
        elif item.get("layer") == "message":
            replies.append(bytes.fromhex(item["hex"]))
    mutations = [m for m in messages if m[0] in (12, 14, 48)]
    check([m[0] for m in mutations] == [48, 14], "Unexpected prior mutations")
    check(replies[-1:] == [b"\x01\x0e\x08"], "First upload not explicitly rejected")
    check(
        not any(r[:1] == b"\x0f" for r in replies), "An upload chunk was acknowledged"
    )
    check(
        mutations[1][2:] == PAYLOAD.read_bytes()[: len(mutations[1]) - 2],
        "Not the first image chunk",
    )


def rejected_allocation(record):
    """Allow only the documented explicit name rejection before any image byte.

    This is not generic reconnect/resume. It cannot allocate another job, and
    never accepts a timeout, partial upload, or ambiguous prior outcome.
    """
    check(record.get("payload_sha256") == SHA256, "Wrong prior payload")
    check(
        record.get("attempted") and not record.get("upload_complete"),
        "Wrong prior phase",
    )
    messages, replies = [], []
    parser = RfcommParser()
    for line in Path(record["log"]).read_text().splitlines():
        item = json.loads(line)
        if item.get("event") != "frame":
            continue
        if item.get("direction") == "tx":
            messages.extend(parser.feed(bytes.fromhex(item["hex"])))
        elif item.get("layer") == "message":
            replies.append(bytes.fromhex(item["hex"]))
    mutations = [m for m in messages if m[0] in (12, 14, 48)]
    check(
        len(mutations) == 2 and [m[0] for m in mutations] == [12, 48],
        "Prior image upload or unexpected mutation",
    )
    check(
        replies[-1:] == [b"\x01\x30\x07"],
        "Prior failure is not explicit invalid-length rejection",
    )
    job, handle = record["job_id"], record["file_handle"]
    check(mutations[1][1:3] == job.to_bytes(2, "little"), "Prior job mismatch")
    check(
        b"\x0d" + bytes([handle]) + job.to_bytes(2, "little") in replies,
        "Allocation acknowledgement missing",
    )
    return job, handle


def validate_payload(data):
    check(hashlib.sha256(data).hexdigest() == SHA256, "CAL-03 payload hash mismatch")
    check(len(data) == 151545, "CAL-03 payload length mismatch")


class Cal03Plan(PrintPlan):
    def __init__(self, data, maximum):
        validate_payload(data)
        check(7 + len(NAME) <= maximum <= 4096, "Unusable negotiated maximum")
        self.data, self.maximum = data, maximum
        self.state, self.offset = "start", 0
        self.handle = self.job = self.expected = None
        self.final_empty_sent = False

    def next_message(self):
        if self.state != "properties":
            return super().next_message()
        check(self.expected is None, "Previous mutation has no acknowledgement")
        message = (
            b"\x30"
            + self.job.to_bytes(2, "little")
            + b"\x03\x01\x01"
            + bytes([len(NAME)])
            + NAME
        )
        check(len(message) <= self.maximum, "Message exceeds negotiated maximum")
        self.expected = message
        return message


async def run(data, complete_allocated=False, fresh_after_rejection=False):
    validate_payload(data)
    claim = (
        FRESH_CLAIM
        if fresh_after_rejection
        else CORRECTION_CLAIM
        if complete_allocated
        else CLAIM
    )
    check(not claim.exists(), "Attempt already claimed; reconcile read-only, no resend")
    prior = (
        json.loads((ROOT / "logs/cal03-name-rejection.json").read_text())
        if complete_allocated
        else None
    )
    allocated = rejected_allocation(prior) if prior else None
    if fresh_after_rejection:
        prior = json.loads((ROOT / "logs/cal03-handle-rejection.json").read_text())
        rejected_allocation(
            json.loads((ROOT / "logs/cal03-name-rejection.json").read_text())
        )
        verify_rejected_handle(prior)
    fresh = (
        ROOT / "logs/cal03-handle-rejection.json"
        if fresh_after_rejection
        else ROOT / "logs/cal03-reconciliation.json"
        if complete_allocated
        else PREFLIGHT
    )
    check(0 <= time.time() - fresh.stat().st_mtime < 300, "Fresh preflight required")
    baseline = json.loads(PREFLIGHT.read_text())
    check(baseline.get("ok"), "Physical preflight failed")
    expected = baseline["rfcomm"]["identity"]
    require_select(expected)
    check(
        expected["device_id"] == baseline["ble"]["identity"]["device_id"],
        "Identity mismatch",
    )
    previous = json.loads((ROOT / "logs/cal02-preflight.json").read_text())
    check(
        expected["device_id"] == previous["rfcomm"]["identity"]["device_id"],
        "Not the previously tested unit",
    )
    trace = Trace(
        ROOT / "logs" / f"{datetime.now(UTC):%Y%m%dT%H%M%S}-cal03-print.jsonl"
    )
    connection = CalibrationConnection(expected["bluetooth_mac"], 20, trace)
    result = {
        "payload_sha256": SHA256,
        "payload_bytes": len(data),
        "copies": 1,
        "jpeg_quality": 100,
        "sampling": "4:4:4",
        "log": str(trace.path),
        "attempted": False,
        "samples": [],
        "events": [],
    }
    try:
        await connection.open()
        session = await negotiate(connection, "rfcomm", trace)
        identity, _ = await read_identity(connection)
        require_select(identity)
        check(identity["device_id"] == expected["device_id"], "Wrong physical printer")
        config = await read_config(connection)
        status = await read_status(connection)
        jobs = await list_jobs(connection)
        idle_preflight(status, config, jobs)
        table = (await read_capabilities(connection))["table"]
        check({12, 14, 48, 44}.issubset(table["requests"]), "Required commands absent")
        check({1, 3}.issubset(table["job_prop"]), "Name/copy properties absent")
        check(
            len(NAME) <= table.get("job_name_max", 0),
            "Name exceeds advertised byte limit",
        )
        metrics = await read_metrics(connection)
        check({"1", "3"}.issubset(metrics["values"]), "Print counters unavailable")
        # Basic BLE/RFCOMM discovery is the fresh identity preflight. Counters
        # are read here on the same channel that will submit the bounded job.
        status = await read_status(connection)
        idle_preflight(status, config, await list_jobs(connection))
        result.update(
            before={"status": status, "config": config, "metrics": metrics},
            session=session,
            job_name_max=table["job_name_max"],
        )
        plan = Cal03Plan(data, session.get("max_message", 0))
        if prior:
            check(
                metrics["values"]["1"] == prior["before"]["metrics"]["values"]["1"],
                "Page count changed after explicit rejection",
            )
        if allocated:
            check(
                metrics["values"]["1"] == prior["before"]["metrics"]["values"]["1"],
                "Page count changed after rejected metadata",
            )
            plan.job, plan.handle = allocated
            plan.state = "properties"
            result.update(
                job_id=plan.job, file_handle=plan.handle, continuing_allocated_job=True
            )
        claim_attempt(claim, SHA256)
        result["attempted"] = True
        trace.event("single_print_authorized", sha256=SHA256, copies=1)
        start, chunks = time.monotonic(), 0
        while plan.state != "complete":
            msg, _ = await connection.submit_next(plan)
            if msg[0] == 12:
                result.update(job_id=plan.job, file_handle=plan.handle)
            chunks += msg[0] == 14
        result.update(
            upload_complete=True, upload_seconds=time.monotonic() - start, chunks=chunks
        )
        trace.event(
            "upload_complete",
            job_id=plan.job,
            seconds=result["upload_seconds"],
            chunks=chunks,
        )
        print(
            json.dumps(
                {
                    k: result[k]
                    for k in ("job_id", "upload_complete", "upload_seconds", "chunks")
                }
            ),
            flush=True,
        )
        end, idle_samples = time.monotonic() + 180, 0
        while time.monotonic() < end:
            status = await read_status(connection)
            jobs = await list_jobs(connection)
            sample = {
                "elapsed": time.monotonic() - start,
                "status": status,
                "jobs": jobs,
            }
            result["samples"].append(sample)
            trace.event("print_observation", **sample)
            print(json.dumps(sample), flush=True)
            idle_samples = (
                idle_samples + 1
                if status.get("print_status_code") == 1 and not jobs
                else 0
            )
            if idle_samples >= 3:
                current = await read_metrics(connection)
                if current["values"]["1"]["value"] > metrics["values"]["1"]["value"]:
                    result["after_metrics"] = current
                    break
            if status.get("print_status_code") not in (1, 2, 7, 16):
                result["observation_stopped"] = "Non-normal state; no automatic action"
                break
            await asyncio.sleep(2)
        if "after_metrics" not in result:
            result["after_metrics"] = await read_metrics(connection)
        result["after_config"] = await read_config(connection)
        for key, tag in (
            ("page_counter_delta", "1"),
            ("calibration_counter_delta", "3"),
        ):
            result[key] = (
                result["after_metrics"]["values"][tag]["value"]
                - metrics["values"][tag]["value"]
            )
        result["configuration_unchanged"] = config == result["after_config"]
        result["device_completion_evidence"] = (
            result["page_counter_delta"] == 1
            and result["calibration_counter_delta"] == 0
            and idle_samples >= 3
            and any(
                s["status"].get("current_job_id") == plan.job
                and s["status"].get("print_status_code") == 7
                for s in result["samples"]
            )
        )
        result["physical_ejection_confirmation"] = (
            "Awaiting operator; device reports are indirect"
        )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        print(
            json.dumps(
                {
                    "event": "stopped",
                    "error": result["error"],
                    "attempted": result["attempted"],
                }
            ),
            flush=True,
        )
    finally:
        result["events"] = connection.unsolicited
        await connection.close()
        trace.event("cal03_result", **result)
        trace.close()
        with os.fdopen(
            os.open(RESULT, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w"
        ) as f:
            json.dump(result, f, indent=2)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute-cal03-once", action="store_true")
    mode.add_argument("--complete-allocated-cal03", action="store_true")
    mode.add_argument("--fresh-after-rejected-handle", action="store_true")
    args = parser.parse_args()
    data = PAYLOAD.read_bytes()
    validate_payload(data)
    if (
        args.execute_cal03_once
        or args.complete_allocated_cal03
        or args.fresh_after_rejected_handle
    ):
        result = asyncio.run(
            run(data, args.complete_allocated_cal03, args.fresh_after_rejected_handle)
        )
        raise SystemExit(0 if result.get("device_completion_evidence") else 1)
    print(
        json.dumps(
            {
                "validated_only": True,
                "sha256": SHA256,
                "bytes": len(data),
                "copies_if_executed": 1,
            }
        )
    )
