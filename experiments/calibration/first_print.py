"""One explicitly authorized CAL-02 print. Not a general-purpose printing CLI.

Default invocation validates the pinned payload only. --execute-cal02-once enables
one persistent attempt against the exact unit in a fresh local probe snapshot.
No resend, reconnect, resume, cancellation, or settings writes are implemented.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import struct
import time
from datetime import UTC, datetime
from pathlib import Path

from zink_probe.capabilities import read_capabilities, read_metrics
from zink_probe.probe import (
    negotiate,
    read_config,
    read_identity,
    read_status,
    require_select,
)
from zink_probe.protocol import ProtocolError, check_response
from zink_probe.rfcomm import RfcommConnection
from zink_probe.trace import Trace

ROOT = Path(__file__).resolve().parents[2]
PAYLOAD = ROOT / "experiments/calibration/package-v2/python.jpg"
SHA256 = "14e1530787508578341510cbdf827352a604d19b1b14039fc3cf785e26078206"
PREFLIGHT = ROOT / "logs/cal02-preflight.json"
CLAIM = ROOT / "logs/cal02-one-print-attempt.json"
RESULT = ROOT / "logs/cal02-first-print-result.json"


def check(condition, message):
    if not condition:
        raise ProtocolError(message)


def validate_payload(data):
    check(hashlib.sha256(data).hexdigest() == SHA256, "CAL-02 payload hash mismatch")
    check(data[:2] == b"\xff\xd8" and data[-2:] == b"\xff\xd9", "Not the complete JPEG")


def frame(message):
    check(0 < len(message) <= 4096, "Invalid application length")
    if len(message) <= 255:
        return b"HP+\x01" + bytes([len(message)]) + message
    return b"HP+\x02" + struct.pack("<H", len(message)) + message


def claim_attempt(path, payload_hash):
    # Persist BEFORE the first mutating write. Never delete/reuse automatically.
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(
            {
                "sha256": payload_hash,
                "copies": 1,
                "claimed_at": datetime.now(UTC).isoformat(),
                "policy": "Do not repeat; reconcile any uncertain result read-only",
            },
            f,
        )
        f.flush()
        os.fsync(f.fileno())


class PrintPlan:
    """Finite single-job transcript: each mutating message is issued at most once."""

    def __init__(self, data, maximum):
        validate_payload(data)
        check(3 <= maximum <= 4096, "Unusable negotiated maximum")
        self.data = data
        self.maximum = maximum
        self.state = "start"
        self.offset = 0
        self.handle = None
        self.job = None
        self.expected = None
        self.final_empty_sent = False

    def next_message(self):
        check(
            self.expected is None, "Previous mutation has no validated acknowledgement"
        )
        if self.state == "start":
            msg = b"\x0c\x01" + struct.pack("<I", len(self.data))
        elif self.state == "properties":
            name = b"SELECT-CAL-02"
            msg = (
                b"\x30"
                + struct.pack("<H", self.job)
                + b"\x03\x01\x01"
                + bytes([len(name)])
                + name
            )
        elif self.state == "upload":
            chunk = self.data[self.offset : self.offset + self.maximum - 2]
            if not chunk:
                check(not self.final_empty_sent, "Repeated empty final chunk refused")
                self.final_empty_sent = True
            msg = b"\x0e" + bytes([self.handle]) + chunk
        else:
            raise ProtocolError("Single print plan is finished")
        check(len(msg) <= self.maximum, "Message exceeds negotiated maximum")
        self.expected = msg
        return msg

    def accept(self, reply):
        msg = self.expected
        check(msg is not None, "No outstanding mutation")
        check_response(msg, reply)
        if self.state == "start":
            check(len(reply) == 4, "Malformed PrintStart response")
            self.handle = reply[1]
            self.job = int.from_bytes(reply[2:4], "little")
            self.state = "properties"
        elif self.state == "properties":
            check(reply == b"\x31", "Unexpected property response")
            self.state = "upload"
        elif self.state == "upload":
            check(len(reply) == 11, "Malformed FileWrite response")
            handle, status, received, total = struct.unpack("<BBII", reply[1:])
            check(handle == self.handle, "File handle changed")
            check(status in (1, 2), f"Upload status {status}; no retry")
            check(
                received == self.offset + len(msg) - 2,
                "Unexpected acknowledgement offset",
            )
            check(total == len(self.data), "Unexpected target total length")
            if status == 2:
                check(received == len(self.data), "Premature upload completion")
                self.state = "complete"
            self.offset = received
        self.expected = None


class CalibrationConnection(RfcommConnection):
    async def submit_next(self, plan):
        # Only a validated, pinned finite plan can supply a write; ordinary reads
        # still use the inherited deny-by-default diagnostic policy.
        msg = plan.next_message()
        check(self.channel_id == 2 and self.channel is not None, "No protocol channel")
        check(self.queue.empty(), "Pending reply before mutation")
        wire = frame(msg)
        self.trace.frame("rfcomm", "tx", wire)
        rc = self.channel.writeSync_length_(wire, len(wire))
        if rc != 0:
            raise ConnectionError(f"Print write failed: IOReturn {rc}; no resend")
        end = time.monotonic() + self.timeout
        while self.queue.empty():
            if self.delegate.closed:
                raise ConnectionError("Disconnected during print; no resend")
            if time.monotonic() >= end:
                raise TimeoutError("Print reply uncertain; no resend")
            from Foundation import NSDate, NSRunLoop

            NSRunLoop.currentRunLoop().runUntilDate_(
                NSDate.dateWithTimeIntervalSinceNow_(0.005)
            )
            await asyncio.sleep(0.005)
        reply = self.queue.get_nowait()
        if isinstance(reply, Exception):
            raise reply
        plan.accept(reply)
        return msg, reply


async def list_jobs(connection):
    reply = await connection.exchange(b"\x2c")
    check_response(b"\x2c", reply)
    check((len(reply) - 1) % 2 == 0, "Malformed job list")
    return [int.from_bytes(reply[i : i + 2], "little") for i in range(1, len(reply), 2)]


def idle_preflight(status, config, jobs):
    check(status.get("print_status_code") == 1, "Printer is not idle")
    check(status.get("system_flags") == 0, "Printer reports system flags")
    check(
        status.get("queue_status_code") == 1 and not jobs, "Remote queue is not empty"
    )
    check(status.get("current_job_id") == 0, "Current job is present")
    check(status.get("battery_percent", 0) >= 30, "Battery below first-print threshold")
    check(status.get("battery_status_code") in (1, 2), "Battery status is unsuitable")
    check(
        not config["errors"] and config["values"].get("pause_printing_raw") == 0,
        "Printer is paused/config unknown",
    )


async def run(data):
    check(
        not CLAIM.exists(),
        "An attempt is already claimed; read-only reconciliation required",
    )
    check(
        time.time() - PREFLIGHT.stat().st_mtime < 300,
        "Fresh physical preflight required",
    )
    baseline = json.loads(PREFLIGHT.read_text())
    check(baseline.get("ok"), "Physical probe failed")
    expected = baseline["rfcomm"]["identity"]
    require_select(expected)
    check(
        expected["device_id"] == baseline["ble"]["identity"]["device_id"],
        "Transport identity mismatch",
    )
    trace = Trace(
        ROOT / "logs" / f"{datetime.now(UTC):%Y%m%dT%H%M%S}-cal02-first-print.jsonl"
    )
    connection = CalibrationConnection(expected["bluetooth_mac"], 20, trace)
    result = {
        "payload_sha256": SHA256,
        "payload_bytes": len(data),
        "copies": 1,
        "log": str(trace.path),
        "attempted": False,
        "samples": [],
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
        check(
            {12, 14, 48, 44}.issubset(table["requests"]),
            "Required commands not advertised",
        )
        check({1, 3}.issubset(table["job_prop"]), "Name/copy properties not advertised")
        metrics = await read_metrics(connection)
        check({"1", "3"}.issubset(metrics["values"]), "Print counters unavailable")
        check(
            metrics["values"]["1"] == baseline["rfcomm"]["metrics"]["values"]["1"],
            "Page count changed since preflight",
        )
        result.update(
            before={"status": status, "config": config, "metrics": metrics},
            session=session,
        )
        plan = PrintPlan(data, session.get("max_message", 0))
        claim_attempt(CLAIM, SHA256)
        result["attempted"] = True
        trace.event("single_print_authorized", sha256=SHA256, copies=1)
        start = time.monotonic()
        chunks = 0
        while plan.state != "complete":
            msg, reply = await connection.submit_next(plan)
            if msg[0] == 12:
                result["job_id"] = plan.job
                result["file_handle"] = plan.handle
            if msg[0] == 14:
                chunks += 1
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
                    "event": "upload_complete",
                    "job_id": plan.job,
                    "chunks": chunks,
                    "seconds": result["upload_seconds"],
                }
            ),
            flush=True,
        )
        # Observe only; never kick/resume/reissue a job. Up to 180s after upload.
        end = time.monotonic() + 180
        idle_samples = 0
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
        result.setdefault("after_metrics", await read_metrics(connection))
        result["after_config"] = await read_config(connection)
        result["page_counter_delta"] = (
            result["after_metrics"]["values"]["1"]["value"]
            - metrics["values"]["1"]["value"]
        )
        result["calibration_counter_delta"] = (
            result["after_metrics"]["values"]["3"]["value"]
            - metrics["values"]["3"]["value"]
        )
        result["configuration_unchanged"] = config == result["after_config"]
        result["physical_ejection_confirmation"] = (
            "Requires operator observation; counters/status alone are indirect"
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
        await connection.close()
        trace.event("first_print_result", **result)
        trace.close()
        with os.fdopen(
            os.open(RESULT, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w"
        ) as f:
            json.dump(result, f, indent=2)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-cal02-once", action="store_true")
    args = parser.parse_args()
    data = PAYLOAD.read_bytes()
    validate_payload(data)
    if args.execute_cal02_once:
        result = asyncio.run(run(data))
        raise SystemExit(1 if "error" in result else 0)
    print(
        json.dumps(
            {
                "validated_only": True,
                "sha256": SHA256,
                "bytes": len(data),
                "copies_if_explicitly_executed": 1,
            }
        )
    )
