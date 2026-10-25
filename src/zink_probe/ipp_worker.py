"""One bounded PAPPL raster job -> existing image preparation and job engine.

Internal subprocess interface, not an IPP implementation. Capture mode never
constructs a transport. A claimed job directory is never reused or replayed.
"""

import argparse
import asyncio
import hashlib
import json
import os
import struct
from dataclasses import asdict
from pathlib import Path
from uuid import UUID

from .jobs import FramedSession, JobEngine, JobJournal
from .jobs.backends import resolve_transport, stream_factory
from .jobs.model import JobSpec
from .jobs.simulator import DEVICE_ID
from .trace import Trace

# IPP draft/normal/high. These change JPEG encoding, never thermal parameters.
QUALITY = {3: (85, "4:2:0"), 4: (90, "4:2:0"), 5: (100, "4:4:4")}


def write_private(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(data)
        out.flush()
        os.fsync(out.fileno())


def write_json(path, data):
    write_private(path, (json.dumps(data, indent=2) + "\n").encode())


def read_config(path):
    config = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if config.get("schema") != 1 or config.get("mode") not in (
        "capture",
        "simulated",
        "live",
    ):
        raise ValueError(
            "Expected schema 1 and an explicit capture/simulated/live mode"
        )
    root = Path(config["data_dir"])
    if not root.is_absolute() or not root.is_dir():
        raise ValueError("data_dir must be an existing absolute private directory")
    config["data_dir"] = root.resolve()
    config.setdefault("preparation_mode", "fill")
    if config["preparation_mode"] not in ("fill", "preserve-edges"):
        raise ValueError("preparation_mode must be fill or preserve-edges")
    if "journal_path" in config:
        journal = Path(config["journal_path"])
        if not journal.is_absolute():
            raise ValueError("journal_path must be absolute")
        config["journal_path"] = journal.resolve()
    if config["mode"] == "live":
        if not config.get("address") or len(bytes.fromhex(config["device_id"])) != 16:
            raise ValueError("Live mode needs a paired address and expected identity")
        if type(config.get("live_after_ns")) is not int or config["live_after_ns"] <= 0:
            raise ValueError("Live mode requires an explicit activation timestamp")
    elif config.get("address") or config.get("device_id"):
        raise ValueError("Offline configurations must not contain printer credentials")
    return config


def load_raster(path):
    from PIL import Image

    with path.open("rb") as source:
        header = source.read(12)
        if len(header) != 12 or header[:4] != b"ZRGB":
            raise ValueError("Invalid raster envelope")
        width, height = struct.unpack(">II", header[4:])
        if not (1 <= width <= 4096 and 1 <= height <= 4096):
            raise ValueError("Raster dimensions exceed host bounds")
        # The IPP renderer has already laid out a 58 x 87 mm page. Do not silently
        # squeeze an A4/Letter document into a photo if a client bypasses media.
        ratio = min(width, height) / max(width, height)
        if abs(ratio - 2 / 3) > 0.005:
            raise ValueError("Select requires a 58 x 87 mm page (2:3 aspect ratio)")
        size = width * height * 3
        if os.fstat(source.fileno()).st_size != 12 + size:
            raise ValueError("Truncated or trailing raster data")
        pixels = source.read(size)
    image = Image.frombytes("RGB", (width, height), pixels)
    if width > height:
        image = image.transpose(Image.Transpose.ROTATE_90)
    return image


async def submit(config, spec, journal, trace):
    simulated = config["mode"] == "simulated"
    transport = resolve_transport(config.get("transport", "auto"), simulated=simulated)
    factory = stream_factory(transport, config.get("adapter"))
    stream = factory(config.get("address"), timeout=15, trace=trace)
    session = FramedSession(stream, timeout=15, trace=trace)
    engine = JobEngine(
        session,
        journal,
        DEVICE_ID if simulated else config["device_id"],
        poll_interval=0 if simulated else 2,
        observation_timeout=180,
    )
    try:
        async with asyncio.timeout(300):
            await stream.open()
            result = asdict(await engine.run(spec))
        result["close_error"] = stream.close_error
        if simulated:
            result["payload_bytes_match"] = bytes(stream.uploaded) == spec.jpeg
            result["print_start_count"] = sum(r[0] == 12 for r in stream.requests)
        return result
    finally:
        await session.close()


def process(config_path, input_path, key, quality):
    from .images import PreparationOptions, prepare_image, safe_area_preview

    if str(UUID(key)) != key or quality not in QUALITY:
        raise ValueError("Expected canonical job UUID and an IPP quality enum")
    config = read_config(config_path)
    root = config["data_dir"]
    incoming = root / "incoming" / f"{key}.rgb"
    path = Path(input_path)
    if path.is_symlink() or path.resolve() != incoming.resolve():
        raise ValueError(
            "Input must be the matching job in the configured incoming directory"
        )
    if config["mode"] == "live" and path.stat().st_mtime_ns < config["live_after_ns"]:
        raise ValueError("Pre-activation raster cannot be submitted")
    image = load_raster(path)
    # An exclusive directory claim survives worker/host termination. Never retry
    # automatically, including a captured job after live mode is enabled.
    output = root / "jobs" / key
    output.parent.mkdir(mode=0o700, exist_ok=True)
    output.mkdir(mode=0o700)
    record = {
        "schema": 1,
        "local_id": key,
        "mode": config["mode"],
        "ipp_quality": quality,
        "preparation_mode": config["preparation_mode"],
        "source_size": list(image.size),
        "physical_ejection_confirmed": False,
    }
    write_json(output / "claim.json", record)
    try:
        q, sampling = QUALITY[quality]
        prepared = prepare_image(
            image, PreparationOptions(config["preparation_mode"], q, sampling)
        )
        spec = JobSpec(
            prepared.jpeg,
            name="Windows photo" if os.name == "nt" else "IPP photo",
            local_id=key,
            allow_alternative_sampling=sampling != "4:2:0",
            encoder_quality=q,
        )
        write_private(output / "image.jpg", spec.jpeg)
        write_private(output / "preview.png", prepared.preview_png)
        write_private(output / "safe-area-preview.png", safe_area_preview(prepared))
        write_json(output / "preparation.json", prepared.manifest)
        record.update(
            jpeg_bytes=len(spec.jpeg),
            sha256=hashlib.sha256(spec.jpeg).hexdigest(),
            encoding=spec.encoding,
        )
        if config["mode"] == "capture":
            record.update(state="captured", bluetooth_opened=False)
            code = 0
        else:
            trace = Trace(output / "frames.jsonl")
            try:
                with JobJournal(
                    config.get("journal_path", root / "jobs.sqlite")
                ) as journal:
                    result = asyncio.run(submit(config, spec, journal, trace))
                record.update(result)
            finally:
                trace.close()
            code = (
                0 if record["state"] == "completed" and not record["close_error"] else 3
            )
    except (Exception, KeyboardInterrupt) as exc:
        record.update(state="stopped", error=f"{type(exc).__name__}: {exc}")
        code = 3
    write_json(output / "result.json", record)
    # Successful jobs retain their prepared preview and receipt, not the much
    # larger raw raster. Failed/uncertain data is kept for manual diagnosis.
    if code == 0:
        path.unlink()
    return code, record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--job-key", required=True)
    parser.add_argument("--quality", type=int, choices=QUALITY, default=4)
    args = parser.parse_args(argv)
    try:
        code, record = process(args.config, args.input, args.job_key, args.quality)
    except (Exception, KeyboardInterrupt) as exc:
        code, record = 3, {"state": "stopped", "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(record))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
