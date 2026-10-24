"""Read-only macOS checks through the portable engine's RFCOMM transport.

No JPEG argument, job allocation, upload, settings change, or automatic retry.
Each requested session is a fresh connection; any failure stops the sequence.
"""

import argparse
import asyncio
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from ..protocol import ProtocolError
from ..trace import Trace
from .diagnostics import ReadOnlySession, inspect_printer
from .macos import MacOSRfcommStream, normalize_address


def positive_seconds(value):
    value = float(value)
    if not math.isfinite(value) or not 0 < value <= 300:
        raise argparse.ArgumentTypeError("Timeout must be finite and in (0, 300]")
    return value


def device_id(value):
    if len(value) != 32 or any(c not in "0123456789abcdefABCDEF" for c in value):
        raise argparse.ArgumentTypeError(
            "Expected 32 hexadecimal protocol device-ID digits"
        )
    return value.lower()


async def run_checks(args, trace, *, stream_factory=MacOSRfcommStream):
    results = []
    for index in range(args.sessions):
        if index:
            # On the validated Select, immediate reopen can race remote/native
            # teardown even after the close callback. This is a gap between
            # explicitly requested sessions, never a retry of a failed request.
            trace.event("reconnect_settle", seconds=2.0)
            await asyncio.sleep(2.0)
        stream = stream_factory(args.address, timeout=args.timeout, trace=trace)
        session = ReadOnlySession(stream, timeout=args.timeout, trace=trace)
        trace.event("adapter_check_started", session=index + 1)
        try:
            async with asyncio.timeout(args.session_timeout):
                await stream.open()
                result = await inspect_printer(session, args.device_id, trace)
        finally:
            await session.close()
        if stream.close_error:
            raise ConnectionError(stream.close_error)
        if result["session"].get("connection_setup") != "accepted":
            raise ProtocolError("Message limit was not negotiated")
        if result["config_before"]["errors"] or result["config_after"]["errors"]:
            raise ProtocolError("Configuration inspection incomplete")
        if not result["counters_unchanged"] or not result["configuration_unchanged"]:
            raise ProtocolError(
                "Printer counters or configuration changed during check"
            )
        if results:
            previous = results[-1]
            if (
                previous["after"]["pages"] != result["before"]["pages"]
                or previous["after"]["calibrations"] != result["before"]["calibrations"]
                or previous["config_after"] != result["config_before"]
            ):
                raise ProtocolError("Printer state changed between connections")
        result["transport"] = {
            "mtu": stream.mtu,
            "native_writes": stream.native_writes,
            "tx_bytes": stream.tx_bytes,
            "rx_bytes": stream.rx_bytes,
            "closed": stream.state == "closed",
            "close_error": stream.close_error,
        }
        trace.event("adapter_check_result", session=index + 1, result=result)
        results.append(result)
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--address",
        required=True,
        type=normalize_address,
        help="Protocol-reported Classic MAC from the existing probe",
    )
    parser.add_argument(
        "--device-id",
        required=True,
        type=device_id,
        help="Expected fixed 16-byte protocol ID, 32 hex digits",
    )
    parser.add_argument(
        "--sessions",
        type=int,
        choices=(1, 2, 3),
        default=2,
        help="Fresh read-only connections; stops at the first failure",
    )
    parser.add_argument("--timeout", type=positive_seconds, default=15.0)
    parser.add_argument("--session-timeout", type=positive_seconds, default=90.0)
    parser.add_argument(
        "--log", type=Path, help="New private JSONL trace; never overwritten"
    )
    args = parser.parse_args(argv)
    path = args.log or Path("logs") / (
        f"{datetime.now(UTC):%Y%m%dT%H%M%S}-macos-adapter-{uuid4().hex[:8]}.jsonl"
    )
    trace = None
    try:
        trace = Trace(path)
        results = asyncio.run(run_checks(args, trace))
        print(
            json.dumps(
                {
                    "ok": True,
                    "read_only": True,
                    "log": str(path),
                    "sessions": [
                        {
                            "identity_matched": True,
                            "firmware": r["identity"].get("firmware"),
                            "super_model": r["identity"].get("super_model"),
                            "max_message": r["session"].get("max_message"),
                            "status": r["after"]["status"],
                            "pages": r["after"]["pages"],
                            "calibrations": r["after"]["calibrations"],
                            "configuration_unchanged": r["configuration_unchanged"],
                            "counters_unchanged": r["counters_unchanged"],
                            "transport": r["transport"],
                        }
                        for r in results
                    ],
                },
                indent=2,
            )
        )
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        error = f"{type(exc).__name__}: {exc}"
        if trace:
            trace.event("adapter_check_failed", error=error)
        print(
            json.dumps(
                {"ok": False, "read_only": True, "error": error, "log": str(path)}
            )
        )
        return 130 if isinstance(exc, KeyboardInterrupt) else 1
    finally:
        if trace:
            trace.close()


if __name__ == "__main__":
    raise SystemExit(main())
