"""Prepare, inspect and deliberately submit one saved Select job on any host."""

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from . import prepare_cli
from .jobs import FramedSession, JobEngine, JobJournal
from .jobs.adapter_checks import device_id, positive_seconds, run_checks
from .jobs.backends import resolve_transport, stream_factory
from .jobs.diagnostics import ReadOnlySession
from .jobs.journal import SubmissionBlocked
from .jobs.model import require
from .jobs.saved_plan import create_plan, load_plan, summary
from .jobs.simulator import DEVICE_ID
from .trace import Trace


def _connection_arguments(parser):
    parser.add_argument(
        "--transport",
        choices=("auto", "macos", "linux", "windows", "simulated"),
        default="auto",
    )
    parser.add_argument(
        "--address", help="Paired printer's Classic Bluetooth MAC, not a BLE UUID"
    )
    parser.add_argument("--adapter", help="Linux hciN or Windows local-radio MAC")
    parser.add_argument(
        "--timeout",
        type=positive_seconds,
        default=15.0,
        help="Per-exchange seconds (default 15)",
    )
    parser.add_argument(
        "--log", type=Path, help="New private JSONL trace; never overwritten"
    )


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser(
        "prepare", help="Offline EXIF/sRGB preparation and fit/fill previews"
    )
    prepare_cli.add_arguments(prepare)
    plan = commands.add_parser(
        "plan", help="Offline: snapshot a prepared bundle as one stable job"
    )
    plan.add_argument("bundle", type=Path)
    plan.add_argument("output", type=Path, help="New private job directory")
    target = plan.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--device-id", type=device_id, help="Expected 32-hex protocol device ID"
    )
    target.add_argument(
        "--simulated", action="store_true", help="Create a simulation-only job"
    )
    plan.add_argument("--name", default="Select photo")
    plan.add_argument("--copies", type=int, default=1)
    plan.add_argument(
        "--allow-alternative-sampling",
        action="store_true",
        help="Opt in to prepared 4:2:2 / 4:4:4 JPEG",
    )
    show = commands.add_parser(
        "show", help="Offline: inspect a saved job and optional journal result"
    )
    show.add_argument("plan", type=Path)
    show.add_argument("--journal", type=Path)
    status = commands.add_parser(
        "status", help="Read-only identity, battery, status, queue and counters"
    )
    _connection_arguments(status)
    status.add_argument(
        "--device-id",
        type=device_id,
        help="Required expected identity for a real printer",
    )
    status.add_argument("--sessions", type=int, choices=(1, 2, 3), default=1)
    status.add_argument("--session-timeout", type=positive_seconds, default=90.0)
    for command, help_text in (
        ("submit", "PRINT a saved real job, or run a simulation-only plan"),
        ("reconcile", "Read-only: check an existing job; never resume or resend"),
    ):
        operation = commands.add_parser(command, help=help_text, description=help_text)
        operation.add_argument("plan", type=Path)
        operation.add_argument(
            "--journal",
            required=True,
            type=Path,
            help="Persistent journal; reuse for every job on this printer",
        )
        _connection_arguments(operation)
        operation.add_argument(
            "--observation-timeout", type=positive_seconds, default=180.0
        )
        operation.add_argument(
            "--operation-timeout",
            type=positive_seconds,
            default=300.0,
            help="Whole operation deadline, seconds (default/max 300)",
        )
    return root


def _endpoint(args, simulated):
    selected = resolve_transport(args.transport, simulated=simulated)
    if simulated and (args.address or args.adapter):
        raise ValueError("Simulation takes no Bluetooth address or adapter")
    if not simulated and not args.address:
        raise ValueError("--address is required for a paired real printer")
    return selected, stream_factory(selected, args.adapter)


def _log(args):
    return args.log or Path("logs") / (
        f"{datetime.now(UTC):%Y%m%dT%H%M%S}-zink-{args.command}-{uuid4().hex[:8]}.jsonl"
    )


def _record_summary(record):
    if record is None:
        return None
    return {
        key: record.get(key)
        for key in (
            "local_id",
            "state",
            "job_id",
            "acknowledged_bytes",
            "upload_acknowledged",
            "seen_printing",
            "error",
            "pending",
            "updated_at",
        )
    }


def _matching_record(journal, intent, spec):
    record = journal.get(spec.local_id)
    if record is not None:
        require(
            all(
                record[key] == value
                for key, value in {
                    "device_id": intent["device_id"],
                    "sha256": spec.sha256,
                    "bytes": len(spec.jpeg),
                    "name": spec.name,
                    "copies": spec.copies,
                    "encoding": spec.encoding,
                }.items()
            ),
            "Saved plan does not match the journal's original job",
        )
    return record


async def _status(args, trace, factory):
    results = await run_checks(args, trace, stream_factory=factory)
    return [
        {
            "identity_matched": True,
            "firmware": r["identity"].get("firmware"),
            "super_model": r["identity"].get("super_model"),
            "max_message": r["session"].get("max_message"),
            "status": r["after"]["status"],
            "queue": r["after"]["jobs"],
            "pages": r["after"]["pages"],
            "calibrations": r["after"]["calibrations"],
            "configuration_unchanged": r["configuration_unchanged"],
            "counters_unchanged": r["counters_unchanged"],
            "transport": r["transport"],
        }
        for r in results
    ]


async def _job(args, intent, spec, journal, trace, factory):
    stream = factory(args.address, timeout=args.timeout, trace=trace)
    session_class = ReadOnlySession if args.command == "reconcile" else FramedSession
    session = session_class(stream, timeout=args.timeout, trace=trace)
    engine = JobEngine(
        session,
        journal,
        intent["device_id"],
        poll_interval=0 if intent["simulated"] else 2,
        observation_timeout=args.observation_timeout,
    )
    try:
        async with asyncio.timeout(args.operation_timeout):
            await stream.open()
            if args.command == "reconcile":
                result = await engine.reconcile(spec.local_id)
            else:
                result = await engine.run(spec)
        output = asdict(result)
        output["close_error"] = stream.close_error
        if intent["simulated"] and args.command == "submit":
            output["payload_bytes_match"] = bytes(stream.uploaded) == spec.jpeg
            output["print_start_count"] = sum(r[0] == 12 for r in stream.requests)
        return output
    finally:
        await session.close()


def _result_code(result):
    if result["state"] == "completed":
        return 1 if result.get("close_error") else 0
    return 1 if result["state"] in ("not_submitted", "rejected") else 3


def _execute(args, output):
    if args.command == "plan":
        intent, _ = create_plan(
            args.bundle,
            args.output,
            expected_device_id=DEVICE_ID if args.simulated else args.device_id,
            simulated=args.simulated,
            name=args.name,
            copies=args.copies,
            allow_alternative_sampling=args.allow_alternative_sampling,
        )
        output.update(offline=True, plan=str(args.output), job=summary(intent))
        return 0
    if args.command == "status":
        simulated = args.transport == "simulated"
        if simulated:
            require(args.device_id in (None, DEVICE_ID), "Wrong simulated identity")
            args.device_id = DEVICE_ID
        elif args.device_id is None:
            raise ValueError(
                "--device-id is required; obtain it with the existing discovery probe"
            )
        selected, factory = _endpoint(args, simulated)
        output.update(
            read_only=True, offline=simulated, simulated=simulated, transport=selected
        )
        path = _log(args)
        output["log"] = str(path)
        trace = Trace(path)
        try:
            output["sessions"] = asyncio.run(_status(args, trace, factory))
        except (Exception, KeyboardInterrupt) as exc:
            trace.event("adapter_check_failed", error=_error(exc))
            raise
        finally:
            trace.close()
        return 0
    intent, spec = load_plan(args.plan)
    output.update(
        job=summary(intent),
        simulated=intent["simulated"],
        read_only=args.command != "submit",
        offline=args.command == "show" or intent["simulated"],
    )
    if args.command == "show" and args.journal is None:
        return 0
    # Never silently create an empty journal for a request to inspect/reconcile.
    if args.command != "submit" and not args.journal.is_file():
        raise FileNotFoundError("Journal does not exist")
    output["journal"] = str(args.journal)
    with JobJournal(args.journal) as journal:
        record = _matching_record(journal, intent, spec)
        output["record"] = _record_summary(record)
        if args.command == "show":
            return 0
        if args.command == "submit":
            if (
                record is not None
                or journal.active_for_device(intent["device_id"]) is not None
            ):
                raise SubmissionBlocked(
                    "Already attempted job or unresolved printer job; use show/reconcile, never resend"
                )
        else:
            require(record is not None, "No matching local job to reconcile")
            if record["state"] in ("completed", "rejected"):
                output["result"] = _record_summary(record)
                output["offline"] = True
                return _result_code(record)
        selected, factory = _endpoint(args, intent["simulated"])
        output["transport"] = selected
        path = _log(args)
        output["log"] = str(path)
        trace = Trace(path)
        try:
            trace.event(
                "unified_job_started",
                command=args.command,
                local_id=spec.local_id,
                simulated=intent["simulated"],
                payload_sha256=spec.sha256,
            )
            output["result"] = asyncio.run(
                _job(args, intent, spec, journal, trace, factory)
            )
            trace.event("unified_job_result", result=output["result"])
            return _result_code(output["result"])
        except (Exception, KeyboardInterrupt) as exc:
            trace.event("unified_job_failed", error=_error(exc))
            raise
        finally:
            output["record"] = _record_summary(journal.get(spec.local_id))
            trace.close()


def _error(exc):
    detail = str(exc) or (
        "Operation timed out"
        if isinstance(exc, TimeoutError)
        else "Operation interrupted"
    )
    return f"{type(exc).__name__}: {detail}"


def main(argv=None):
    args = parser().parse_args(argv)
    if args.command == "prepare":
        return prepare_cli.run(args)
    output = {"command": args.command}
    try:
        code = _execute(args, output)
    except (Exception, KeyboardInterrupt) as exc:
        output["error"] = _error(exc)
        state = (output.get("record") or {}).get("state")
        code = (
            130
            if isinstance(exc, KeyboardInterrupt)
            else 3
            if state not in (None, "completed", "rejected")
            else 1
        )
    output["ok"] = code == 0
    print(json.dumps(output, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
