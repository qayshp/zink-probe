#!/usr/bin/env python3
"""Compare local CAL-03 JPEG variants and execute firmware header handling only.

Writes local research files, never transmits a print. Existing CAL-03 and the
production image-preparation defaults are unchanged. Requires Pillow, NumPy,
Unicorn, and the exact locally acquired FS2105 firmware package.
"""

import argparse
import io
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from PIL import __version__ as pillow_version

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "firmware"))
from inspect_rbn import sha256
from trace_jpeg import JpegHeaders
from trace_lut import MAIN_SHA, RBN_SHA

ROOT = Path(__file__).resolve().parents[2]
CAL = ROOT / "experiments/calibration/package-v3"


def encode(image, quality, sampling, optimize=True, progressive=False, **kwargs):
    stream = io.BytesIO()
    image.save(
        stream,
        "JPEG",
        quality=quality,
        subsampling=sampling,
        optimize=optimize,
        progressive=progressive,
        **kwargs,
    )
    return stream.getvalue()


def sof_offset(data):
    """Locate an actual SOF before SOS, without scanning entropy bytes."""
    if data[:2] != b"\xff\xd8":
        raise ValueError("not JPEG")
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 255:
            raise ValueError("invalid marker boundary")
        marker = data[pos + 1]
        size = int.from_bytes(data[pos + 2 : pos + 4], "big")
        if size < 2 or pos + 2 + size > len(data):
            raise ValueError("invalid segment size")
        if marker in (0xC0, 0xC1, 0xC2):
            return pos
        if marker == 0xDA:
            break
        pos += 2 + size
    raise ValueError("no SOF")


def mutate_header(data, relative_offset, value):
    result = bytearray(data)
    result[sof_offset(data) + relative_offset] = value
    return bytes(result)


def metrics(source, payload, patches):
    decoded = np.asarray(Image.open(io.BytesIO(payload)).convert("RGB"), dtype=np.int16)
    error = decoded - source
    mse = float(np.mean(error.astype(float) ** 2))
    lines = {}
    for patch in patches:
        if patch["kind"] != "lines" or not patch["name"].startswith("r1-"):
            continue
        channel = {"K": 0, "G128": 0, "C": 0, "M": 1, "Y": 2}[patch["color"]]
        x0, y0, x1, y1 = patch["box_exclusive"]
        block = decoded[y0 + 8 : y1 - 8, x0 + 8 : x1 - 8, channel]
        profile = block.mean(axis=0 if patch["orientation"] == "vertical" else 1)
        lines[patch["name"]] = round(
            float((profile.max() - profile.min()) / (255 - patch["rgb"][channel])), 6
        )
    return {
        "rgb_mae": round(float(np.abs(error).mean()), 6),
        "rgb_max_error": int(np.abs(error).max()),
        "rgb_psnr_db": round(float(10 * np.log10(255**2 / mse)), 6) if mse else None,
        "one_pixel_requested_channel_modulation": lines,
    }


def compare(rbn, output):
    output.mkdir(parents=True, exist_ok=True)
    arm = JpegHeaders(rbn)
    image = Image.open(CAL / "python.png").convert("RGB")
    source = np.asarray(image, dtype=np.int16)
    manifest = json.loads((CAL / "manifest.json").read_text())
    variants, header_cases, decoded_by_key = {}, {}, {}

    def inspect(name, data):
        result = arm.parse(data)
        # Compare firmware's natural-order quantization arrays against Pillow's
        # independent header reader. No firmware pixel decoder is invoked.
        if result["status"] == 0:
            tables = Image.open(io.BytesIO(data)).quantization
            checks = [
                list(arm.uc.mem_read(0x4047A8 + 0x56C + 64 * i, 64)) == values
                for i, values in tables.items()
            ]
            if not all(checks):
                raise AssertionError((name, "quantization table differs"))
            result["quantization_matches_host_header"] = True
        header_cases[name] = result
        return result

    for quality in (90, 95, 100):
        for sampling, label, mode in ((2, "420", 0), (1, "422", 2), (0, "444", 1)):
            for optimize in (False, True):
                name = f"q{quality}-{label}-" + (
                    "optimized" if optimize else "standard"
                )
                payload = encode(image, quality, sampling, optimize)
                result = inspect(name, payload)
                assert result["status"] == 0 and result["sampling_mode"] == mode
                assert not result["synthetic_stream_eof"]
                decoded = Image.open(io.BytesIO(payload)).tobytes()
                key = (quality, sampling)
                if optimize:
                    assert decoded == decoded_by_key[key]
                else:
                    decoded_by_key[key] = decoded
                variants[name] = {
                    "bytes": len(payload),
                    "sha256": sha256(payload),
                    "quality": quality,
                    "sampling": label,
                    "optimize": optimize,
                    **metrics(source, payload, manifest["patches"]),
                }
                (output / f"{name}.jpg").write_bytes(payload)
    baseline = (output / "q90-420-optimized.jpg").read_bytes()
    assert baseline == (CAL / "python.jpg").read_bytes()
    for name, path in (
        ("existing-cal03-android", CAL / "android.jpg"),
        ("printed-cal02-python", CAL.parent / "package-v2/python.jpg"),
    ):
        result = inspect(name, path.read_bytes())
        assert result["status"] == 0 and result["sampling_mode"] == 0
    for sub in (0, 1, 2):
        payload = encode(image, 95, sub, progressive=True)
        result = inspect(f"progressive-q95-sub{sub}", payload)
        assert result["status"] == 0 and result["progressive_recognized"]
        assert not result["sampling_setup_executed"]
        disabled = arm.parse(payload, progressive_enabled=False)
        header_cases[f"progressive-disabled-sub{sub}"] = disabled
        assert disabled["status"] == 0x103 and disabled["error_flags_hex"] == "0x10000"
    for name, im, fmt in (
        ("gray-jpeg", image.convert("L"), "JPEG"),
        ("cmyk-jpeg", image.convert("CMYK"), "JPEG"),
        ("png", image, "PNG"),
        ("bmp", image, "BMP"),
    ):
        stream = io.BytesIO()
        im.save(stream, fmt)
        data = stream.getvalue()
        if len(data) > 0x100000:
            # A small valid BMP is sufficient for the SOI discriminator.
            stream = io.BytesIO()
            im.resize((32, 32)).save(stream, fmt)
            data = stream.getvalue()
        result = inspect(name, data)
        assert (result["status"] == 0) == (name == "gray-jpeg")
    # Header mutations are parser-boundary fixtures, not valid alternate files
    # for full decoding. In particular, the entropy data is NOT rewritten.
    mutations = {
        "header-only-sof1-8bit": (1, 0xC1),
        "header-only-sof3-lossless": (1, 0xC3),
        "header-only-sof9-arithmetic": (1, 0xC9),
        "header-only-12bit": (4, 12),
        "header-only-vertical422": (11, 0x12),
    }
    for name, (offset, value) in mutations.items():
        # Vertical 4:2:2 starts with horizontal 4:2:2, maintaining four MCU blocks.
        base = (
            (output / "q90-422-optimized.jpg").read_bytes()
            if "vertical" in name
            else baseline
        )
        data = mutate_header(base, offset, value)
        result = inspect(name, data)
        accepted = name in ("header-only-sof1-8bit", "header-only-vertical422")
        assert (result["status"] == 0) == accepted
        if "vertical" in name:
            assert result["sampling_mode"] == 3
    return {
        "firmware_sha256": RBN_SHA,
        "main_sha256": MAIN_SHA,
        "source_sha256": sha256((CAL / "python.png").read_bytes()),
        "source": "Unchanged SELECT-CAL-03 prepared RGB bitmap, 768 x 1152",
        "pillow_version": pillow_version,
        "numpy_version": np.__version__,
        "unicorn_version": __import__("unicorn").__version__,
        "scope": "Host-decoded image metrics; actual firmware header parser and baseline sampling setup only; no firmware entropy decoding or physical printing",
        "baseline_byte_exact": True,
        "optimized_vs_standard_pixels_equal": True,
        "variants": variants,
        "header_cases": header_cases,
    }


def plot(result, output):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = ("q90-420-optimized", "q100-420-optimized", "q95-444-optimized")
    labels = ("Quality 90 / 4:2:0", "Quality 100 / 4:2:0", "Quality 95 / 4:4:4")
    colors = ("#64748b", "#d97706", "#2563eb")
    fig, ax = plt.subplots(figsize=(9, 4.8), layout="constrained")
    for i, (name, label, color) in enumerate(zip(names, labels, colors)):
        values = [
            100
            * result["variants"][name]["one_pixel_requested_channel_modulation"][
                f"r1-{c}-vertical"
            ]
            for c in ("C", "M", "Y")
        ]
        bars = ax.bar(
            np.arange(3) + (i - 1) * 0.25, values, width=0.23, label=label, color=color
        )
        ax.bar_label(bars, fmt="%.1f%%", fontsize=9, padding=3)
    ax.set_xticks(
        np.arange(3), ("Requested cyan", "Requested magenta", "Requested yellow")
    )
    ax.set_ylim(0, 118)
    ax.set_ylabel("Retained RGB-channel range (%)")
    ax.set_title(
        "CAL-03 one-pixel vertical stripes after JPEG encoding\nHost decode only — no physical print",
        pad=14,
    )
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncols=3, frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_axisbelow(True)
    ax.grid(axis="y", alpha=0.2)
    fig.savefig(output, dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rbn", type=Path)
    parser.add_argument(
        "--output", type=Path, required=True, help="Local directory for research JPEGs"
    )
    parser.add_argument(
        "--plot",
        type=Path,
        help="Optional local plot of measured host-decode differences",
    )
    args = parser.parse_args()
    result = compare(args.rbn.read_bytes(), args.output)
    if args.plot:
        plot(result, args.plot)
    print(json.dumps(result, indent=2))
