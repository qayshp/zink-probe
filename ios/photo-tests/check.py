"""Offline Apple pipeline checks; optional comparison with saved Android fixtures."""

import argparse
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageChops, ImageCms, ImageOps, ImageStat, JpegImagePlugin

parser = argparse.ArgumentParser()
parser.add_argument("executable")
parser.add_argument("output", type=Path)
parser.add_argument("--android", type=Path)
a = parser.parse_args()
a.output.mkdir(parents=True, exist_ok=True)
base = Image.new("RGB", (120, 80), "white")
for box, color in [
    ((0, 0, 60, 40), "red"),
    ((60, 0, 120, 40), "green"),
    ((0, 40, 60, 80), "blue"),
    ((60, 40, 120, 80), "yellow"),
]:
    base.paste(color, box)
report = {}
for orientation in range(1, 9):
    path = a.output / f"exif-{orientation}.jpg"
    exif = Image.Exif()
    exif[274] = orientation
    exif[315] = "PRIVATE TEST MARKER"
    base.save(path, quality=100, subsampling=0, exif=exif)
    out = a.output / path.stem
    subprocess.run(
        [a.executable, str(path), str(out)], check=True, stdout=subprocess.DEVNULL
    )
    expected = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    # Compare corner identities inside the centered Fit image (not the white margins).
    actual = Image.open(out / "Fit-100.png").convert("RGB")
    scale = min(768 / expected.width, 1152 / expected.height)
    left, top = (768 - expected.width * scale) / 2, (1152 - expected.height * scale) / 2
    for fx, fy in [(0.2, 0.2), (0.8, 0.2), (0.2, 0.8), (0.8, 0.8)]:
        src = expected.getpixel((int(expected.width * fx), int(expected.height * fy)))
        dst = actual.getpixel(
            (
                int(left + expected.width * scale * fx),
                int(top + expected.height * scale * fy),
            )
        )
        assert max(abs(x - y) for x, y in zip(src, dst)) < 8, (orientation, src, dst)
    for q in [90, 95, 100]:
        jpeg = Image.open(out / f"Preserve edges-{q}.jpg")
        assert jpeg.size == (768, 1152) and not jpeg.getexif().get(315)
        assert jpeg.getexif().get_ifd(34665).get(40961) == 1
        report[f"quality-{q}"] = {
            "sampling": JpegImagePlugin.get_sampling(jpeg),
            "bytes": (out / f"Preserve edges-{q}.jpg").stat().st_size,
        }
alpha = Image.new("RGBA", (768, 1152), (255, 0, 0, 0))
path = a.output / "transparent.png"
alpha.save(path)
subprocess.run(
    [a.executable, str(path), str(a.output / "alpha")],
    check=True,
    stdout=subprocess.DEVNULL,
)
assert Image.open(a.output / "alpha" / "Borderless-100.png").convert("RGB").getpixel(
    (384, 576)
) == (255, 255, 255)
report["exif_orientations"] = "all eight passed corner checks"
report["transparency"] = "transparent pixels composited white"
profile = Path("/System/Library/ColorSync/Profiles/Display P3.icc")
if profile.exists():
    p3 = Image.new("RGB", (768, 1152), (180, 100, 80))
    path = a.output / "p3.png"
    p3.save(path, icc_profile=profile.read_bytes())
    subprocess.run(
        [a.executable, str(path), str(a.output / "p3")],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    expected = ImageCms.profileToProfile(
        p3, str(profile), ImageCms.createProfile("sRGB"), renderingIntent=1
    ).getpixel((384, 576))
    actual = (
        Image.open(a.output / "p3" / "Borderless-100.png")
        .convert("RGB")
        .getpixel((384, 576))
    )
    assert max(abs(x - y) for x, y in zip(expected, actual)) <= 3, (expected, actual)
    report["p3_conversion"] = {"littlecms": expected, "apple": actual}

if a.android:
    comparisons = {}
    for dimensions in ["96x144", "768x1152", "1200x1200", "1600x900"]:
        stem = f"file-matrix-{dimensions}-plain"
        path = a.android / f"{stem}-input.png"
        if not path.exists():
            continue
        out = a.output / stem
        subprocess.run(
            [a.executable, str(path), str(out)], check=True, stdout=subprocess.DEVNULL
        )
        source = Image.open(path).convert("RGB")
        scale = max(768 / source.width, 1152 / source.height)
        python = source.transform(
            (768, 1152),
            Image.Transform.AFFINE,
            (
                1 / scale,
                0,
                (source.width - 768 / scale) / 2,
                0,
                1 / scale,
                (source.height - 1152 / scale) / 2,
            ),
            Image.Resampling.BILINEAR,
        )
        apple = Image.open(out / "Borderless-100.png").convert("RGB")
        android = Image.open(a.android / f"{stem}-output.png").convert("RGB")
        comparisons[dimensions] = {}
        for name, reference in [("python", python), ("android", android)]:
            diff = ImageChops.difference(apple, reference)
            comparisons[dimensions][name] = {
                "mean_absolute_rgb": ImageStat.Stat(diff).mean,
                "max_channel_difference": max(v[1] for v in diff.getextrema()),
            }
    report["raster_comparisons"] = comparisons
(a.output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
