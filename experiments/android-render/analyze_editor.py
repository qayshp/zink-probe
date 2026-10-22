"""Analyze synthetic offline editor traces and generate a comparison figure."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

matplotlib.use("Agg")


def analyze(folder: Path, destination: Path) -> None:
    cases = json.loads((folder / "editor-results.json").read_text())
    assert len(cases) == 38 and not any("error" in case for case in cases)
    destination.mkdir(parents=True, exist_ok=True)
    for case in cases:
        name = case["case"]
        final_file = folder / f"{name}-final.png"
        final = Image.open(final_file)
        assert final.size == (768, 1152)
        pixels = np.array(final)[:, :, :3]
        case["near_white_pixel_percent"] = round(
            float(np.all(pixels > 245, axis=2).mean() * 100), 4
        )
        case["sample_colors_tl_tr_bl_br"] = [
            pixels[y, x].tolist()
            for y, x in [(200, 150), (200, 600), (950, 150), (950, 600)]
        ]
        encoded = (folder / f"{name}-edited.bin").read_bytes()
        assert encoded.startswith(b"\xff\xd8\xff")
        case["intermediate_encoding"] = "JPEG"
        case["intermediate_bytes"] = len(encoded)
        case["final_png_sha256"] = hashlib.sha256(final_file.read_bytes()).hexdigest()
    indexed = {case["case"]: case for case in cases}
    assert indexed["96x144-exif1-identity"]["measuredWidth"] == 1000
    assert indexed["96x144-exif1-identity"]["measuredHeight"] == 1500
    assert indexed["1024x1536-exif1-identity"]["widthScale"] == 2.56
    assert 32 < indexed["1200x1200-exif1-fit-once"]["near_white_pixel_percent"] < 34
    assert indexed["1200x1200-exif1-fit-twice"]["near_white_pixel_percent"] < 1
    assert 74 < indexed["1200x1800-exif1-zoom-half"]["near_white_pixel_percent"] < 76
    for orientation in (2, 4, 5, 7, 8):
        assert (
            indexed[f"1200x1800-exif{orientation}-identity"][
                "sample_colors_tl_tr_bl_br"
            ]
            == indexed["1200x1800-exif1-identity"]["sample_colors_tl_tr_bl_br"]
        )
    assert (
        indexed["1200x1800-exif3-identity"]["sample_colors_tl_tr_bl_br"]
        == indexed["1200x1800-exif6-identity"]["sample_colors_tl_tr_bl_br"]
    )
    report = {
        "vendor_version": "3.0.2921.1",
        "viewport": [400, 600],
        "photofix_skipped": True,
        "physical_device_connected": False,
        "case_count": len(cases),
        "cases": cases,
    }
    (destination / "editor-summary.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    panels = [
        ("1800x1200-exif1-identity-input.jpg", "Landscape source\n1800 × 1200"),
        (
            "1800x1200-exif1-identity-final.png",
            "Editor auto-rotation + render\n768 × 1152",
        ),
        (
            "1200x1800-exif1-zoom-half-final.png",
            "Portrait zoomed to 50%\nWhite space survives rendering",
        ),
        (
            "1200x1200-exif1-fit-once-final.png",
            "Square: fit once\nWhole image, white bands",
        ),
        (
            "1200x1200-exif1-fit-twice-final.png",
            "Square: toggle again to fill\nSides cropped, no bands",
        ),
        (
            "1200x1800-exif1-rotate90-final.png",
            "Manual 90° in fixed canvas\nClipping plus white bands",
        ),
    ]
    fig, axes = plt.subplots(2, 3, figsize=(10, 10), constrained_layout=True)
    for axis, (filename, title) in zip(axes.flat, panels, strict=True):
        axis.imshow(Image.open(folder / filename))
        axis.set_title(title, fontsize=10)
        axis.set_xticks([])
        axis.set_yticks([])
    fig.suptitle(
        "Original Android editor and Select renderer\nSynthetic local images; no printing",
        fontsize=14,
    )
    fig.savefig(destination / "editor-comparison.png", dpi=140)
    plt.close(fig)
    print(f"Validated {len(cases)} editor cases; wrote summary and figure.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture_folder", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    analyze(args.capture_folder, args.destination)
