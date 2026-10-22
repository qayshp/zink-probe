"""Analyze captured original-Android renderings of our own calibration chart."""

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "python-render"))
from compare import difference, without_icc  # noqa: E402


def analyze(capture, out=ROOT / "package"):
    out = Path(out)
    cases = json.loads((capture / "results.json").read_text())
    assert len(cases) == 6 and all(
        "error" not in c and c["processDataMatches"] for c in cases
    )
    source = Image.open(out / "source.png")
    python = Image.open(out / "python.png")
    report = {
        "scope": "Original Android renderer; synthetic chart only; no printer access",
        "apk_version": "3.0.2921.1 / 74251",
        "pointer_tagging_disabled_in_harness": True,
        "cases": [],
    }
    for c in cases:
        name = c["case"]
        inp = Image.open(capture / f"{name}-input.png")
        bitmap = Image.open(capture / f"{name}-output.png")
        jpg = capture / f"{name}.jpg"
        assert difference(source, inp)["pixel_exact"]
        report["cases"].append(
            {
                **c,
                "python_vs_android_bitmap": difference(python, bitmap),
                "python_vs_android_decoded_jpeg": difference(
                    Image.open(out / "python.jpg"), Image.open(jpg)
                ),
                "jpeg_equal_except_icc": (out / "python.jpg").read_bytes()
                == without_icc(jpg.read_bytes()),
                "jpeg_sha256": hashlib.sha256(jpg.read_bytes()).hexdigest(),
            }
        )
    for tag, base in [("plain", "android"), ("photofix", "android-photofix")]:
        name = f"override-768x1152-{tag}"
        shutil.copyfile(capture / f"{name}-output.png", out / f"{base}.png")
        shutil.copyfile(capture / f"{name}.jpg", out / f"{base}.jpg")
    manifest = json.loads((out / "manifest.json").read_text())
    rows = []
    decoded = Image.open(out / "python.jpg")
    for patch in manifest.get(
        "line_patches", [p for p in manifest.get("patches", []) if p["kind"] == "lines"]
    ):
        box = patch["box_exclusive"]
        region = np.array(decoded.crop(box).convert("L"), dtype=float)
        axis = 0 if patch["orientation"] == "vertical" else 1
        signal = region.mean(axis=axis)
        rows.append(
            {
                **patch,
                "decoded_jpeg_luma_min": float(signal.min()),
                "decoded_jpeg_luma_max": float(signal.max()),
                "source_vs_decoded_jpeg": difference(
                    source.crop(box), decoded.crop(box)
                ),
            }
        )
    report["line_patches"] = rows
    report["source_vs_encoded_jpeg"] = difference(source, decoded)
    report["files"] = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(out.glob("*"))
        if p.suffix in {".jpg", ".png"}
    }
    (out / "comparison.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "cases": len(cases),
                "all_pixel_exact": all(
                    c["python_vs_android_bitmap"]["pixel_exact"]
                    for c in report["cases"]
                ),
                "all_jpeg_equal_except_icc": all(
                    c["jpeg_equal_except_icc"] for c in report["cases"]
                ),
                "source_vs_jpeg": report["source_vs_encoded_jpeg"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--package", type=Path, default=ROOT / "package")
    args = parser.parse_args()
    analyze(args.capture, args.package)
