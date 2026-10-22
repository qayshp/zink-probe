"""Analyze locally captured, synthetic Android render outputs; no device access."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image, ImageCms, JpegImagePlugin

matplotlib.use("Agg")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def analyze(root: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    sizes = ["768x1152", "1200x1200", "1600x900", "600x1800", "96x144", "1536x2304"]
    report = {"artifact_version": "3.0.2921.1", "runs": {}}
    for run in ("full-default", "no-pointer-tags"):
        folder = root / run / "files" / f"results-{run}"
        cases = json.loads((folder / "results.json").read_text())
        assert len(cases) == 36 and not any("error" in c for c in cases)
        assert all(c["processDataMatches"] for c in cases)
        assert all(
            (c["width"], c["height"], c["jpegQuality"]) == (768, 1152, 90)
            for c in cases
        )
        sample = Image.open(folder / "override-768x1152-plain.jpg")
        profile = ImageCms.ImageCmsProfile(io.BytesIO(sample.info["icc_profile"]))
        entry = {
            "case_count": len(cases),
            "process_data_matches_captured_compression": True,
            "all_output_dimensions": [768, 1152],
            "jpeg_quality_argument": 90,
            "jpeg": {
                "mode": sample.mode,
                "jfif_version": sample.info["jfif_version"],
                "jfif_unit": sample.info["jfif_unit"],
                "jfif_density": sample.info["jfif_density"],
                "icc_description": ImageCms.getProfileDescription(profile).strip(),
                "icc_bytes": len(sample.info["icc_profile"]),
                "sampling": JpegImagePlugin.get_sampling(sample),
                "exif_tags": len(sample.getexif()),
                "progressive": bool(sample.info.get("progressive", False)),
                "luma_quantization_first_eight": sample.quantization[0][:8],
            },
            "photofix_results": sorted(
                {
                    c["photoFixDiagnosticResult"]
                    for c in cases
                    if "photoFixDiagnosticResult" in c
                }
            ),
            "comparisons": [],
            "outputs": [],
        }
        for size in sizes:
            plain = folder / f"override-{size}-plain-output.png"
            fixed = folder / f"override-{size}-photofix-output.png"
            a, b = (
                np.array(Image.open(plain)).astype(int),
                np.array(Image.open(fixed)).astype(int),
            )
            delta = np.abs(a[:, :, :3] - b[:, :, :3])
            comparison = {
                "input": size,
                "photofix_changed_pixel_percent": round(
                    float(np.any(delta, axis=2).mean() * 100), 6
                ),
                "photofix_mean_absolute_channel_difference": round(
                    float(delta.mean()), 6
                ),
                "photofix_max_channel_difference": int(delta.max()),
            }
            for pf in ("plain", "photofix"):
                hashes = [
                    sha(folder / f"{route}-{size}-{pf}.jpg")
                    for route in ("override", "file-lanczos", "file-matrix")
                ]
                comparison[f"all_three_routes_identical_{pf}"] = len(set(hashes)) == 1
            entry["comparisons"].append(comparison)
        for case in cases:
            jpg = folder / f"{case['case']}.jpg"
            im = Image.open(jpg)
            assert im.size == (768, 1152)
            assert JpegImagePlugin.get_sampling(im) == 2
            assert not im.getexif()
            assert im.info["jfif_unit"] == 0
            entry["outputs"].append(
                {"case": case["case"], "bytes": jpg.stat().st_size, "sha256": sha(jpg)}
            )
        report["runs"][run] = entry
    report["profiles"] = json.loads(
        (root / "full-default/files/results-full-default/profiles.json").read_text()
    )
    report["offline_messages"] = json.loads(
        (root / "offline-messages.json").read_text()
    )
    (destination / "summary.json").write_text(json.dumps(report, indent=2) + "\n")

    # Analytical comparison figure using our synthetic fixtures and measured outputs.
    folder = root / "no-pointer-tags/files/results-no-pointer-tags"
    fig, axes = plt.subplots(3, 3, figsize=(10, 11), constrained_layout=True)
    for row, size in enumerate(("1200x1200", "1600x900", "600x1800")):
        for col, (suffix, title) in enumerate(
            (
                ("plain-input", "Synthetic input"),
                ("plain-output", "Select render: no PhotoFix"),
                ("photofix-output", "Select render: PhotoFix succeeds"),
            )
        ):
            axes[row, col].imshow(Image.open(folder / f"override-{size}-{suffix}.png"))
            axes[row, col].set_title(
                f"{title}\n{size if col == 0 else '768 × 1152'}", fontsize=10
            )
            axes[row, col].set_xticks([])
            axes[row, col].set_yticks([])
    fig.suptitle(
        "Original Android renderer: center crop to fill\nSynthetic inputs; emulator only; no physical print",
        fontsize=14,
    )
    fig.savefig(destination / "render-comparison.png", dpi=140)
    plt.close(fig)
    print(
        json.dumps(
            {
                run: {
                    "cases": r["case_count"],
                    "photofix": r["photofix_results"],
                    "routes_identical": all(
                        c["all_three_routes_identical_plain"]
                        and c["all_three_routes_identical_photofix"]
                        for c in r["comparisons"]
                    ),
                }
                for run, r in report["runs"].items()
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture_root", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    analyze(args.capture_root, args.destination)
