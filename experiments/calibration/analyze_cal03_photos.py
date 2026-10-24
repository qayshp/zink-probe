"""Exploratory CAL-03 photograph measurements; never edits photos or contacts hardware.

Raw photographs are private. Mapping uses approximate manually selected frame
crosses and a planar homography, which cannot correct paper curl/lens distortion.
Results are nonlinear photo code values, not reflectance, dye density or MTF.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from analyze_photo_geometry import projective_map, transform
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "experiments/calibration/package-v3"
PAYLOAD = ROOT / "experiments/jpeg-quality/q100-444-optimized.jpg"
SHA256 = "50b58d8cc26ba7349e7874861e8c76b16b4b0f5ac6d2962fa0051d970de83944"
# Source TL, TR, BL, BR in the 1368x1824 viewing coordinate system.
# Saved originals are 2880x3840; these are selections, not subpixel fits.
CROSSES = [
    [[1134, 1707], [84, 1715], [1132, 72], [88, 75]],
    [[68, 49], [1147, 47], [80, 1740], [1151, 1724]],
]
COLORS = {"K": 0, "G128": 0, "C": 0, "M": 1, "Y": 2}


def sample(pixels, matrix, box, step=0.25):
    """Bilinear numerical samples at chart coordinates; no image output saved."""
    x0, y0, x1, y1 = box
    x, y = np.meshgrid(np.arange(x0, x1, step), np.arange(y0, y1, step))
    u, v = transform(matrix, np.c_[x.ravel(), y.ravel()]).T
    a, b = np.floor(u).astype(int), np.floor(v).astype(int)
    assert a.min() >= 0 and b.min() >= 0
    assert a.max() + 1 < pixels.shape[1] and b.max() + 1 < pixels.shape[0]
    du, dv = (u - a)[:, None], (v - b)[:, None]
    values = (
        pixels[b, a] * (1 - du) * (1 - dv)
        + pixels[b, a + 1] * du * (1 - dv)
        + pixels[b + 1, a] * (1 - du) * dv
        + pixels[b + 1, a + 1] * du * dv
    )
    return values.reshape((*x.shape, 3))


def interior(patch, dx=8, dy=8):
    x0, y0, x1, y1 = patch["box_exclusive"]
    return [x0 + dx, y0 + dy, x1 - dx, y1 - dy]


def modulation(values, orientation, channel):
    profile = values[:, :, channel].mean(axis=0 if orientation == "vertical" else 1)
    return float(np.diff(np.percentile(profile, [5, 95]))[0])


def target(pixels, matrix, patch, channel):
    x0, y0, x1, y1 = patch["box_exclusive"]
    rows = sample(pixels, matrix, [x0 + 8, y0 - 8, x1 - 8, y1 + 8])
    gradient = np.diff(rows[:, :, channel].mean(axis=1))
    # Search separately around each expected edge to exclude conditioning blocks.
    top = y0 - 8 + (np.argmin(gradient[:64]) + 0.5) / 4
    bottom = y0 - 8 + (np.argmax(gradient[64:]) + 64 + 0.5) / 4
    center = (top + bottom) / 2
    assert 10 < bottom - top < 22, "Unreliable target edge registration"
    center_box = [x0 + 8, center - 3, x1 - 8, center + 3]
    rgb = sample(pixels, matrix, center_box).mean(axis=(0, 1))
    white = (
        sample(pixels, matrix, [x0 - 6, center - 3, x0 - 3, center + 3]).mean((0, 1))
        + sample(pixels, matrix, [x1 + 3, center - 3, x1 + 6, center + 3]).mean((0, 1))
    ) / 2
    assert white.min() > 0
    shifts = []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            box = [
                center_box[0] + dx,
                center_box[1] + dy,
                center_box[2] + dx,
                center_box[3] + dy,
            ]
            shifts.append(sample(pixels, matrix, box).mean((0, 1)))
    return {
        "rgb_mean": rgb.tolist(),
        "local_white_rgb": white.tolist(),
        "white_normalized_rgb": (255 * rgb / white).tolist(),
        "center_box_chart_coordinates": center_box,
        "edge_height_chart_pixels": float(bottom - top),
        "shifted_rgb_min": np.min(shifts, axis=0).tolist(),
        "shifted_rgb_max": np.max(shifts, axis=0).tolist(),
    }


def analyze(photo_dir):
    assert hashlib.sha256(PAYLOAD.read_bytes()).hexdigest() == SHA256
    manifest = json.loads((PACKAGE / "manifest.json").read_text())
    patches = {p["name"]: p for p in manifest["patches"]}
    jpeg = np.asarray(Image.open(PAYLOAD).convert("RGB"), dtype=float)
    groups = {}
    for p in patches.values():
        if p["kind"] == "history-target":
            x0, y0, x1, y1 = p["box_exclusive"]
            groups.setdefault(p["color"], []).append(jpeg[y0:y1, x0:x1])
    for blocks in groups.values():
        assert len(blocks) == 4 and all(np.array_equal(blocks[0], b) for b in blocks)
    output = {
        "payload_sha256": SHA256,
        "leading_end": "B / TWO; operator confirmation",
        "physical_rotation": "90 degrees relative to camera, reported by operator; not inferred from saved orientation",
        "scope": "Two photographs of one sheet; exploratory nonlinear RGB code-value measurements",
        "all_four_targets_per_color_identical_in_decoded_printed_jpeg": True,
        "limitations": [
            "Manual planar registration does not correct curl or lens distortion",
            "No controlled exposure, white balance, lighting, focus or linear camera response",
            "Phone processing and image-dependent local contrast remain confounders",
            "Oversampled numerical grid adds no captured resolution",
            "No native DPI, thermal time constant, MTF or isolated dye activation inferred",
        ],
        "photos": [],
    }
    for number, crosses in enumerate(CROSSES, 1):
        name = f"{number}-Photo-{number}.jpg"
        path = photo_dir / name
        image = Image.open(path)
        assert image.size == (2880, 3840)
        pixels = np.asarray(image.convert("RGB"))
        points = np.array(crosses) * (2880 / 1368)
        matrix = projective_map(manifest["reference_centers"], points)
        np.testing.assert_allclose(
            transform(matrix, manifest["reference_centers"]), points
        )
        record = {
            "name": name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "dimensions": list(image.size),
            "manual_crosses_source_order_photo_px": points.tolist(),
            "source_to_photo_matrix": matrix.tolist(),
            "lines": [],
            "conditioning": [],
        }
        for color, channel in COLORS.items():
            for row in ("r1", "r2", "r4", "g6", "g14", "repeat-r2"):
                measured, baseline = [], []
                for orient in ("vertical", "horizontal"):
                    p = patches[f"{row}-{color}-{orient}"]
                    measured.append(
                        modulation(sample(pixels, matrix, interior(p)), orient, channel)
                    )
                    x0, y0, x1, y1 = interior(p)
                    baseline.append(modulation(jpeg[y0:y1, x0:x1], orient, channel))
                record["lines"].append(
                    {
                        "color": color,
                        "row": row,
                        "channel": "RGB"[channel],
                        "photo_modulation_V_H": measured,
                        "photo_H_over_V": measured[1] / measured[0],
                        "decoded_jpeg_modulation_V_H": baseline,
                    }
                )
            for gap in (8, 32):
                members = {
                    lane: target(
                        pixels,
                        matrix,
                        patches[f"target-g{gap}-{color}-{lane}"],
                        channel,
                    )
                    for lane in ("heated", "reference")
                }
                hot, ref = members["heated"], members["reference"]
                record["conditioning"].append(
                    {
                        "color": color,
                        "gap_input_px": gap,
                        "members": members,
                        "hot_minus_ref_rgb": (
                            np.array(hot["rgb_mean"]) - ref["rgb_mean"]
                        ).tolist(),
                        "hot_minus_ref_white_normalized_rgb": (
                            np.array(hot["white_normalized_rgb"])
                            - ref["white_normalized_rgb"]
                        ).tolist(),
                        "independent_one_pixel_shift_difference_min": (
                            np.array(hot["shifted_rgb_min"]) - ref["shifted_rgb_max"]
                        ).tolist(),
                        "independent_one_pixel_shift_difference_max": (
                            np.array(hot["shifted_rgb_max"]) - ref["shifted_rgb_min"]
                        ).tolist(),
                    }
                )
        output["photos"].append(record)
    return output


def plot(result):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.3), layout="constrained")
    colors = list(COLORS)
    for i, photo in enumerate(result["photos"]):
        lines = {p["color"]: p for p in photo["lines"] if p["row"] == "r2"}
        axes[0].plot(
            range(5),
            [lines[c]["photo_H_over_V"] for c in colors],
            "o-",
            label=f"Photo {i + 1}",
            linewidth=1.4,
        )
        for gap, marker in [(8, "o"), (32, "s")]:
            values = {
                p["color"]: p for p in photo["conditioning"] if p["gap_input_px"] == gap
            }
            axes[1].plot(
                np.arange(2) + (i - 0.5) * 0.06,
                [values[c]["hot_minus_ref_rgb"][0] for c in ["K", "G128"]],
                marker + ("-" if gap == 8 else "--"),
                color=["#2065a3", "#cf7220"][i],
                label=f"Photo {i + 1}, gap {gap}",
            )
    axes[0].axhline(1, color="gray", linestyle="--", linewidth=1)
    axes[0].set(
        xticks=range(5),
        xticklabels=colors,
        ylim=(0, 2.15),
        ylabel="Captured modulation ratio H / V",
        title="Matched 2 px bars / 2 px gaps\nAbove 1: H stronger; below 1: V stronger",
    )
    axes[1].axhline(0, color="gray", linewidth=1)
    axes[1].set(
        xticks=[0, 1],
        xticklabels=[
            "Black column\n(target gray 128)",
            "Gray column\n(target gray 192)",
        ],
        ylabel="HOT minus REF: red photo code value",
        title="Identical pale targets near solid blocks\nPositive: HOT photographed lighter",
    )
    for ax in axes:
        ax.spines[["top", "right"]].set_visible(False)
        ax.legend(fontsize=8)
        ax.grid(axis="y", alpha=0.2)
    fig.suptitle(
        "CAL-03: exploratory photo comparisons, not calibrated printer response",
        fontsize=12,
    )
    fig.savefig(PACKAGE / "photo-comparison.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--photo-dir", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.photo_dir)
    (PACKAGE / "photo-analysis.json").write_text(json.dumps(result, indent=2) + "\n")
    plot(result)
    for photo in result["photos"]:
        print(photo["name"])
        for p in photo["conditioning"]:
            if p["color"] in ("K", "G128"):
                print(
                    p["color"],
                    p["gap_input_px"],
                    np.round(p["hot_minus_ref_rgb"], 2),
                    "shift bounds R",
                    round(p["independent_one_pixel_shift_difference_min"][0], 2),
                    round(p["independent_one_pixel_shift_difference_max"][0], 2),
                )
