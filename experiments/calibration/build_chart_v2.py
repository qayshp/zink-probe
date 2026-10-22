"""SELECT-CAL-02: deterministic one-sheet geometry, tone, and detail experiment."""

import hashlib
import importlib.util
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "package-v2"
spec = importlib.util.spec_from_file_location(
    "prepare", ROOT.parent / "python-render/prepare.py"
)
prep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prep)


def build():
    OUT.mkdir(exist_ok=True)
    im = Image.new("RGB", (768, 1152), "white")
    d = ImageDraw.Draw(im)
    f = ImageFont.load_default(size=14)
    title = ImageFont.load_default(size=22)

    def text(x, y, s):
        d.text((x, y), s, font=f, fill="black")

    # Coded, inward-facing crop gauges: each stripe's offset is known exactly.
    gauges = []
    for edge in ["top", "bottom", "left", "right"]:
        for i, depth in enumerate([2, 4, 8, 12, 16, 24, 32]):
            pos = 260 + i * 32
            if edge in ("top", "bottom"):
                yy = depth if edge == "top" else 1151 - depth
                box = (pos, yy, pos + 23, yy)
            else:
                xx = depth if edge == "left" else 767 - depth
                box = (xx, pos, xx, pos + 23)
            d.line(box, fill="black", width=1)
            gauges.append({"edge": edge, "depth_px": depth, "line": box})
    for x in range(0, 768, 16):
        d.line((x, 0, x, 7), fill="black")
        d.line((x, 1151, x, 1144), fill="black")
    for y in range(0, 1152, 16):
        d.line((0, y, 7, y), fill="black")
        d.line((767, y, 760, y), fill="black")
    points = [(48, 48), (720, 48), (48, 1104), (720, 1104), (384, 576)]
    d.rectangle((48, 48, 720, 1104), outline=(160, 160, 160))
    for x, y in points:
        d.line((x - 8, y, x + 8, y), fill="black")
        d.line((x, y - 8, x, y + 8), fill="black")
    text(54, 30, "A")
    text(704, 30, "B")
    text(54, 1110, "C")
    text(704, 1110, "D")
    d.text((72, 65), "SELECT CAL-02  |  TOP", fill="black", font=title)
    text(72, 94, "768 x 1152 | PhotoFix OFF | spans 672 x 1056 input px")
    patches = []

    def patch(name, box, kind, **extra):
        patches.append(
            {"name": name, "box_exclusive": list(box), "kind": kind, **extra}
        )

    # Same three inputs repeated at widely separated feed positions.
    for tag, y in [("A", 140), ("B", 510), ("C", 978)]:
        text(72, y - 20, f"REPEAT {tag}: gray 128 / 3px lines / gray edge")
        d.rectangle((72, y, 231, y + 47), fill=(128, 128, 128))
        patch("repeat-gray-" + tag, (72, y, 232, y + 48), "repeat", group="gray")
        for x in range(292, 452):
            d.line(
                (x, y, x, y + 47),
                fill="black" if ((x - 292) // 3) % 2 == 0 else "white",
            )
        patch("repeat-lines-" + tag, (292, y, 452, y + 48), "repeat", group="lines")
        d.rectangle((512, y, 591, y + 47), fill=(64, 64, 64))
        d.rectangle((592, y, 671, y + 47), fill=(192, 192, 192))
        patch("repeat-edge-" + tag, (512, y, 672, y + 48), "repeat", group="edge")
    # A long gray strip can reveal spatial streaks/bands (not uniquely their cause).
    d.rectangle((690, 130, 703, 1030), fill=(128, 128, 128))
    patch("gray-strip", (690, 130, 704, 1031), "uniform")
    for orient, y in [("vertical", 232), ("horizontal", 362)]:
        text(
            72, y - 24, orient.upper() + " black/white lines: run width in input pixels"
        )
        for col, run in enumerate([1, 2, 3, 4, 6, 8]):
            x = 72 + col * 102
            a = np.zeros((80, 80, 3), dtype=np.uint8)
            for yy in range(80):
                for xx in range(80):
                    a[yy, xx] = (
                        255 if ((xx if orient == "vertical" else yy) // run) % 2 else 0
                    )
            im.paste(Image.fromarray(a), (x, y))
            text(x, y + 83, f"{run}px")
            patch(
                f"{orient}-{run}",
                (x, y, x + 80, y + 80),
                "lines",
                orientation=orient,
                run_px=run,
            )
    # Precisely generated antialiased slanted edges: coverage averaged at 8x.
    text(72, 600, "SLANTED EDGES: black/white and 64/192; both axes")
    for i, (orient, lo, hi) in enumerate(
        [
            ("vertical", 0, 255),
            ("horizontal", 0, 255),
            ("vertical", 64, 192),
            ("horizontal", 64, 192),
        ]
    ):
        x = 72 + i * 153
        y = 624
        w = 132
        h = 96
        n = 8
        yy, xx = np.mgrid[: h * n, : w * n]
        xx = (xx + 0.5) / n
        yy = (yy + 0.5) / n
        mask = (
            xx >= w / 2 + 0.1 * (yy - h / 2)
            if orient == "vertical"
            else yy >= h / 2 + 0.1 * (xx - w / 2)
        )
        a = (
            (lo + (hi - lo) * mask)
            .reshape(h, n, w, n)
            .mean(axis=(1, 3))
            .round()
            .astype("uint8")
        )
        im.paste(Image.fromarray(a).convert("RGB"), (x, y))
        patch(
            f"edge-{i}",
            (x, y, x + w, y + h),
            "slanted-edge",
            orientation=orient,
            levels=[lo, hi],
            slope=0.1,
            coverage_supersampling=n,
        )
    text(72, 740, "SINE SWEEPS H/V | checker 2px | colored edges C/M/Y")
    for orient, x in [("vertical", 72), ("horizontal", 226)]:
        w = 140
        h = 80
        yy, xx = np.mgrid[:h, :w]
        pos = xx if orient == "vertical" else yy
        length = w if orient == "vertical" else h
        phase = (
            2 * math.pi * (0.025 * pos + (0.45 - 0.025) * pos**2 / (2 * (length - 1)))
        )
        a = np.rint(128 + 96 * np.sin(phase)).astype("uint8")
        im.paste(Image.fromarray(a).convert("RGB"), (x, 764))
        patch(
            "sweep-" + orient,
            (x, 764, x + w, 844),
            "sine-sweep",
            orientation=orient,
            start_cycles_per_pixel=0.025,
            end_cycles_per_pixel=0.45,
        )
    yy, xx = np.mgrid[:80, :80]
    a = (((xx // 2 + yy // 2) % 2) * 255).astype("uint8")
    im.paste(Image.fromarray(a).convert("RGB"), (382, 764))
    patch("checker", (382, 764, 462, 844), "checker", run_px=2)
    for i, c in enumerate([(0, 255, 255), (255, 0, 255), (255, 255, 0)]):
        x = 486 + i * 64
        d.rectangle((x, 764, x + 24, 843), fill=c)
        d.line((x + 38, 764, x + 38, 843), fill=c, width=2)
        patch(f"color-edge-{i}", (x, 764, x + 48, 844), "color-edge", rgb=c)
    text(72, 860, "TONE: continuous ramp / dark steps / light steps")
    a = np.tile(np.rint(np.linspace(0, 255, 600)).astype("uint8"), (24, 1))
    im.paste(Image.fromarray(a).convert("RGB"), (72, 882))
    patch("ramp", (72, 882, 672, 906), "ramp")
    for side, values in enumerate(
        [[0, 4, 8, 12, 16, 24, 32, 48], [207, 223, 231, 239, 243, 247, 251, 255]]
    ):
        for i, v in enumerate(values):
            x = 72 + side * 312 + i * 36
            d.rectangle((x, 918, x + 31, 941), fill=(v, v, v))
            patch(f"tone-{v}", (x, 918, x + 32, 942), "tone", value=v)
    text(72, 1048, "A/B/C repeats are identical source pixels; compare decoded JPEG.")
    text(72, 1070, "Crop depths: 2,4,8,12,16,24,32px | full legend in repository")
    for x in [80, 152, 224, 296, 472, 544, 616, 688]:
        # Additional local geometry marks above/below panels, away from center cross.
        d.line((x, 580, x, 588), fill="black")
    im.save(OUT / "source.png")
    render = prep.prepare(im)
    render.save(OUT / "python.png")
    (OUT / "python.jpg").write_bytes(prep.jpeg_bytes(render))
    m = {
        "chart_id": "SELECT-CAL-02",
        "dimensions": [768, 1152],
        "reference_centers": points,
        "reference_spans_px": {"x": 672, "y": 1056},
        "crop_gauges": gauges,
        "patches": patches,
        "sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [OUT / "source.png", OUT / "python.png", OUT / "python.jpg"]
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(m, indent=2) + "\n")
    print(json.dumps(m["sha256"], indent=2))


if __name__ == "__main__":
    build()
