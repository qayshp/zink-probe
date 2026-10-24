"""Single-job submission and conservative completion, independent of native I/O."""

from __future__ import annotations

import asyncio
import hashlib
import math
from dataclasses import dataclass

from ..capabilities import read_capabilities, read_metrics
from ..probe import negotiate, read_config, read_identity, read_status, require_select
from ..protocol import check_response
from .journal import SubmissionBlocked
from .model import RemoteRejected, UploadPlan, require


@dataclass(frozen=True)
class JobResult:
    local_id: str
    state: str
    job_id: int | None = None
    acknowledged_bytes: int = 0
    error: str | None = None
    physical_ejection_confirmed: bool = False

    @classmethod
    def from_record(cls, record):
        return cls(
            **{
                key: record[key]
                for key in (
                    "local_id",
                    "state",
                    "job_id",
                    "acknowledged_bytes",
                    "error",
                )
            }
        )


class _QuietTrace:
    def event(self, *args, **kwargs):
        pass


async def list_jobs(session):
    reply = await session.exchange(b"\x2c")
    check_response(b"\x2c", reply)
    require((len(reply) - 1) % 2 == 0, "Malformed job list")
    jobs = [int.from_bytes(reply[i : i + 2], "little") for i in range(1, len(reply), 2)]
    require(
        0 not in jobs and len(set(jobs)) == len(jobs), "Invalid or duplicate job ID"
    )
    return jobs


async def observation(session):
    status = await read_status(session)
    jobs = await list_jobs(session)
    metrics = await read_metrics(session)
    require(
        "error" not in metrics and {"1", "3"}.issubset(metrics["values"]),
        "Page/calibration counters unavailable",
    )
    return {
        "status": status,
        "jobs": jobs,
        "pages": metrics["values"]["1"]["value"],
        "calibrations": metrics["values"]["3"]["value"],
    }


def idle(observed):
    status = observed["status"]
    return (
        status.get("print_status_code") == 1
        and status.get("system_flags") == 0
        and status.get("current_job_id") == 0
        and status.get("queue_status_code") == 1
        and not observed["jobs"]
    )


class JobEngine:
    """Owns one supplied session; all exit paths close it.

    Caller opens the stream and supplies an expected protocol device ID from
    discovery. run() rechecks that identity, capabilities, idle state and counters
    before claiming. No resume, cancel, reconnect, or mutation retry exists here.
    reconcile() is strictly read-only and can only strengthen saved evidence.
    """

    def __init__(
        self,
        session,
        journal,
        expected_device_id,
        *,
        observation_timeout=180,
        poll_interval=2,
    ):
        require(
            isinstance(expected_device_id, str)
            and len(expected_device_id) == 32
            and all(c in "0123456789abcdef" for c in expected_device_id),
            "Expected fixed protocol device ID required",
        )
        if not math.isfinite(observation_timeout) or observation_timeout <= 0:
            raise ValueError("Positive finite observation timeout required")
        if not math.isfinite(poll_interval) or poll_interval < 0:
            raise ValueError("Nonnegative finite polling interval required")
        self.session, self.journal, self.device_id = (
            session,
            journal,
            expected_device_id,
        )
        self.observation_timeout, self.poll_interval = (
            observation_timeout,
            poll_interval,
        )
        self.used = False

    async def _identity(self):
        setup = await negotiate(self.session, "rfcomm", _QuietTrace())
        require(
            setup.get("connection_setup") == "accepted",
            "Message limit was not negotiated",
        )
        identity, _ = await read_identity(self.session)
        require_select(identity)
        require(
            identity.get("device_id") == self.device_id,
            "Wrong physical device identity",
        )
        self.firmware = identity.get("firmware")
        return setup

    async def _preflight(self, spec):
        setup = await self._identity()
        features = await read_capabilities(self.session)
        require("table" in features, "Capabilities unavailable")
        table = features["table"]
        require(
            {12, 14, 48, 44, 58}.issubset(table.get("requests", [])),
            "Required print/read commands absent",
        )
        require(
            {1, 3}.issubset(table.get("job_prop", [])), "Name/copy properties absent"
        )
        require(1 in table.get("mime", []), "JPEG file type absent")
        name_limit = table.get("job_name_max", 0)
        require(
            type(name_limit) is int and 0 < name_limit <= 65535,
            "Invalid advertised name limit",
        )
        plan = UploadPlan(spec, setup["max_message"], name_limit)
        config = await read_config(self.session)
        require(
            not config["errors"] and config["values"].get("pause_printing_raw") == 0,
            "Paused or unknown configuration",
        )
        before = await observation(self.session)
        require(idle(before), "Printer must be idle with an empty queue and zero flags")
        status = before["status"]
        require(
            status.get("battery_percent", 0) >= 30
            and status.get("battery_status_code") in (1, 2),
            "Battery state unsuitable",
        )
        before.update(firmware=self.firmware, maximum=plan.maximum)
        return plan, before

    def _record_stop(self, local_id, state, exc):
        try:
            return self.journal.update(
                local_id, state=state, error=f"{type(exc).__name__}: {exc}"
            )
        except Exception:
            # A failed journal update cannot erase the already committed pending
            # request or permit resubmission. Surface uncertainty to the caller.
            record = self.journal.get(local_id)
            record.update(
                state="uncertain",
                error="Journal update failed; inspect durable pending state",
            )
            return record

    async def run(self, spec):
        require(not self.used, "Engine instances are single-use")
        self.used = True
        claimed, mutated, plan = False, False, None
        try:
            if self.journal.get(spec.local_id) is not None:
                raise SubmissionBlocked(
                    "Local job ID already exists; use read-only reconciliation"
                )
            plan, before = await self._preflight(spec)
            self.journal.claim(spec, self.device_id, before)
            claimed = True
            while plan.phase != "uploaded":
                message = plan.next_message()
                self.journal.update(
                    spec.local_id,
                    state="request_pending",
                    pending={
                        "opcode": message[0],
                        "length": len(message),
                        "sha256": hashlib.sha256(message).hexdigest(),
                        "offset": plan.offset,
                    },
                )
                mutated = True  # write can send bytes before raising or cancellation
                reply = await self.session.exchange(message)
                plan.accept(reply)
                self.journal.update(
                    spec.local_id,
                    state="uploaded"
                    if plan.phase == "uploaded"
                    else "accepted"
                    if plan.phase == "properties"
                    else "uploading",
                    pending=None,
                    job_id=plan.job_id,
                    file_handle=plan.handle,
                    acknowledged_bytes=plan.offset,
                    upload_acknowledged=plan.phase == "uploaded",
                )
            record = await self._observe(spec.local_id)
            return JobResult.from_record(record)
        except SubmissionBlocked:
            raise
        except asyncio.CancelledError as exc:
            if claimed:
                self._record_stop(spec.local_id, "uncertain", exc)
            raise
        except Exception as exc:
            if not claimed:
                return JobResult(
                    spec.local_id, "not_submitted", error=f"{type(exc).__name__}: {exc}"
                )
            state = (
                "rejected"
                if isinstance(exc, RemoteRejected) and plan.job_id is None
                else "stopped"
                if isinstance(exc, RemoteRejected)
                else "uncertain"
            )
            # A local error after claiming is conservative even if a write was
            # not attempted; the claim still prevents an accidental resubmit.
            record = self._record_stop(
                spec.local_id, state if mutated else "uncertain", exc
            )
            return JobResult.from_record(record)
        finally:
            await self.session.close()

    async def _observe(self, local_id):
        stable_idle = 0
        try:
            async with asyncio.timeout(self.observation_timeout):
                while True:
                    record = self.journal.get(local_id)
                    sample = await observation(self.session)
                    status, job = sample["status"], record["job_id"]
                    seen = record["seen_printing"] or (
                        job is not None
                        and status.get("current_job_id") == job
                        and status.get("print_status_code") == 7
                    )
                    baseline = record["baseline"]
                    delta = sample["pages"] - baseline["pages"]
                    # Foreign activity and calibration/counter changes break
                    # attribution; never turn a disappearing job into success.
                    require(
                        sample["calibrations"] == baseline["calibrations"],
                        "Calibration counter changed",
                    )
                    require(
                        0 <= delta <= record["copies"],
                        "Page counter reset or unexpected extra pages",
                    )
                    require(
                        all(j == job for j in sample["jobs"]), "Foreign job observed"
                    )
                    require(
                        status.get("current_job_id") in (0, job),
                        "Foreign current job observed",
                    )
                    normal = status.get("print_status_code") in (1, 2, 7, 16)
                    require(
                        normal and status.get("system_flags", -1) in (0, 4),
                        "Printer reports a blocking or unknown state",
                    )
                    require(
                        status.get("queue_status_code") in (1, 4),
                        "Queue paused or unknown",
                    )
                    stable_idle = stable_idle + 1 if idle(sample) else 0
                    completed = (
                        seen
                        and record["upload_acknowledged"]
                        and stable_idle >= 2
                        and delta == record["copies"]
                    )
                    record = self.journal.update(
                        local_id,
                        state="completed"
                        if completed
                        else "printing"
                        if seen
                        else "uploaded"
                        if record["upload_acknowledged"]
                        else "uncertain",
                        seen_printing=seen,
                        last_observation=sample,
                        error=None,
                    )
                    if completed:
                        return record
                    await asyncio.sleep(self.poll_interval)
        except TimeoutError:
            return self.journal.update(
                local_id,
                state="uncertain",
                error="Completion not established before observation deadline",
            )

    async def reconcile(self, local_id):
        require(not self.used, "Engine instances are single-use")
        self.used = True
        record = None
        try:
            record = self.journal.get(local_id)
            require(
                record is not None and record["device_id"] == self.device_id,
                "No matching local job",
            )
            if record["state"] in ("completed", "rejected"):
                return JobResult.from_record(record)
            await self._identity()
            require(
                record["job_id"] is not None,
                "Remote job ID unknown; read-only observation cannot attribute it",
            )
            return JobResult.from_record(await self._observe(local_id))
        except asyncio.CancelledError as exc:
            self._record_stop(local_id, "uncertain", exc)
            raise
        except Exception as exc:
            if record is None or record["device_id"] != self.device_id:
                raise
            return JobResult.from_record(self._record_stop(local_id, "uncertain", exc))
        finally:
            await self.session.close()
