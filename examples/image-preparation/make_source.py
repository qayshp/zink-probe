"""Rebuild the synthetic public fit/fill example; no private photo or font."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def main():
    image = Image.new("RGB", (900, 600), "#f3f1eb")
    draw = ImageDraw.Draw(image)
    large = ImageFont.load_default(size=36)
    small = ImageFont.load_default(size=22)
    draw.text((40, 28), "ONE SOURCE / TWO WAYS TO FRAME IT", font=large, fill="#142c42")
    for start, end, color, label in (
        (40, 250, "#276f8e", "LEFT EDGE"),
        (260, 640, "#cd6b36", "CENTER"),
        (650, 860, "#397b65", "RIGHT EDGE"),
    ):
        draw.rounded_rectangle((start, 100, end, 490), radius=18, fill=color)
        draw.text(
            ((start + end) / 2, 130), label, anchor="mt", font=small, fill="white"
        )
        center = (start + end) / 2
        draw.ellipse((center - 62, 220, center + 62, 344), outline="white", width=5)
        draw.line((center - 82, 282, center + 82, 282), fill="white", width=2)
        draw.line((center, 200, center, 364), fill="white", width=2)
    draw.text(
        (40, 530),
        "900 x 600 source | Fit keeps the edges; fill crops the sides.",
        font=small,
        fill="#142c42",
    )
    image.save(Path(__file__).with_name("source.png"))


if __name__ == "__main__":
    main()
