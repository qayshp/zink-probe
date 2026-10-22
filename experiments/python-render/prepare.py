"""Offline Select raster preparation. Reads/writes files; has no printer transport."""

from __future__ import annotations

import argparse
import io
from pathlib import Path

from PIL import Image

SIZE = (768, 1152)
JPEG_QUALITY = 90


def opaque_rgb(image: Image.Image) -> Image.Image:
    """Composite transparency over white. Inputs are assumed to be sRGB."""
    rgba = image.convert("RGBA")
    background = Image.new("RGBA", image.size, "white")
    return Image.alpha_composite(background, rgba).convert("RGB")


def prepare(image: Image.Image) -> Image.Image:
    """Center-cover a prepared bitmap; no EXIF rotation, editor, or PhotoFix.

    Affine bilinear sampling is intentional: Pillow's resize() reduction filter
    differs more from the captured Android rasterizer on our synthetic fixtures.
    """
    image = opaque_rgb(image)
    width, height = image.size
    scale = max(SIZE[0] / width, SIZE[1] / height)
    left = (width - SIZE[0] / scale) / 2
    top = (height - SIZE[1] / scale) / 2
    return image.transform(
        SIZE,
        Image.Transform.AFFINE,
        (1 / scale, 0, left, 0, 1 / scale, top),
        Image.Resampling.BILINEAR,
    )


def editor_transform(image: Image.Image, matrix: list[float]) -> Image.Image:
    """Replay a forward Android affine matrix on a fixed, white source-size canvas.

    This replays recorded model state; it does not implement gesture constraints,
    source measurement/EXIF normalization, fit/fill state, or decorative layers.
    """
    if len(matrix) != 9 or matrix[6:] != [0, 0, 1]:
        raise ValueError("Expected a 3x3 affine matrix with bottom row [0, 0, 1]")
    a, b, c, d, e, f = matrix[:6]
    det = a * e - b * d
    if abs(det) < 1e-12:
        raise ValueError("Matrix must be invertible")
    inverse = (
        e / det,
        -b / det,
        (b * f - e * c) / det,
        -d / det,
        a / det,
        (d * c - a * f) / det,
    )
    return opaque_rgb(image).transform(
        image.size,
        Image.Transform.AFFINE,
        inverse,
        Image.Resampling.BILINEAR,
        fillcolor="white",
    )


def jpeg_bytes(image: Image.Image, quality: int = JPEG_QUALITY) -> bytes:
    """Baseline JPEG, 4:2:0. No copied metadata/profile or physical-DPI claim."""
    stream = io.BytesIO()
    opaque_rgb(image).save(
        stream, "JPEG", quality=quality, subsampling=2, optimize=True, progressive=False
    )
    return stream.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Already oriented/edited sRGB image")
    parser.add_argument("output", type=Path, help="Local .jpg/.jpeg or lossless .png")
    args = parser.parse_args()
    if args.output.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
        parser.error("Output must be .jpg, .jpeg, or .png")
    if args.input.resolve() == args.output.resolve():
        parser.error("Input and output must be different files")
    with Image.open(args.input) as source:
        result = prepare(source)
    # Exclusive creation prevents accidentally replacing a source or prior result.
    with args.output.open("xb") as destination:
        if args.output.suffix.lower() == ".png":
            result.save(destination, "PNG")
        else:
            destination.write(jpeg_bytes(result))
    print(f"Saved {SIZE[0]} x {SIZE[1]} locally; PhotoFix omitted; nothing transmitted")


if __name__ == "__main__":
    main()
