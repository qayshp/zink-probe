"""Offline import, rendering, encoding and job-engine integration contracts."""

import asyncio
import hashlib
import importlib.util
import io
import json
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

pytest.importorskip("PIL", reason="install the images extra for preparation tests")
from PIL import Image, ImageCms, ImageFile, JpegImagePlugin
from PIL.PngImagePlugin import PngInfo

from zink_probe import images
from zink_probe.images import (
    PreparationError,
    PreparationOptions,
    prepare_comparison,
    prepare_image,
)
from zink_probe.jobs import FramedSession, JobEngine, JobJournal, JobSpec
from zink_probe.jobs.simulator import DEVICE_ID, SimulatedPrinter
from zink_probe.prepare_cli import main, write_bundle

ROOT = Path(__file__).resolve().parents[1]
LINEAR_PROFILE = (ROOT / "tests/fixtures/images/linear-rgb.icc").read_bytes()


def decoded(data):
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        return image.copy()


@pytest.mark.parametrize(
    "orientation,expected,dimensions",
    [
        (1, [10, 20, 30, 40, 50, 60], (3, 2)),
        (2, [30, 20, 10, 60, 50, 40], (3, 2)),
        (3, [60, 50, 40, 30, 20, 10], (3, 2)),
        (4, [40, 50, 60, 10, 20, 30], (3, 2)),
        (5, [10, 40, 20, 50, 30, 60], (2, 3)),
        (6, [40, 10, 50, 20, 60, 30], (2, 3)),
        (7, [60, 30, 50, 20, 40, 10], (2, 3)),
        (8, [30, 60, 20, 50, 10, 40], (2, 3)),
    ],
)
def test_all_exif_orientations_and_original_preservation(
    tmp_path, orientation, expected, dimensions
):
    source = Image.new("RGB", (3, 2))
    source.putdata([(v, 0, 0) for v in (10, 20, 30, 40, 50, 60)])
    source.getexif()[274] = orientation
    before = source.tobytes(), source.getexif().tobytes()
    path = tmp_path / "oriented.png"
    source.save(path, exif=source.getexif())
    file_before = path.read_bytes()
    for value in (source, path):
        normalized, metadata = images._load_source(value)
        assert normalized.size == dimensions
        assert [pixel[0] for pixel in normalized.get_flattened_data()] == expected
        assert metadata["exif_orientation"] == orientation
        assert metadata["oriented_size"] == list(dimensions)
        assert not normalized.getexif() and not normalized.info
    assert (source.tobytes(), source.getexif().tobytes()) == before
    assert path.read_bytes() == file_before


def test_exif_is_applied_before_crop_and_removed_from_outputs(tmp_path):
    source = Image.new("RGB", (12, 8), "red")
    source.getexif()[274] = 6
    source.getexif()[270] = "Private description"
    path = tmp_path / "oriented.jpg"
    source.save(path, exif=source.getexif())
    result = prepare_image(path)
    assert result.manifest["geometry"]["scale"] == 96
    assert result.manifest["geometry"]["source_crop_box"] == [0, 0, 8, 12]
    for artifact in (result.jpeg, result.raster_png, result.preview_png):
        with Image.open(io.BytesIO(artifact)) as image:
            assert not image.getexif()
            assert "icc_profile" not in image.info
            assert b"Private description" not in artifact


def test_linear_icc_conversion_precedes_alpha_compositing(tmp_path):
    source = Image.new("RGBA", (8, 12), (128, 128, 128, 128))
    path = tmp_path / "linear.png"
    source.save(path, icc_profile=LINEAR_PROFILE)
    result = prepare_image(path)
    # Linear 0.502 -> encoded sRGB about 0.737 (~188), then half white -> ~221.
    pixel = decoded(result.raster_png).getpixel((384, 576))
    assert all(220 <= value <= 223 for value in pixel)
    metadata = result.manifest["source"]
    assert metadata["color_conversion"] == "embedded-icc-to-srgb"
    assert metadata["source_icc_sha256"] == hashlib.sha256(LINEAR_PROFILE).hexdigest()
    assert metadata["alpha_composited"]
    assert metadata["input_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_srgb_profile_keeps_pixels_and_is_not_copied():
    source = Image.new("RGB", (8, 12), (25, 100, 220))
    source.info["icc_profile"] = ImageCms.ImageCmsProfile(
        ImageCms.createProfile("sRGB")
    ).tobytes()
    result = prepare_image(source)
    assert decoded(result.raster_png).getpixel((384, 576)) == (25, 100, 220)
    assert decoded(result.preview_png).info["srgb"] == 1
    assert b"ICC_PROFILE" not in result.jpeg


@pytest.mark.parametrize(
    "mode,value,expected",
    [
        ("L", 80, (80, 80, 80)),
        ("LA", (0, 128), (127, 127, 127)),
        ("RGBA", (0, 100, 200, 0), (255, 255, 255)),
        ("1", 1, (255, 255, 255)),
    ],
)
def test_gray_and_transparency(mode, value, expected):
    result = prepare_image(Image.new(mode, (8, 12), value))
    assert decoded(result.raster_png).getpixel((384, 576)) == expected


def test_palette_transparency():
    source = Image.new("P", (8, 12), 0)
    source.putpalette([255, 0, 0] + [0] * 765)
    source.info["transparency"] = 0
    assert decoded(prepare_image(source).raster_png).getpixel((384, 576)) == (
        255,
        255,
        255,
    )


@pytest.mark.parametrize(
    "kind,match",
    [
        ("bad-profile", "ICC"),
        ("wrong-profile-space", "does not match"),
        ("untagged-cmyk", "CMYK"),
        ("unsupported-mode", "Unsupported"),
        ("bad-orientation", "EXIF orientation"),
        ("bad-gamma", "gamma"),
        ("bad-chromaticities", "chromaticities"),
        ("too-many-pixels", "pixels"),
        ("oversized-profile", "oversized"),
        ("truncated-policy", "truncated"),
    ],
)
def test_reject_ambiguous_input(kind, match, monkeypatch):
    source = Image.new("RGB", (8, 12), "gray")
    if kind == "bad-profile":
        source.info["icc_profile"] = b"invalid"
    elif kind == "wrong-profile-space":
        source = source.convert("L")
        source.info["icc_profile"] = LINEAR_PROFILE
    elif kind == "untagged-cmyk":
        source = source.convert("CMYK")
    elif kind == "unsupported-mode":
        source = Image.new("I;16", (8, 12))
    elif kind == "bad-orientation":
        source.getexif()[274] = 9
    elif kind == "bad-gamma":
        source.info["gamma"] = 1.0
    elif kind == "bad-chromaticities":
        source.info["chromaticity"] = (0,) * 8
    elif kind == "too-many-pixels":
        monkeypatch.setattr(images, "MAX_PIXELS", 95)
    elif kind == "oversized-profile":
        source.info["icc_profile"] = LINEAR_PROFILE
        monkeypatch.setattr(images, "MAX_PROFILE_BYTES", 100)
    elif kind == "truncated-policy":
        monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", True)
    with pytest.raises(PreparationError, match=match):
        prepare_image(source)


def test_file_rejections_before_output(tmp_path, monkeypatch):
    source = Image.new("RGB", (8, 12), "red")
    path = tmp_path / "input.png"
    source.save(path, save_all=True, append_images=[Image.new("RGB", (8, 12), "blue")])
    with pytest.raises(PreparationError, match="multi-frame"):
        prepare_image(path)
    source.save(path, "JPEG")
    path.write_bytes(path.read_bytes()[:-20])
    with pytest.raises(PreparationError):
        prepare_image(path)
    Image.new("I;16", (8, 12)).save(path, "PNG")
    with pytest.raises(PreparationError, match="16-bit"):
        prepare_image(path)
    source.save(path, "PNG")
    monkeypatch.setattr(images, "MAX_INPUT_BYTES", 16)
    with pytest.raises(PreparationError, match="file-size"):
        prepare_image(path)


def test_png_explicit_srgb_and_gamma(tmp_path):
    path = tmp_path / "input.png"
    tags = PngInfo()
    tags.add(b"gAMA", struct.pack(">I", 100000))
    Image.new("RGB", (8, 12)).save(path, pnginfo=tags)
    with pytest.raises(PreparationError, match="gamma"):
        prepare_image(path)
    tags = PngInfo()
    tags.add(b"sRGB", b"\x01")
    Image.new("RGB", (8, 12)).save(path, pnginfo=tags)
    assert prepare_image(path).manifest["source"]["color_conversion"] == "png-srgb-tag"


@pytest.mark.parametrize(
    "chunk,data,match",
    [
        (b"iCCP", b"broken\0\0bad-zlib", "ICC"),
        (b"sRGB", b"\x05", "rendering intent"),
        (b"cICP", bytes((9, 16, 0, 1)), "CICP/HDR"),
    ],
)
def test_explicit_color_metadata_cannot_silently_become_untagged(
    tmp_path, chunk, data, match
):
    path = tmp_path / "color.png"
    Image.new("RGB", (8, 12)).save(path)
    original = path.read_bytes()
    # Insert after IHDR; Pillow's writer deliberately filters malformed iCCP.
    record = (
        struct.pack(">I", len(data))
        + chunk
        + data
        + struct.pack(">I", zlib.crc32(chunk + data))
    )
    path.write_bytes(original[:33] + record + original[33:])
    with pytest.raises(PreparationError, match=match):
        prepare_image(path)


@pytest.mark.parametrize(
    "size",
    [(768, 1152), (1200, 1200), (1600, 900), (600, 1800), (96, 144), (1536, 2304)],
)
def test_default_render_matches_earlier_android_compared_implementation(size):
    spec = importlib.util.spec_from_file_location(
        "legacy_prepare", ROOT / "experiments/python-render/prepare.py"
    )
    legacy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(legacy)
    source = Image.linear_gradient("L").resize(size).convert("RGB")
    w, h = size
    source.paste("red", (w // 7, h // 5, 4 * w // 7, 3 * h // 5))
    old_raster = legacy.prepare(source)
    result = prepare_image(source)
    assert decoded(result.raster_png).tobytes() == old_raster.tobytes()
    assert result.jpeg == legacy.jpeg_bytes(old_raster)


def test_fit_preserves_edges_fill_crops_center():
    source = Image.new("RGB", (96, 48), "lime")
    source.paste("red", (0, 0, 32, 48))
    source.paste("blue", (64, 0, 96, 48))
    results = prepare_comparison(source)
    fit, fill = (decoded(results[m].raster_png) for m in ("fit", "fill"))
    assert fit.getpixel((20, 576)) == (255, 0, 0)
    assert fit.getpixel((748, 576)) == (0, 0, 255)
    assert fit.getpixel((384, 100)) == (255, 255, 255)
    assert fit.getpixel((384, 1050)) == (255, 255, 255)
    # Bilinear filtering blends across the crop boundary by half a source pixel.
    assert fill.crop((12, 0, 756, 1152)).getextrema() == ((0, 0), (255, 255), (0, 0))
    assert results["fit"].manifest["geometry"]["padding_pixels"] == dict(
        left=0, right=0, top=384, bottom=384
    )
    assert results["fill"].manifest["geometry"]["source_crop_box"] == [32, 0, 64, 48]


def test_tall_fit_side_padding_and_tall_fill_crop():
    results = prepare_comparison(Image.new("RGB", (32, 96), "red"))
    assert results["fit"].manifest["geometry"]["padding_pixels"] == dict(
        left=192, right=192, top=0, bottom=0
    )
    assert results["fill"].manifest["geometry"]["source_crop_box"] == [0, 24, 32, 72]
    assert decoded(results["fit"].raster_png).getpixel((10, 576)) == (255, 255, 255)


def test_small_matching_aspect_scales_without_letterbox():
    results = prepare_comparison(Image.new("RGB", (96, 144), "red"))
    for result in (results["fit"], results["fill"]):
        assert result.manifest["geometry"]["scale"] == 8
        assert result.manifest["geometry"]["padding_pixels"] == dict(
            left=0, right=0, top=0, bottom=0
        )
        assert decoded(result.raster_png).getextrema() == ((255, 255), (0, 0), (0, 0))
    assert results["fit"].jpeg == results["fill"].jpeg


@pytest.mark.parametrize(
    "size", [(96, 144), (900, 600), (600, 900), (80, 80), (80, 400), (101, 157)]
)
def test_preserve_edges_fits_whole_source_inside_conservative_box(size):
    # Four colored corners make losing any edge detectable, not just metadata.
    source = Image.new("RGB", size, "black")
    w, h = size
    for color, box in [
        ("red", (0, 0, w // 4, h // 4)),
        ("lime", (3 * w // 4, 0, w, h // 4)),
        ("blue", (0, 3 * h // 4, w // 4, h)),
        ("yellow", (3 * w // 4, 3 * h // 4, w, h)),
    ]:
        source.paste(color, box)
    prepared = prepare_image(source, PreparationOptions("preserve-edges", 100, "4:4:4"))
    geometry = prepared.manifest["geometry"]
    assert geometry["source_crop_box"] == [0, 0, w, h]
    assert min(geometry["padding_pixels"].values()) >= 48 - 1e-9
    x0, y0, x1, y1 = geometry["scaled_image_box"]
    assert (x1 - x0) / (y1 - y0) == pytest.approx(w / h)
    raster = decoded(prepared.raster_png)
    assert raster.crop((0, 0, 48, 1152)).getextrema() == ((255, 255),) * 3
    for fx, fy, color in [
        (0.1, 0.1, (255, 0, 0)),
        (0.9, 0.1, (0, 255, 0)),
        (0.1, 0.9, (0, 0, 255)),
        (0.9, 0.9, (255, 255, 0)),
    ]:
        assert (
            raster.getpixel((round(x0 + fx * (x1 - x0)), round(y0 + fy * (y1 - y0))))
            == color
        )
    assert prepared.manifest["safe_area"]["applied_to_layout"]
    assert not prepared.manifest["safe_area"]["guaranteed"]


def test_preserve_matching_aspect_has_expected_margins_and_orientation():
    source = Image.new("RGB", (144, 96), "red")
    source.getexif()[274] = 6
    prepared = prepare_image(source, PreparationOptions("preserve-edges"))
    assert prepared.manifest["source"]["oriented_size"] == [96, 144]
    assert prepared.manifest["geometry"]["scaled_image_box"] == [48, 72, 720, 1080]
    assert prepared.manifest["geometry"]["scale"] == 7


@pytest.mark.parametrize("mode", images.MODES)
def test_safe_guide_is_separate_from_payload_and_decoded_preview(mode):
    prepared = prepare_image(
        Image.new("RGB", (96, 144), "white"), PreparationOptions(mode)
    )
    before = (prepared.jpeg, prepared.raster_png, prepared.preview_png)
    guide = decoded(images.safe_area_preview(prepared))
    assert guide.getpixel((10, 576)) != (255, 255, 255)
    assert guide.getpixel((384, 576)) == (255, 255, 255)
    assert (
        guide.crop((50, 50, 718, 1102)).tobytes()
        == decoded(prepared.preview_png).crop((50, 50, 718, 1102)).tobytes()
    )
    assert before == (prepared.jpeg, prepared.raster_png, prepared.preview_png)
    assert decoded(prepared.jpeg).tobytes() == decoded(prepared.preview_png).tobytes()


@pytest.mark.parametrize("quality", [1, 90, 100])
@pytest.mark.parametrize("sampling,code", [("4:2:0", 2), ("4:2:2", 1), ("4:4:4", 0)])
def test_jpeg_options_and_actual_decoded_preview(quality, sampling, code):
    result = prepare_image(
        Image.new("RGB", (8, 12), (17, 143, 225)),
        PreparationOptions(quality=quality, subsampling=sampling),
    )
    with Image.open(io.BytesIO(result.jpeg)) as image:
        image.load()
        assert image.size == (768, 1152) and image.mode == "RGB"
        assert JpegImagePlugin.get_sampling(image) == code
        assert not image.info.get("progressive")
        assert image.tobytes() == decoded(result.preview_png).tobytes()
        assert all(v == 1 for t in image.quantization.values() for v in t) == (
            quality == 100
        )
    assert result.manifest["encoding"]["bytes"] == len(result.jpeg)
    assert (
        result.manifest["encoding"]["sha256"] == hashlib.sha256(result.jpeg).hexdigest()
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"quality": 0},
        {"quality": 101},
        {"quality": True},
        {"quality": 90.0},
        {"mode": "stretch"},
        {"subsampling": "4:1:1"},
    ],
)
def test_invalid_options(kwargs):
    with pytest.raises(PreparationError):
        PreparationOptions(**kwargs)


@pytest.mark.parametrize(
    "package,quality,sampling,golden",
    [
        ("package-v2", 90, "4:2:0", "experiments/calibration/package-v2/python.jpg"),
        ("package-v3", 90, "4:2:0", "experiments/calibration/package-v3/python.jpg"),
        ("package-v3", 100, "4:4:4", "experiments/jpeg-quality/q100-444-optimized.jpg"),
    ],
)
def test_existing_calibration_payloads_exact(package, quality, sampling, golden):
    source = ROOT / "experiments/calibration" / package / "source.png"
    result = prepare_image(
        source, PreparationOptions(quality=quality, subsampling=sampling)
    )
    assert result.jpeg == (ROOT / golden).read_bytes()
    with Image.open(source) as original:
        assert decoded(result.raster_png).tobytes() == original.convert("RGB").tobytes()


@pytest.mark.parametrize("sampling", ["4:2:0", "4:4:4"])
def test_prepared_payload_through_simulated_engine(tmp_path, sampling):
    prepared = prepare_image(
        Image.new("RGB", (96, 144), "red"),
        PreparationOptions(quality=100, subsampling=sampling),
    )
    job = JobSpec(
        prepared.jpeg,
        name="PREPARED",
        encoder_quality=100,
        allow_alternative_sampling=sampling != "4:2:0",
    )
    printer = SimulatedPrinter(read_size=17, write_fragment=3)
    with JobJournal(tmp_path / "job.sqlite") as journal:
        engine = JobEngine(
            FramedSession(printer, timeout=1),
            journal,
            DEVICE_ID,
            poll_interval=0,
            observation_timeout=10,
        )
        result = asyncio.run(engine.run(job))
    assert result.state == "completed"
    assert bytes(printer.uploaded) == prepared.jpeg
    assert not result.physical_ejection_confirmed


def test_cli_bundle_manifest_and_exclusive_destination(tmp_path, capsys):
    source = tmp_path / "private-photo.png"
    Image.new("RGBA", (8, 8), (255, 0, 0, 128)).save(source)
    original = source.read_bytes()
    output = tmp_path / "prepared"
    args = [
        str(source),
        str(output),
        "--mode",
        "fit",
        "--quality",
        "100",
        "--subsampling",
        "4:4:4",
    ]
    assert main(args) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["offline"] and summary["ok"]
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["selected_mode"] == "fit"
    assert {p.name for p in output.iterdir()} == {
        "image.jpg",
        "raster.png",
        "preview.png",
        "fit-preview.png",
        "fill-preview.png",
        "preserve-edges-preview.png",
        "safe-area-preview.png",
        "preview.html",
        "manifest.json",
    }
    for filename, record in manifest["files"].items():
        contents = (output / filename).read_bytes()
        assert record == {
            "bytes": len(contents),
            "sha256": hashlib.sha256(contents).hexdigest(),
        }
    assert (output / "preview.png").read_bytes() == (
        output / "fit-preview.png"
    ).read_bytes()
    html = (output / "preview.html").read_text()
    assert "http" not in html and "<script" not in html
    assert str(source) not in html and "private-photo" not in html
    assert "private-photo" not in (output / "manifest.json").read_text()
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    assert main(args) == 1
    assert "already exists" in capsys.readouterr().out
    assert before == {p.name: p.read_bytes() for p in output.iterdir()}
    assert source.read_bytes() == original


def test_cli_bad_input_or_options_leaves_no_output(tmp_path, capsys):
    source = tmp_path / "bad.jpg"
    source.write_bytes(b"not a JPEG")
    output = tmp_path / "prepared"
    assert main([str(source), str(output)]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False
    assert not output.exists()
    assert main([str(source), str(output), "--quality", "101"]) == 1
    assert "quality" in capsys.readouterr().out
    assert not output.exists()


def test_bundle_write_failure_removes_partial_output(tmp_path, monkeypatch):
    results = prepare_comparison(Image.new("RGB", (8, 12)))
    original_open = __import__("os").open

    def failing_open(path, flags, mode):
        if Path(path).name == "preview.png":
            raise OSError("disk failure")
        return original_open(path, flags, mode)

    monkeypatch.setattr("zink_probe.prepare_cli.os.open", failing_open)
    output = tmp_path / "prepared"
    with pytest.raises(OSError, match="disk failure"):
        write_bundle(output, results, PreparationOptions())
    assert not output.exists()


def test_cli_help_and_imports_do_not_load_hardware_or_pillow():
    script = """
import sys
import zink_probe.prepare_cli
assert not any(m.startswith(('PIL', 'bleak', 'objc', 'IOBluetooth', 'zink_probe.jobs')) for m in sys.modules)
try:
    zink_probe.prepare_cli.main(['--help'])
except SystemExit as exc:
    assert exc.code == 0
"""
    subprocess.run([sys.executable, "-c", script], check=True, capture_output=True)


def test_preparation_api_imports_no_transport():
    script = """
import sys
from PIL import Image
from zink_probe.images import prepare_image
prepare_image(Image.new('RGB', (8, 12)))
assert not any(m.startswith(('bleak', 'objc', 'IOBluetooth', 'zink_probe.jobs')) for m in sys.modules)
"""
    subprocess.run([sys.executable, "-c", script], check=True, capture_output=True)


def test_cli_missing_optional_dependency_gives_install_hint():
    script = """
import sys
class NoPillow:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] == 'PIL':
            raise ModuleNotFoundError('Pillow is intentionally absent')
sys.meta_path.insert(0, NoPillow())
from zink_probe.prepare_cli import main
assert main(['unused-input.jpg', 'unused-output']) == 1
"""
    result = subprocess.run(
        [sys.executable, "-c", script], check=True, capture_output=True, text=True
    )
    assert "zink-probe[images]" in json.loads(result.stdout)["error"]
