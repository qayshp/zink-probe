"""Read-only Linux checks through the portable engine's RFCOMM transport.

No JPEG argument, job allocation, upload, settings change, or automatic retry.
Each requested session is a fresh connection; any failure stops the sequence.
"""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from ..trace import Trace
from .adapter_checks import device_id, positive_seconds
from .adapter_checks import run_checks as _run_checks
from .linux import LinuxRfcommStream, adapter_name, normalize_address


async def run_checks(args, trace, *, stream_factory=LinuxRfcommStream):
    def factory(address, **kwargs):
        return stream_factory(address, adapter=args.adapter, **kwargs)

    return await _run_checks(args, trace, stream_factory=factory)


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
        "--adapter",
        type=adapter_name,
        help="Linux controller, e.g. hci0; required if the printer is paired on multiple adapters",
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
        f"{datetime.now(UTC):%Y%m%dT%H%M%S}-linux-adapter-{uuid4().hex[:8]}.jsonl"
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
