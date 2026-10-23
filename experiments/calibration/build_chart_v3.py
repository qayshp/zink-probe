"""Build SELECT-CAL-03 offline: matched color, spacing and conditioning controls."""

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "package-v3"
spec = importlib.util.spec_from_file_location(
    "prepare", ROOT.parent / "python-render/prepare.py"
)
prep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prep)
COLORS = [
    ("K", (0, 0, 0)),
    ("G128", (128, 128, 128)),
    ("C", (0, 255, 255)),
    ("M", (255, 0, 255)),
    ("Y", (255, 255, 0)),
]


def build():
    OUT.mkdir(exist_ok=True)
    im = Image.new("RGB", (768, 1152), "white")
    d = ImageDraw.Draw(im)
    fonts = {size: ImageFont.load_default(size=size) for size in (11, 12, 14, 20, 28)}
    patches = []

    def text(x, y, value, size=12):
        d.text((x, y), value, fill="black", font=fonts[size])

    def patch(name, box, kind, **extra):
        patches.append(
            {"name": name, "box_exclusive": list(box), "kind": kind, **extra}
        )

    def fill(name, box, rgb, kind, **extra):
        x0, y0, x1, y1 = box
        d.rectangle((x0, y0, x1 - 1, y1 - 1), fill=rgb)
        patch(name, box, kind, rgb=list(rgb), **extra)

    # Important content stays inside the first sheet's measured crop envelope.
    # The frame remains a placement reference, not a printer-resolution claim.
    d.rectangle((48, 48, 720, 1104), outline=(160, 160, 160))
    points = [(48, 48), (720, 48), (48, 1104), (720, 1104)]
    for x, y in points:
        d.line((x - 6, y, x + 6, y), fill="black")
        d.line((x, y - 6, x, y + 6), fill="black")
    fill("end-A-square", (64, 64, 84, 84), (0, 0, 0), "end-marker")
    text(104, 54, "A / ONE", 28)
    text(300, 61, "SELECT CAL-03 | THERMAL", 20)
    text(64, 100, "V = along feed axis | H = across feed axis", 14)
    text(64, 118, "Same geometry in every color; widths and gaps are input pixels", 12)

    def references(y, tag):
        for index, (color, rgb) in enumerate(COLORS):
            x = 64 + 128 * index
            fill(
                f"solid-{tag}-{color}",
                (x, y, x + 32, y + 16),
                rgb,
                "solid-reference",
                color=color,
                repeat_group=f"solid-{color}",
            )
            # Actual white controls have no border, to avoid added local heating.
            fill(
                f"white-{tag}-{color}",
                (x + 40, y, x + 56, y + 16),
                (255, 255, 255),
                "white-reference",
                color=color,
            )
            fill(
                f"isolated-V-{tag}-{color}",
                (x + 78, y - 8, x + 80, y + 24),
                rgb,
                "isolated-line",
                color=color,
                orientation="vertical",
            )
            fill(
                f"isolated-H-{tag}-{color}",
                (x, y + 24, x + 32, y + 26),
                rgb,
                "isolated-line",
                color=color,
                orientation="horizontal",
            )

    for index, (color, _) in enumerate(COLORS):
        text(64 + 128 * index, 136, color, 14)
    references(160, "A")
    for row, (y, run, gap, tag) in enumerate(
        [
            (208, 1, 1, "r1"),
            (272, 2, 2, "r2"),
            (336, 4, 4, "r4"),
            (416, 2, 6, "g6"),
            (480, 2, 14, "g14"),
            (928, 2, 2, "repeat-r2"),
        ]
    ):
        for index, (color, rgb) in enumerate(COLORS):
            x = 64 + 128 * index
            label = f"{run}px: V | H" if gap == run else f"2px/g{gap}: V | H"
            text(x, y - 16, label, 11)
            for orientation, px in [("vertical", x), ("horizontal", x + 64)]:
                yy, xx = np.mgrid[:48, :48]
                coordinate = xx if orientation == "vertical" else yy
                mask = coordinate % (run + gap) < run
                a = np.full((48, 48, 3), 255, dtype=np.uint8)
                a[mask] = rgb
                im.paste(Image.fromarray(a), (px, y))
                patch(
                    f"{tag}-{color}-{orientation}",
                    (px, y, px + 48, y + 48),
                    "lines",
                    color=color,
                    rgb=list(rgb),
                    orientation=orientation,
                    run_px=run,
                    gap_px=gap,
                    expected_cycles=48 / (run + gap),
                    repeat_group=(
                        f"r2-{color}-{orientation}" if row in (1, 5) else None
                    ),
                )
    text(64, 386, "SPACING: same 2px bars, wider white gaps", 12)
    text(
        64, 548, "CONDITIONING: pale target between solid blocks; paired reference", 12
    )
    text(64, 566, "Blocks at BOTH ends; second pair swaps lanes. See legend.", 12)
    # Bracketing works whichever end emerges first. Reference lanes contain the
    # same pale target but white in the positions occupied by colored blocks.
    # It is not an absolute cold control; neighboring/global heat may reach it.
    for gap, target_y, heated_side in [(8, 640, 0), (32, 800, 1)]:
        for index, (color, rgb) in enumerate(COLORS):
            x = 64 + 128 * index
            label_y = 584 if gap == 8 else 720
            text(
                x,
                label_y,
                f"{gap}: " + ("HOT | REF" if heated_side == 0 else "REF | HOT"),
                11,
            )
            target_rgb = tuple((value + 256) // 2 for value in rgb)
            # Keep 255 unchanged while rounding half-white blends to 128/192.
            target_rgb = tuple(min(255, value) for value in target_rgb)
            for side in (0, 1):
                px = x + side * 64
                lane = "heated" if side == heated_side else "reference"
                fill(
                    f"target-g{gap}-{color}-{lane}",
                    (px, target_y, px + 48, target_y + 16),
                    target_rgb,
                    "history-target",
                    color=color,
                    gap_px=gap,
                    lane=lane,
                    repeat_group=f"target-{color}",
                )
                for direction, y0 in [
                    ("A", target_y - gap - 24),
                    ("B", target_y + 16 + gap),
                ]:
                    fill(
                        f"block-g{gap}-{color}-{lane}-{direction}",
                        (px, y0, px + 48, y0 + 24),
                        rgb if lane == "heated" else (255, 255, 255),
                        "conditioning-block",
                        color=color,
                        gap_px=gap,
                        lane=lane,
                        end=direction,
                    )
    text(64, 892, "REPEAT: same 2px V/H patterns and reference colors as above", 12)
    references(1008, "B")
    fill("end-B-square-1", (64, 1064, 84, 1084), (0, 0, 0), "end-marker")
    fill("end-B-square-2", (92, 1064, 112, 1084), (0, 0, 0), "end-marker")
    text(132, 1054, "B / TWO", 28)
    text(324, 1061, "Record which end exits first", 14)
    text(324, 1082, "768 x 1152 | PhotoFix OFF | CAL-03", 11)

    im.save(OUT / "source.png")
    rendered = prep.prepare(im)
    rendered.save(OUT / "python.png")
    (OUT / "python.jpg").write_bytes(prep.jpeg_bytes(rendered))
    manifest = {
        "chart_id": "SELECT-CAL-03",
        "dimensions": [768, 1152],
        "status": "Prepared offline; no physical print performed",
        "photo_fix": False,
        "colors": {name: list(rgb) for name, rgb in COLORS},
        "reference_centers": points,
        "reference_spans_px": {"x": 672, "y": 1056},
        "known_feed_axis": "Along 1152-pixel / long paper axis; leading end unknown",
        "patches": patches,
        "sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [OUT / "source.png", OUT / "python.png", OUT / "python.jpg"]
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"patches": len(patches), "sha256": manifest["sha256"]}, indent=2))


if __name__ == "__main__":
    build()
