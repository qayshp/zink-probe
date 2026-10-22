"""Generate a deterministic offline calibration sheet in input-pixel coordinates."""

import hashlib
import importlib.util
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "prepare", ROOT.parent / "python-render/prepare.py"
)
prep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prep)


def build():
    out = ROOT / "package"
    out.mkdir(exist_ok=True)
    im = Image.new("RGB", (768, 1152), "white")
    d = ImageDraw.Draw(im)
    font = ImageFont.load_default(size=14)
    title = ImageFont.load_default(size=22)

    def label(x, y, text):
        d.text((x, y), text, fill="black", font=font)

    # Alternating edge rulers locate cropping without relying on a single border.
    for x in range(0, 768, 8):
        d.line((x, 0, x, 10 if x % 32 else 18), fill="black")
        d.line((x, 1151, x, 1141 if x % 32 else 1133), fill="black")
    for y in range(0, 1152, 8):
        d.line((0, y, 10 if y % 32 else 18, y), fill="black")
        d.line((767, y, 757 if y % 32 else 749, y), fill="black")
    d.rectangle((48, 48, 720, 1104), outline="black", width=1)
    points = [(48, 48), (720, 48), (48, 1104), (720, 1104), (384, 576)]
    for x, y in points:
        d.line((x - 8, y, x + 8, y), fill="black")
        d.line((x, y - 8, x, y + 8), fill="black")
    d.text((72, 66), "SELECT CAL-01 | 768 x 1152", fill="black", font=title)
    label(72, 96, "TOP  |  input pixels, not hardware dots  |  PhotoFix OFF")
    label(72, 122, "Reference centers: x=48 / 720; y=48 / 1104")
    label(72, 146, "Spans: 672 px across; 1056 px down. Edge ticks: 8 px.")
    patches = []
    for row, orient in enumerate(("vertical", "horizontal")):
        y = 212 + row * 156
        label(
            72, y - 24, f"{orient.upper()} lines: black/white run width in input pixels"
        )
        for col, run in enumerate((1, 2, 3, 4, 6, 8)):
            x = 72 + col * 104
            label(x, y + 100, f"{run}px / shift 1")
            for band in range(2):
                box = [x, y + band * 48, x + 88, y + band * 48 + 40]
                for yy in range(box[1], box[3]):
                    for xx in range(box[0], box[2]):
                        pos = (xx - x if orient == "vertical" else yy - box[1]) + band
                        im.putpixel(
                            (xx, yy),
                            (0, 0, 0) if (pos // run) % 2 == 0 else (255, 255, 255),
                        )
                patches.append(
                    {
                        "kind": "lines",
                        "orientation": orient,
                        "run_px": run,
                        "phase_px": band,
                        "box_exclusive": box,
                    }
                )
    label(72, 538, "CENTER CROSS (384,576); isolated marks and edge spread")
    for i, size in enumerate((1, 2, 3, 4, 6, 8)):
        x = 80 + i * 45
        d.rectangle((x, 578, x + size - 1, 578 + size - 1), fill="black")
        label(x, 606, str(size))
    d.rectangle((440, 566, 528, 630), fill="black")
    d.polygon([(564, 630), (620, 566), (680, 630)], fill="black")
    label(72, 662, "Neutral steps: 0  32  64  96  128  160  192  224  255")
    for i, v in enumerate((0, 32, 64, 96, 128, 160, 192, 224, 255)):
        d.rectangle((72 + i * 68, 688, 72 + i * 68 + 59, 748), fill=(v, v, v))
    label(72, 774, "Color controls: R G B C M Y; geometry chart, not color profiling")
    for i, c in enumerate(
        (
            (255, 0, 0),
            (0, 255, 0),
            (0, 0, 255),
            (0, 255, 255),
            (255, 0, 255),
            (255, 255, 0),
        )
    ):
        d.rectangle((72 + i * 104, 800, 72 + i * 104 + 87, 850), fill=c)
    label(72, 882, "Read separately: source -> prepared JPEG -> measured paper")
    label(72, 908, "Keep all auto-fit, enhancement and border choices recorded.")
    label(
        72, 934, "One future sheet: geometry first; fine-detail claims are conditional."
    )
    label(72, 960, "Feed direction is to be observed, not assumed from this TOP label.")
    label(72, 1016, "CAL-01  |  measure cross centers, not the outside of thick marks")
    label(72, 1042, "No DPI metadata. Actual paper dimensions must be measured.")
    source = out / "source.png"
    im.save(source)
    rendered = prep.prepare(im)
    rendered.save(out / "python.png")
    (out / "python.jpg").write_bytes(prep.jpeg_bytes(rendered))
    manifest = {
        "chart_id": "SELECT-CAL-01",
        "dimensions": [768, 1152],
        "coordinate_system": "pixel centers; origin top left; boxes exclusive",
        "reference_centers": points,
        "reference_spans_px": {"x": 672, "y": 1056},
        "line_patches": patches,
        "sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (source, out / "python.png", out / "python.jpg")
        },
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest["sha256"], indent=2))


if __name__ == "__main__":
    build()
