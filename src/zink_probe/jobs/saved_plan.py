"""Offline, self-contained submission intentions with stable local job IDs.

Checksums detect accidental edits, not hostile tampering. The journal remains
the authority for attempted jobs; copying a plan never grants a safe retry.
"""

import hashlib
import io
import json
import os
from pathlib import Path

from .adapter_checks import device_id
from .model import JobSpec, require
from .simulator import DEVICE_ID

MAX_JPEG = 16 * 1024 * 1024


def bounded_read(path, maximum):
    with Path(path).open("rb") as file:
        data = file.read(maximum + 1)
    require(len(data) <= maximum, "Input exceeds size bound")
    return data


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def decode_check(jpeg):
    try:
        from PIL import Image, ImageFile
    except ImportError as exc:
        raise RuntimeError("JPEG validation requires zink-probe[images]") from exc
    require(
        not ImageFile.LOAD_TRUNCATED_IMAGES, "Truncated JPEG decoding must be disabled"
    )
    with Image.open(io.BytesIO(jpeg)) as image:
        require(
            image.format == "JPEG"
            and image.size == (768, 1152)
            and image.mode == "RGB",
            "Expected a fully decodable 768x1152 RGB JPEG",
        )
        image.load()


def create_plan(
    bundle,
    destination,
    *,
    expected_device_id,
    simulated=False,
    name="Select photo",
    copies=1,
    allow_alternative_sampling=False,
):
    """Validate a preparation bundle, snapshot its bytes, and create a new plan."""
    bundle, destination = Path(bundle), Path(destination)
    expected_device_id = device_id(expected_device_id)
    require(type(simulated) is bool, "Invalid simulation mode")
    require(
        not simulated or expected_device_id == DEVICE_ID, "Wrong simulated identity"
    )
    manifest_bytes = bounded_read(bundle / "manifest.json", 1024 * 1024)
    manifest = json.loads(manifest_bytes)
    require(
        manifest["schema_version"] == 1 and manifest["offline"] is True,
        "Unsupported preparation bundle",
    )
    jpeg = bounded_read(bundle / "image.jpg", MAX_JPEG)
    mode = manifest["selected_mode"]
    require(mode in ("fit", "fill", "preserve-edges"), "Invalid preparation mode")
    source_encoding = manifest["variants"][mode]["encoding"]
    spec = JobSpec(
        jpeg,
        name=name,
        copies=copies,
        allow_alternative_sampling=allow_alternative_sampling,
        encoder_quality=source_encoding["quality"],
    )
    require(
        manifest["files"]["image.jpg"] == {"bytes": len(jpeg), "sha256": spec.sha256},
        "Preparation JPEG hash or size mismatch",
    )
    require(
        source_encoding["sha256"] == spec.sha256
        and source_encoding["bytes"] == len(jpeg)
        and source_encoding["subsampling"] == spec.encoding["sampling"]
        and source_encoding["quantization_all_ones"]
        == spec.encoding["quantization_all_ones"],
        "Preparation encoding metadata mismatch",
    )
    decode_check(jpeg)
    intent = {
        "schema_version": 1,
        "local_id": spec.local_id,
        "device_id": expected_device_id,
        "simulated": simulated,
        "name": spec.name,
        "copies": spec.copies,
        "allow_alternative_sampling": allow_alternative_sampling,
        "encoder_quality": spec.encoder_quality,
        "payload_sha256": spec.sha256,
        "payload_bytes": len(jpeg),
        "encoding": spec.encoding,
        "preparation_sha256": digest(manifest_bytes),
    }
    envelope = {"intent": intent, "intent_sha256": digest(canonical(intent))}
    # Publish the complete metadata last; an interrupted plan cannot be loaded.
    destination.mkdir(mode=0o700)
    created = []
    try:
        for filename, content in (
            ("image.jpg", jpeg),
            ("job.json", canonical(envelope) + b"\n"),
        ):
            path = destination / filename
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created.append(path)
            with os.fdopen(fd, "wb") as file:
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
    except BaseException:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        try:
            destination.rmdir()
        except OSError:
            pass
        raise
    return intent, spec


def load_plan(directory):
    directory = Path(directory)
    envelope = json.loads(bounded_read(directory / "job.json", 1024 * 1024))
    intent = envelope["intent"]
    require(
        envelope["intent_sha256"] == digest(canonical(intent)),
        "Job plan checksum mismatch",
    )
    require(
        set(intent)
        == {
            "schema_version",
            "local_id",
            "device_id",
            "simulated",
            "name",
            "copies",
            "allow_alternative_sampling",
            "encoder_quality",
            "payload_sha256",
            "payload_bytes",
            "encoding",
            "preparation_sha256",
        }
        and intent["schema_version"] == 1,
        "Unsupported job plan",
    )
    require(
        type(intent["simulated"]) is bool
        and type(intent["allow_alternative_sampling"]) is bool,
        "Invalid job flags",
    )
    require(
        device_id(intent["device_id"]) == intent["device_id"], "Noncanonical device ID"
    )
    require(
        not intent["simulated"] or intent["device_id"] == DEVICE_ID,
        "Wrong simulated identity",
    )
    spec = JobSpec(
        bounded_read(directory / "image.jpg", MAX_JPEG),
        name=intent["name"],
        copies=intent["copies"],
        local_id=intent["local_id"],
        allow_alternative_sampling=intent["allow_alternative_sampling"],
        encoder_quality=intent["encoder_quality"],
    )
    require(
        spec.sha256 == intent["payload_sha256"]
        and len(spec.jpeg) == intent["payload_bytes"],
        "Job JPEG hash or size mismatch",
    )
    require(spec.encoding == intent["encoding"], "Job encoding metadata mismatch")
    decode_check(spec.jpeg)
    return intent, spec


def summary(intent):
    return {
        key: intent[key]
        for key in (
            "local_id",
            "simulated",
            "name",
            "copies",
            "payload_sha256",
            "payload_bytes",
            "encoding",
        )
    }
