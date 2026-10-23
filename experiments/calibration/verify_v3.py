"""Verify CAL-03 controls and retain the decoded-JPEG measurement baseline."""

import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent / "package-v3"


def verify():
    manifest = json.loads((ROOT / "manifest.json").read_text())
    comparison = json.loads((ROOT / "comparison.json").read_text())
    for name, digest in {**manifest["sha256"], **comparison["files"]}.items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, name
    source = np.asarray(Image.open(ROOT / "source.png").convert("RGB"), dtype=int)
    decoded = np.asarray(Image.open(ROOT / "python.jpg").convert("RGB"), dtype=int)
    assert source.shape == decoded.shape == (1152, 768, 3)
    assert np.array_equal(source, np.asarray(Image.open(ROOT / "python.png")))
    assert len(comparison["cases"]) == 6
    assert all(
        c["processDataMatches"]
        and "error" not in c
        and c["python_vs_android_bitmap"]["pixel_exact"]
        and c["python_vs_android_decoded_jpeg"]["pixel_exact"]
        and c["jpeg_equal_except_icc"]
        for c in comparison["cases"]
    )
    patches = manifest["patches"]
    groups = defaultdict(list)
    by_name = {p["name"]: p for p in patches}
    assert len(by_name) == len(patches) == 163

    def region(image, patch):
        x0, y0, x1, y1 = patch["box_exclusive"]
        return image[y0:y1, x0:x1]

    for p in patches:
        x0, y0, x1, y1 = p["box_exclusive"]
        assert 64 <= x0 < x1 <= 688 and 64 <= y0 < y1 <= 1084, p["name"]
        if p.get("repeat_group"):
            groups[p["repeat_group"]].append(p)
        for other in patches:
            if p is other:
                continue
            a0, b0, a1, b1 = other["box_exclusive"]
            assert not (max(x0, a0) < min(x1, a1) and max(y0, b0) < min(y1, b1)), (
                p["name"],
                other["name"],
            )

    repeats = []
    for name, members in groups.items():
        arrays = [region(source, p) for p in members]
        assert all(np.array_equal(a, arrays[0]) for a in arrays), name
        jpeg = [region(decoded, p) for p in members]
        repeats.append(
            {
                "group": name,
                "patch_names": [p["name"] for p in members],
                "source_pixel_exact": True,
                "maximum_decoded_jpeg_difference_from_first": int(
                    max(np.abs(a - jpeg[0]).max() for a in jpeg)
                ),
            }
        )
    assert len(repeats) == 20  # Five colors: solids, targets, V repeat, H repeat.

    for color, rgb in manifest["colors"].items():
        for tag in ("r1", "r2", "r4", "g6", "g14", "repeat-r2"):
            v = region(source, by_name[f"{tag}-{color}-vertical"])
            h = region(source, by_name[f"{tag}-{color}-horizontal"])
            assert np.array_equal(v, h.transpose(1, 0, 2))
        for gap, target_y, heated_x in [(8, 640, 64), (32, 800, 128)]:
            hot = by_name[f"target-g{gap}-{color}-heated"]
            ref = by_name[f"target-g{gap}-{color}-reference"]
            assert hot["box_exclusive"][1] == ref["box_exclusive"][1] == target_y
            assert hot["box_exclusive"][0] % 128 == heated_x % 128
            for end, start in [("A", target_y - gap - 24), ("B", target_y + 16 + gap)]:
                block = by_name[f"block-g{gap}-{color}-heated-{end}"]
                blank = by_name[f"block-g{gap}-{color}-reference-{end}"]
                assert block["box_exclusive"][1] == start
                assert np.all(region(source, block) == rgb)
                assert np.all(region(source, blank) == 255)

    rows = []
    for p in patches:
        if p["kind"] != "lines":
            continue
        # C absorbs red, M green, Y blue in this RGB file. This measures code
        # values in a JPEG, not physical dye densities or calibrated contrast.
        channel = {"K": 0, "G128": 0, "C": 0, "M": 1, "Y": 2}[p["color"]]
        sample = region(decoded, p)[8:-8, 8:-8, channel]
        profile = sample.mean(axis=0 if p["orientation"] == "vertical" else 1)
        rows.append(
            {
                "patch": p["name"],
                "color": p["color"],
                "orientation": p["orientation"],
                "run_px": p["run_px"],
                "gap_px": p["gap_px"],
                "rgb_channel": "RGB"[channel],
                "decoded_channel_min": float(profile.min()),
                "decoded_channel_max": float(profile.max()),
                "normalized_encoded_modulation": round(
                    float((profile.max() - profile.min()) / (255 - p["rgb"][channel])),
                    6,
                ),
            }
        )
    result = {
        "chart_id": "SELECT-CAL-03",
        "physical_print_performed": False,
        "source_sha256": manifest["sha256"]["source.png"],
        "payload_sha256": manifest["sha256"]["python.jpg"],
        "patch_count": len(patches),
        "source_repeat_groups": repeats,
        "all_six_android_cases_pixel_exact": True,
        "all_six_android_jpegs_equal_except_icc": True,
        "encoding_measurement": "Central 32x32 of each 48x48 patch; average perpendicular to stripe variation. Encoded channel range divided by requested white-to-color channel range. Values may exceed one due to JPEG rounding/ringing; not reflectance, physical MTF or a cross-color perceptual metric.",
        "line_baselines": rows,
    }
    (ROOT / "verification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(
        "CAL-03: hashes, 163 non-overlapping patches, 20 repeat groups, matched axes,"
    )
    print("conditioning geometry and six original-Android comparisons passed.")
    print("Retained 60 decoded-JPEG line baselines; nothing transmitted to a printer.")


if __name__ == "__main__":
    verify()
