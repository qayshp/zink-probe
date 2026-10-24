"""Offline simulated-job CLI. No real-printer transport is exposed here."""

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from .engine import JobEngine
from .journal import JobJournal
from .model import JobSpec
from .simulator import DEVICE_ID, SimulatedPrinter
from .transport import FramedSession


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "jpeg", type=Path, help="Already prepared 768x1152 baseline JPEG"
    )
    parser.add_argument(
        "--journal",
        required=True,
        type=Path,
        help="Local SQLite record for simulated jobs",
    )
    parser.add_argument("--name", default="Select photo")
    parser.add_argument("--copies", type=int, default=1)
    parser.add_argument("--allow-alternative-sampling", action="store_true")
    parser.add_argument(
        "--encoder-quality",
        type=int,
        help="Declared encoder metadata, not physical engine quality",
    )
    args = parser.parse_args()
    try:
        job = JobSpec(
            args.jpeg.read_bytes(),
            name=args.name,
            copies=args.copies,
            allow_alternative_sampling=args.allow_alternative_sampling,
            encoder_quality=args.encoder_quality,
        )
        printer = SimulatedPrinter(read_size=37, write_fragment=13)
        with JobJournal(args.journal) as journal:
            runner = JobEngine(
                FramedSession(printer),
                journal,
                DEVICE_ID,
                poll_interval=0,
                observation_timeout=10,
            )
            result = asyncio.run(runner.run(job))
        print(
            json.dumps(
                {
                    "simulated": True,
                    "result": asdict(result),
                    "encoding": job.encoding,
                    "payload_sha256": job.sha256,
                    "payload_bytes_match": bytes(printer.uploaded) == job.jpeg,
                    "print_start_count": sum(m[0] == 12 for m in printer.mutations),
                },
                indent=2,
            )
        )
        return 0 if result.state == "completed" else 1
    except Exception as exc:
        print(json.dumps({"simulated": True, "error": f"{type(exc).__name__}: {exc}"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
