"""Offline Select image preparation; optional Pillow dependency, no transport.

File inputs are single-frame JPEG/PNG. In-memory Pillow images are also accepted.
Output is always an opaque sRGB 768x1152 baseline JPEG, independently decoded
before return. No PhotoFix, printer color LUT, thermal correction, or DPI claim.
"""

from __future__ import annotations

import hashlib
import io
import math
import platform
import warnings
from dataclasses import dataclass
from pathlib import Path

import PIL
from PIL import Image, ImageCms, ImageFile, ImageOps, JpegImagePlugin, features
from PIL.PngImagePlugin import PngInfo

SIZE = (768, 1152)
MAX_PIXELS = 64_000_000
MAX_INPUT_BYTES = 100 * 1024 * 1024
MAX_PROFILE_BYTES = 4 * 1024 * 1024
SAMPLING = {"4:2:0": 2, "4:2:2": 1, "4:4:4": 0}


class PreparationError(ValueError):
    """The source or requested preparation cannot be handled without guessing."""


@dataclass(frozen=True)
class PreparationOptions:
    mode: str = "fill"
    quality: int = 90
    subsampling: str = "4:2:0"

    def __post_init__(self):
        if self.mode not in ("fit", "fill"):
            raise PreparationError("Mode must be fit or fill")
        if type(self.quality) is not int or not 1 <= self.quality <= 100:
            raise PreparationError("JPEG quality must be an integer from 1 to 100")
        if self.subsampling not in SAMPLING:
            raise PreparationError("Subsampling must be 4:2:0, 4:2:2, or 4:4:4")


@dataclass(frozen=True)
class PreparedImage:
    jpeg: bytes
    raster_png: bytes
    preview_png: bytes
    manifest: dict


def _clean_rgb(image):
    # Copy pixels only. Do not propagate EXIF, XMP, comments, or a source profile
    # that no longer describes the transformed pixels.
    clean = Image.new("RGB", image.size)
    clean.paste(image)
    return clean


def _size_check(image):
    w, h = image.size
    if w < 1 or h < 1 or w * h > MAX_PIXELS:
        raise PreparationError(f"Input must contain 1..{MAX_PIXELS:,} pixels")


def _untagged_png_check(info):
    if "srgb" in info:
        if info["srgb"] not in (0, 1, 2, 3):
            raise PreparationError("Invalid PNG sRGB rendering intent")
        return
    if "gamma" in info and not math.isclose(info["gamma"], 0.45455, abs_tol=0.00001):
        raise PreparationError("Non-sRGB PNG gamma requires an embedded ICC profile")
    if "chromaticity" in info:
        srgb = (0.3127, 0.3290, 0.64, 0.33, 0.30, 0.60, 0.15, 0.06)
        values = info["chromaticity"]
        if len(values) != 8 or any(
            not math.isclose(a, b, abs_tol=0.00001) for a, b in zip(values, srgb)
        ):
            raise PreparationError("Non-sRGB PNG chromaticities require an ICC profile")


def _normalize(image):
    _size_check(image)
    if getattr(image, "n_frames", 1) != 1:
        raise PreparationError("Animated or multi-frame inputs are unsupported")
    if image.mode not in ("1", "L", "LA", "P", "RGB", "RGBA", "CMYK"):
        raise PreparationError(
            f"Unsupported input mode {image.mode}; export 8-bit sRGB"
        )
    orientation = image.getexif().get(274, 1)
    if type(orientation) is not int or orientation not in range(1, 9):
        raise PreparationError(
            "Invalid EXIF orientation; expected an integer from 1 to 8"
        )
    info = dict(image.info)
    icc = info.get("icc_profile")
    if "icc_profile" in info and (
        not isinstance(icc, bytes) or not 0 < len(icc) <= MAX_PROFILE_BYTES
    ):
        raise PreparationError("Invalid or oversized embedded ICC profile")
    oriented = ImageOps.exif_transpose(image)
    alpha = None
    if oriented.mode in ("RGBA", "LA", "P") or "transparency" in info:
        alpha = oriented.convert("RGBA").getchannel("A")
    if oriented.mode == "CMYK":
        color, expected_space = oriented, "CMYK"
    elif oriented.mode in ("1", "L", "LA"):
        color, expected_space = oriented.convert("L"), "GRAY"
    else:
        color, expected_space = oriented.convert("RGB"), "RGB"
    if icc is not None:
        try:
            profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            if profile.profile.xcolor_space.strip() != expected_space:
                raise PreparationError(
                    "Embedded ICC color space does not match the image mode"
                )
            color = ImageCms.profileToProfile(
                color,
                profile,
                ImageCms.createProfile("sRGB"),
                renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
                outputMode="RGB",
                flags=ImageCms.Flags.BLACKPOINTCOMPENSATION,
            )
        except (ImageCms.PyCMSError, OSError, ValueError) as exc:
            raise PreparationError(
                f"Cannot convert embedded ICC profile to sRGB: {exc}"
            ) from exc
        conversion = "embedded-icc-to-srgb"
    else:
        if expected_space == "CMYK":
            raise PreparationError("CMYK input requires an embedded CMYK ICC profile")
        _untagged_png_check(info)
        color = color.convert("RGB")
        conversion = "png-srgb-tag" if "srgb" in info else "assumed-srgb"
    if alpha is not None:
        rgba = color.convert("RGBA")
        rgba.putalpha(alpha)
        color = Image.alpha_composite(
            Image.new("RGBA", rgba.size, "white"), rgba
        ).convert("RGB")
    return _clean_rgb(color), {
        "input_size": list(image.size),
        "input_mode": image.mode,
        "input_format": image.format,
        "exif_orientation": orientation,
        "orientation_applied": orientation != 1,
        "oriented_size": list(oriented.size),
        "color_conversion": conversion,
        "source_icc_sha256": hashlib.sha256(icc).hexdigest() if icc else None,
        "rendering_intent": "relative-colorimetric-with-black-point-compensation"
        if icc
        else None,
        "alpha_composited": alpha is not None,
        "background_srgb": [255, 255, 255],
        "compositing_space": "encoded-srgb",
    }


def _check_png_headers(data):
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return
    pos = 8
    while pos + 12 <= len(data):
        size = int.from_bytes(data[pos : pos + 4], "big")
        kind = data[pos + 4 : pos + 8]
        end = pos + 12 + size
        if end > len(data):
            raise PreparationError("Truncated PNG chunk")
        # Pillow exposes 16-bit RGB PNGs as RGB after reducing precision.
        if kind == b"IHDR" and size >= 9 and data[pos + 16] == 16:
            raise PreparationError(
                "16-bit PNG inputs are unsupported; export 8-bit sRGB"
            )
        # Pillow 13 does not expose these color/HDR chunks to ImageCms. Refuse
        # to assume sRGB after its loader silently ignores an explicit tag.
        if kind in (b"cICP", b"mDCv", b"cLLi"):
            raise PreparationError(
                "PNG CICP/HDR color metadata is unsupported; export SDR sRGB"
            )
        pos = end
        if kind == b"IEND":
            break


def _load_source(source):
    if ImageFile.LOAD_TRUNCATED_IMAGES:
        raise PreparationError("Pillow truncated-image loading must be disabled")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            if isinstance(source, Image.Image):
                rgb, metadata = _normalize(source)
                metadata["input_sha256"] = None
                return rgb, metadata
            path = Path(source)
            with path.open("rb") as file:
                data = file.read(MAX_INPUT_BYTES + 1)
            if len(data) > MAX_INPUT_BYTES:
                raise PreparationError("Input exceeds the 100 MiB file-size limit")
            _check_png_headers(data)
            # Verify PNG structure/CRC, then reopen for full entropy decoding.
            with Image.open(io.BytesIO(data), formats=("JPEG", "PNG")) as checked:
                _size_check(checked)
                if getattr(checked, "n_frames", 1) != 1:
                    raise PreparationError(
                        "Animated or multi-frame inputs are unsupported"
                    )
                checked.verify()
            with Image.open(io.BytesIO(data), formats=("JPEG", "PNG")) as image:
                image.load()
                rgb, metadata = _normalize(image)
            metadata["input_sha256"] = hashlib.sha256(data).hexdigest()
            return rgb, metadata
    except PreparationError:
        raise
    except (
        OSError,
        ValueError,
        SyntaxError,
        Image.DecompressionBombWarning,
        Image.DecompressionBombError,
    ) as exc:
        raise PreparationError(
            f"Cannot read a supported single-frame JPEG/PNG: {exc}"
        ) from exc


def _png(image):
    output = io.BytesIO()
    tags = PngInfo()
    tags.add(b"sRGB", b"\x01")  # Explicit sRGB; no inherited input ICC/EXIF.
    _clean_rgb(image).save(output, "PNG", pnginfo=tags)
    return output.getvalue()


def _render(source, source_metadata, options):
    w, h = source.size
    scale = (max if options.mode == "fill" else min)(SIZE[0] / w, SIZE[1] / h)
    left, top = (w - SIZE[0] / scale) / 2, (h - SIZE[1] / scale) / 2
    raster = source.transform(
        SIZE,
        Image.Transform.AFFINE,
        (1 / scale, 0, left, 0, 1 / scale, top),
        Image.Resampling.BILINEAR,
        fillcolor="white",
    )
    output = io.BytesIO()
    raster.save(
        output,
        "JPEG",
        quality=options.quality,
        subsampling=SAMPLING[options.subsampling],
        optimize=True,
        progressive=False,
    )
    jpeg = output.getvalue()
    # Full decoding is deliberately upstream of the job engine's header check.
    with Image.open(io.BytesIO(jpeg)) as decoded:
        decoded.load()
        if (
            decoded.size != SIZE
            or decoded.mode != "RGB"
            or decoded.info.get("progressive")
            or decoded.info.get("progression")
            or JpegImagePlugin.get_sampling(decoded) != SAMPLING[options.subsampling]
        ):
            raise PreparationError("Encoded JPEG does not satisfy the Select contract")
        preview = _png(decoded)
        tables_one = all(
            v == 1 for table in decoded.quantization.values() for v in table
        )
    x, y = (SIZE[0] - w * scale) / 2, (SIZE[1] - h * scale) / 2
    manifest = {
        "schema_version": 1,
        "offline": True,
        "profile": "hp-sprocket-select-768x1152",
        "source": source_metadata,
        "geometry": {
            "mode": options.mode,
            "output_size": list(SIZE),
            "scale": scale,
            "upscaled": scale > 1,
            "source_crop_box": [
                max(0.0, left),
                max(0.0, top),
                min(float(w), left + SIZE[0] / scale),
                min(float(h), top + SIZE[1] / scale),
            ],
            "scaled_image_box": [x, y, x + w * scale, y + h * scale],
            "padding_pixels": {
                "left": max(0.0, x),
                "right": max(0.0, x),
                "top": max(0.0, y),
                "bottom": max(0.0, y),
            },
            "resampling": "inverse-affine-bilinear",
        },
        "encoding": {
            "format": "baseline-jpeg",
            "quality": options.quality,
            "subsampling": options.subsampling,
            "optimized_huffman": True,
            "quantization_all_ones": tables_one,
            "bytes": len(jpeg),
            "sha256": hashlib.sha256(jpeg).hexdigest(),
            "color_space": "sRGB",
            "icc_embedded": False,
            "exif_embedded": False,
        },
        "preview": "PNG of fully decoded output JPEG, tagged sRGB",
        "photofix": False,
        "physical_print_validated": False,
        "versions": {
            "python": platform.python_version(),
            "pillow": PIL.__version__,
            "littlecms": features.version("littlecms2"),
            "jpeg": features.version("jpg"),
            "libjpeg_turbo": features.version("libjpeg_turbo"),
        },
    }
    return PreparedImage(jpeg, _png(raster), preview, manifest)


def prepare_image(
    source: str | Path | Image.Image, options: PreparationOptions | None = None
) -> PreparedImage:
    """Normalize a path/Pillow image and prepare one Select image, entirely offline.

    Source objects/files are not modified. `preview_png` shows the decoded JPEG;
    `raster_png` preserves the pixels before lossy compression. No source metadata
    is copied to either artifact. Untagged RGB/grayscale is assumed to be sRGB.
    """
    options = PreparationOptions() if options is None else options
    if not isinstance(options, PreparationOptions):
        raise TypeError("options must be PreparationOptions")
    rgb, metadata = _load_source(source)
    return _render(rgb, metadata, options)


def prepare_comparison(
    source: str | Path | Image.Image, options: PreparationOptions | None = None
) -> dict[str, PreparedImage]:
    """Normalize once and return both fit/fill results with the same JPEG settings."""
    options = PreparationOptions() if options is None else options
    if not isinstance(options, PreparationOptions):
        raise TypeError("options must be PreparationOptions")
    rgb, metadata = _load_source(source)
    return {
        mode: _render(
            rgb,
            metadata,
            PreparationOptions(mode, options.quality, options.subsampling),
        )
        for mode in ("fit", "fill")
    }
