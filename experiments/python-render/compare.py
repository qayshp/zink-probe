"""Compare our Python preparation with existing offline Android synthetic captures."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import platform
from pathlib import Path

import numpy as np
import PIL
from PIL import Image, JpegImagePlugin, features
from prepare import editor_transform, jpeg_bytes, prepare


def pixels(image):
    return np.array(image.convert("RGB"), dtype=np.int16)


def difference(left, right):
    assert left.size == right.size
    delta = np.abs(pixels(left) - pixels(right))
    return {
        "mean_absolute_channel_error": round(float(delta.mean()), 6),
        "maximum_channel_error": int(delta.max()),
        "changed_pixel_percent": round(float(np.any(delta, axis=2).mean() * 100), 6),
        "pixel_exact": bool(not delta.any()),
    }


def without_icc(data):
    """Remove ICC APP2 markers only, preserving the complete encoded scan."""
    assert data[:2] == b"\xff\xd8"
    result = bytearray(data[:2])
    offset = 2
    while offset < len(data):
        assert data[offset] == 255
        marker = data[offset + 1]
        if marker in (0xDA, 0xD9):
            result.extend(data[offset:])
            return bytes(result)
        length = int.from_bytes(data[offset + 2 : offset + 4], "big")
        end = offset + 2 + length
        assert length >= 2 and end <= len(data)
        if not (
            marker == 0xE2 and data[offset + 4 : end].startswith(b"ICC_PROFILE\x00")
        ):
            result.extend(data[offset:end])
        offset = end
    raise ValueError("Incomplete JPEG")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compare(root, destination):
    rows = []
    for run in ("full-default", "no-pointer-tags"):
        folder = root / run / "files" / f"results-{run}"
        cases = json.loads((folder / "results.json").read_text())
        assert len(cases) == 36 and not any("error" in c for c in cases)
        for case in cases:
            name = case["case"]
            source = folder / f"{name}-input.png"
            reference = folder / f"{name}-output.png"
            android_jpeg = folder / f"{name}.jpg"
            result = prepare(Image.open(source))
            encoded = jpeg_bytes(result)
            python_jpeg = Image.open(io.BytesIO(encoded))
            original_jpeg = Image.open(android_jpeg)
            rows.append(
                {
                    "run": run,
                    "case": name,
                    "input_sha256": sha(source),
                    "android_png_sha256": sha(reference),
                    "android_jpeg_sha256": sha(android_jpeg),
                    "python_jpeg_sha256": hashlib.sha256(encoded).hexdigest(),
                    "raster": difference(result, Image.open(reference)),
                    "decoded_jpeg": difference(python_jpeg, original_jpeg),
                    "jpeg_byte_exact": encoded == android_jpeg.read_bytes(),
                    "jpeg_exact_except_icc": encoded
                    == without_icc(android_jpeg.read_bytes()),
                    "python_jpeg_bytes": len(encoded),
                    "android_jpeg_bytes": android_jpeg.stat().st_size,
                    "quantization_tables_equal": python_jpeg.quantization
                    == original_jpeg.quantization,
                    "python_sampling": JpegImagePlugin.get_sampling(python_jpeg),
                    "android_sampling": JpegImagePlugin.get_sampling(original_jpeg),
                    "python_icc_bytes": len(python_jpeg.info.get("icc_profile", b"")),
                    "android_icc_bytes": len(
                        original_jpeg.info.get("icc_profile", b"")
                    ),
                }
            )
    editor = []
    folder = root / "editor-fit/files/results-editor-fit"
    cases = json.loads((folder / "editor-results.json").read_text())
    assert len(cases) == 38 and not any("error" in c for c in cases)
    for case in cases:
        name = case["case"]
        measured = folder / f"{name}-measured.jpg"
        edited = folder / f"{name}-edited.png"
        final = folder / f"{name}-final.png"
        transformed = editor_transform(Image.open(measured), case["matrix"])
        # Android saves its edited bitmap as JPEG 100, then decodes for rendering.
        decoded_edit = Image.open(io.BytesIO(jpeg_bytes(transformed, quality=100)))
        editor.append(
            {
                "case": name,
                "matrix": case["matrix"],
                "measured_input_sha256": sha(measured),
                "android_edited_sha256": sha(edited),
                "android_final_sha256": sha(final),
                "edited_jpeg_decoded": difference(decoded_edit, Image.open(edited)),
                "python_edit_then_final": difference(
                    prepare(decoded_edit), Image.open(final)
                ),
                "final_from_android_edited_bitmap": difference(
                    prepare(Image.open(edited)), Image.open(final)
                ),
            }
        )
    report = {
        "scope": "Offline prepared-bitmap render and captured editor-matrix replay; no PhotoFix",
        "android_apk_version": "3.0.2921.1 / 74251",
        "python": platform.python_version(),
        "pillow": PIL.__version__,
        "numpy": np.__version__,
        "libjpeg_turbo": features.version_feature("libjpeg_turbo"),
        "render_cases": rows,
        "editor_cases": editor,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n")
    for row in rows:
        if (
            row["run"] == "full-default"
            and row["case"].startswith("override-")
            and row["case"].endswith("-plain")
        ):
            print(row["case"], row["raster"], "JPEG", row["decoded_jpeg"])
    print(
        "Editor replay max mean error:",
        max(r["python_edit_then_final"]["mean_absolute_channel_error"] for r in editor),
    )
    print("Counts:", len(rows), "render;", len(editor), "editor")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture_root", type=Path)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    compare(args.capture_root, args.report)
