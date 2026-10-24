"""Retain exact host-decoded CAL-03 quality-100 4:4:4 measurement references."""

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "experiments/calibration/package-v3"
PAYLOAD = ROOT / "experiments/jpeg-quality/q100-444-optimized.jpg"
SHA256 = "50b58d8cc26ba7349e7874861e8c76b16b4b0f5ac6d2962fa0051d970de83944"


def verify():
    data = PAYLOAD.read_bytes()
    assert hashlib.sha256(data).hexdigest() == SHA256
    image = Image.open(PAYLOAD)
    assert image.size == (768, 1152) and image.mode == "RGB"
    assert not image.info.get("progressive")
    assert all(h == v == 1 for _, h, v, _ in image.layer)
    assert all(value == 1 for table in image.quantization.values() for value in table)
    pixels = np.asarray(image, dtype=int)
    manifest = json.loads((PACKAGE / "manifest.json").read_text())
    assert (
        hashlib.sha256((PACKAGE / "source.png").read_bytes()).hexdigest()
        == manifest["sha256"]["source.png"]
    )
    groups, lines = {}, []
    for patch in manifest["patches"]:
        x0, y0, x1, y1 = patch["box_exclusive"]
        block = pixels[y0:y1, x0:x1]
        if patch.get("repeat_group"):
            groups.setdefault(patch["repeat_group"], []).append((patch["name"], block))
        if patch["kind"] == "lines":
            channel = {"K": 0, "G128": 0, "C": 0, "M": 1, "Y": 2}[patch["color"]]
            profile = block[8:-8, 8:-8, channel].mean(
                axis=0 if patch["orientation"] == "vertical" else 1
            )
            lines.append(
                {
                    "patch": patch["name"],
                    "rgb_channel": "RGB"[channel],
                    "min": float(profile.min()),
                    "max": float(profile.max()),
                    "normalized_encoded_modulation": float(
                        (profile.max() - profile.min()) / (255 - patch["rgb"][channel])
                    ),
                }
            )
    repeats = [
        {
            "group": group,
            "patches": [name for name, _ in members],
            "maximum_decoded_rgb_difference_from_first": int(
                max(np.abs(block - members[0][1]).max() for _, block in members)
            ),
        }
        for group, members in groups.items()
    ]
    assert len(repeats) == 20 and len(lines) == 60
    assert all(r["maximum_decoded_rgb_difference_from_first"] == 0 for r in repeats)
    result = {
        "payload": str(PAYLOAD.relative_to(ROOT)),
        "sha256": SHA256,
        "bytes": len(data),
        "size": image.size,
        "sampling": "4:4:4",
        "quality": 100,
        "quantization_all_ones": True,
        "baseline": True,
        "source_unchanged": True,
        "source_sha256": manifest["sha256"]["source.png"],
        "repeat_groups": repeats,
        "line_baselines": lines,
        "scope": "Host-decoded exact payload reference; no physical-print measurements",
    }
    (PACKAGE / "quality100-verification.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )
    print(
        "CAL-03 quality-100 4:4:4: pinned payload, 20 identical repeat groups, 60 line baselines verified."
    )


if __name__ == "__main__":
    verify()
