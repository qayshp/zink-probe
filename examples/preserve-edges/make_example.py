"""Build a synthetic portrait and offline safe-area comparison; no private data."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from zink_probe.images import PreparationOptions, prepare_comparison, safe_area_preview
from zink_probe.prepare_cli import write_bundle


def main():
    root = Path(__file__).resolve().parent
    source = Image.new("RGB", (768, 1152), "#143347")
    draw = ImageDraw.Draw(source)
    title = ImageFont.load_default(size=46)
    text = ImageFont.load_default(size=26)
    small = ImageFont.load_default(size=20)
    draw.rectangle((0, 0, 767, 1151), outline="#f4bd54", width=12)
    for box, label, pos in [
        ((12, 12, 104, 78), "01", (58, 26)),
        ((663, 12, 755, 78), "02", (709, 26)),
        ((12, 1073, 104, 1139), "03", (58, 1087)),
        ((663, 1073, 755, 1139), "04", (709, 1087)),
    ]:
        draw.rectangle(box, fill="#f4bd54")
        draw.text(pos, label, font=text, fill="#143347", anchor="mt")
    draw.text((384, 118), "KEEP THE EDGES", font=title, fill="white", anchor="mt")
    draw.text(
        (384, 180),
        "One portrait. Three placement choices.",
        font=text,
        fill="#c7dee2",
        anchor="mt",
    )
    for y in range(270, 850, 58):
        draw.line((70, y, 698, y), fill="#244b60", width=2)
    for x in range(94, 700, 58):
        draw.line((x, 250, x, 850), fill="#244b60", width=2)
    draw.ellipse((142, 332, 626, 816), fill="#46a6ad")
    draw.ellipse((210, 400, 558, 748), fill="#f4bd54")
    draw.ellipse((278, 468, 490, 680), fill="#ed7d5b")
    draw.line((82, 574, 686, 574), fill="white", width=3)
    draw.line((384, 270, 384, 878), fill="white", width=3)
    draw.text(
        (384, 928),
        "Look for all four corner numbers",
        font=text,
        fill="white",
        anchor="mt",
    )
    draw.text(
        (384, 978),
        "768 x 1152 synthetic source",
        font=small,
        fill="#c7dee2",
        anchor="mt",
    )
    source.save(root / "source.png")
    options = PreparationOptions("preserve-edges", 100, "4:4:4")
    results = prepare_comparison(root / "source.png", options)
    write_bundle(root / "prepared", results, options)
    comparison = Image.new("RGB", (1232, 748), "#f0f2f5")
    draw = ImageDraw.Draw(comparison)
    draw.text(
        (20, 14),
        "SAME PHOTO / SUGGESTED SAFE-AREA GUIDES ON",
        font=text,
        fill="#17202d",
    )
    for x, mode, label, caption in [
        (20, "fill", "Borderless fill", "Full canvas; edges remain exposed"),
        (424, "fit", "Fit", "Same result for this 2:3 source"),
        (828, "preserve-edges", "Preserve edges", "Whole image inset on white"),
    ]:
        import io

        draw.text((x, 64), label, font=text, fill="#17202d")
        with Image.open(io.BytesIO(safe_area_preview(results[mode]))) as guide:
            comparison.paste(
                guide.resize((384, 576), Image.Resampling.LANCZOS), (x, 105)
            )
        draw.text((x, 690), caption, font=small, fill="#17202d")
    draw.text(
        (20, 725),
        "Violet = preview-only 48px guide; not an exact cut line. No printer was contacted.",
        font=small,
        fill="#6033a7",
    )
    comparison.save(root / "comparison.png")


if __name__ == "__main__":
    main()
