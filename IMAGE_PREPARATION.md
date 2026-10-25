# Offline Select image preparation

2026-10-24. `zink_probe.images` and `zink-prepare` turn a photo into a fully
decoded/checked **768 × 1152 baseline JPEG**, with EXIF orientation, explicit
color handling and fill/fit/preserve-edges previews. Preparation has no Bluetooth dependency,
imports no transport, and cannot submit a job. It runs on Python 3.11+ with the
optional `images` extra on macOS, Linux and Windows.

## Install and prepare

Run inside the checkout, using your chosen Python environment:

```sh
python -m pip install -e '.[images]'
zink-prepare photo.jpg prepared-photo --mode fill
```

The output directory must be new and its parent must exist. Inputs and existing
output directories are never overwritten. The command exits nonzero on an error
and prints a JSON result. Successful preparation includes a complete JPEG decode,
not just a header check. Windows PowerShell accepts these same command arguments.

To retain the whole image and use the higher-information encoding:

```sh
zink-prepare photo.png prepared-fit --mode fit --quality 100 --subsampling 4:4:4
```

Open `prepared-fit/preview.html` locally. It needs no server, network, scripts or
remote assets. A [committed synthetic example](examples/image-preparation/README.md)
shows the result without sharing a personal photo.

| Choice | Behavior |
| --- | --- |
| `--mode fill` (default) | Scale uniformly to cover the canvas; crop equally from opposing sides. |
| `--mode fit` | Scale uniformly to keep the whole image; center it on white padding. |
| `--mode preserve-edges` | Fit the whole image inside a conservative 48-pixel inset; center it on white. |
| `--quality 1..100` | JPEG encoder quality, default **90**. Quality 100 remains lossy. |
| `--subsampling 4:2:0` (default) | Matches the measured app's ordinary JPEG sampling. |
| `--subsampling 4:2:2` | Intermediate chroma sampling; available for offline experiments. |
| `--subsampling 4:4:4` | Retains full chroma sampling; quality 100 / 4:4:4 worked on one physical Select. |

These options change the submitted image, not the printer's heater temperature,
feed speed, firmware LUT or physical resolution. The full numeric quality range
is an encoder capability, not a claim that every combination has been physically
printed. The default remains quality 90 / 4:2:0. See the earlier
[encoding investigation](JPEG_QUALITY_AND_FORMATS.md) and
[CAL-03 print evidence](experiments/calibration/CAL03_PRINT.md).

## Bundle contents

| File | Meaning |
| --- | --- |
| `image.jpg` | Selected layout result, ready for the separate job engine. |
| `raster.png` | Selected RGB pixels before JPEG compression. |
| `preview.png` | Lossless PNG of the **decoded selected JPEG**, including compression changes. |
| `fit-preview.png`, `fill-preview.png`, `preserve-edges-preview.png` | Three framing choices, each decoded from a JPEG using the requested quality/sampling. |
| `safe-area-preview.png` | Selected decoded JPEG with a violet suggested-safe-area guide. Preview only. |
| `preview.html` | Three layouts with toggleable safe-area guides and links to selected artifacts. |
| `manifest.json` | Source hash, transformations, framing geometry, encoder settings/versions and artifact hashes. |

The previews show digital pixels. They do not predict paper color, contrast,
thermal response or the printer's unequal physical edge trimming. Fit preserves
the image inside the digital canvas; it does not guarantee that the printer
retains every border pixel. The optional Preserve edges policy deliberately adds
white margins; it does not apply asymmetric offsets or predict exact trimming.
See [policy, evidence, examples and Windows queue support](PRESERVE_EDGES.md).

The manifest records the source file's hash but not its filename, full path, EXIF
description, GPS data or ICC description. Paths appear only in the CLI's local
result. Output files contain the image itself and must still be treated as private
when preparing personal photos. On POSIX systems the new directory is created
with mode 0700 and files with 0600; Windows uses the parent directory's ACLs.

## Python API

```python
from pathlib import Path
from zink_probe.images import PreparationOptions, prepare_image, prepare_comparison, safe_area_preview

options = PreparationOptions(mode="preserve-edges", quality=100, subsampling="4:4:4")
result = prepare_image(Path("photo.jpg"), options)

# Immutable byte payloads; no files are written by these preparation functions.
jpeg_bytes = result.jpeg
before_compression = result.raster_png
decoded_preview = result.preview_png
details = result.manifest

guided_preview = safe_area_preview(result)  # Separate PNG; never submit this guide.
layouts = prepare_comparison("photo.jpg", options)
assert set(layouts) == {"fit", "fill", "preserve-edges"}
```

`prepare_image` returns `PreparedImage`; `prepare_comparison` normalizes the input
once and returns three results with the same encoder settings. `options.mode`
selects a single result in `prepare_image` and the CLI; comparison always returns
all modes. The manifest is a regular dictionary intended for serialization.
Invalid image data/settings raise `PreparationError`, a `ValueError` subclass.
Programmer errors such as an unsupported options type raise `TypeError`.

Sources may also be Pillow `Image.Image` objects. The API copies pixels and
does not mutate the supplied image/EXIF. In-memory callers own source decoding:
use the path interface when its file-format, bit-depth, CRC and size checks are
required. An in-memory image has no source-file hash. No `bytes` or URL input is
accepted; file reads are local.

Passing the result into a **simulator** is an independent operation:

```sh
zink-simulate prepared-fit/image.jpg --journal logs/prepared-simulation.sqlite --name PREPARED --allow-alternative-sampling --encoder-quality 100
```

The engine still requires its explicit alternative-sampling opt-in for 4:4:4 or
4:2:2. Preparation does not bypass the engine's identity, queue, journal or
submission safeguards. This example cannot access real printer hardware.

## Processing policy

1. Read and fully decode a single-frame JPEG or PNG. Reject corrupt/truncated
   inputs, more than 64 million input pixels or more than 100 MiB of file data.
   Refuse Pillow's global truncated-image allowance. PNG structural verification
   runs before decoding.
2. Apply EXIF orientation 1–8, including reflected/transposed cases, **before**
   calculating layout. Remove source EXIF/XMP/comment metadata from outputs.
3. Convert an embedded ICC profile to sRGB with LittleCMS, using relative
   colorimetric intent and black-point compensation. Validate that the profile
   color space matches the image. Invalid, undecodable, mismatched or oversized
   profiles fail; they do not silently fall back to an sRGB assumption.
4. Treat untagged RGB/palette/grayscale as sRGB and record that assumption.
   Respect a PNG sRGB tag; accept compatible gamma/chromaticity tags. Reject
   explicit non-sRGB gamma/chromaticities without an ICC profile. Untagged CMYK
   fails because its conversion cannot be inferred reliably. Tagged CMYK/gray
   profiles use LittleCMS's corresponding transform; the committed nontrivial
   conversion fixture exercises an RGB profile, not a CMYK printer profile.
5. Composite transparency over white **after** color conversion, in encoded
   sRGB. This preserves the earlier research's compositing policy; it is not
   linear-light alpha compositing. Grayscale and palette images become RGB.
6. Render into 768 × 1152 using centered inverse-affine bilinear sampling.
   Fill uses `max(768 / width, 1152 / height)`, fit uses `min(...)`. Small images
   may enlarge: 96 × 144 becomes 768 × 1152 at 8×, with no padding in fit/fill.
   Preserve edges uses `min(672 / width, 1056 / height)`; that same source
   becomes 672 × 1008 at 7× with 48/72-pixel horizontal/vertical margins.
   Geometry is recorded as floating-point source crop/scaled-image bounds;
   interpolation can blend half a source pixel beyond a nominal crop edge.
7. Encode a baseline JPEG with optimized Huffman tables, the chosen quality
   and sampling. Fully decode it and verify dimensions, RGB mode, baseline
   coding and chroma sampling before returning it. Derive preview PNGs from
   those decoded pixels.

The JPEG pixels are sRGB, but no ICC APP2, EXIF or physical-DPI declaration is
embedded, matching the established host-side compatibility path. PNGs carry an
explicit sRGB tag. Encoder and LittleCMS versions are retained in the manifest.

The file interface supports SDR, at most 8-bit channels, with bilevel/palette
PNG also accepted. It rejects animated/multi-frame files, 16-bit PNG, PNG CICP/HDR
metadata, unsupported modes, GIF, TIFF, HEIC and RAW. Export those to an 8-bit
sRGB JPEG/PNG first. This version does not implement HDR tone mapping, PhotoFix,
arbitrary editor rotations, decorative borders, perceptual sharpening or thermal
precompensation. EXIF orientation and the three centered layouts are the geometry API.

## Validation and compatibility boundary

`tests/test_images.py` covers all EXIF orientations, immutability, real ICC
conversion, conversion-before-alpha, grayscale/palette inputs, invalid color
metadata, file limits, crop/padding geometry, all three sampling choices at
quality 1/90/100, complete preview decode equality, CLI bundles and simulated jobs.
The generated [linear RGB profile](tests/fixtures/images/make_profile.py) uses
LittleCMS's sRGB primaries with gamma 1.0. An encoded value of 128 converts to
approximately 188 in sRGB, providing a clear test against merely relabeling pixels.

Regression checks retain exact JPEG bytes for CAL-02 and CAL-03 at quality 90 /
4:2:0 and CAL-03 at quality 100 / 4:4:4. Six additional synthetic sizes compare the
new default renderer with the earlier Python implementation that was measured
against Android. The new input-normalization policy is deliberately explicit;
it is **not** evidence that arbitrary-photo importing matches the Android app.
Earlier Android-versus-Python differences remain documented in
[PYTHON_IMAGE_PREPARATION.md](PYTHON_IMAGE_PREPARATION.md).

[CI](https://github.com/qayshp/zink-probe/actions/workflows/ci.yml) runs this suite
on macOS, Linux and Windows with Python 3.11 and 3.14. It also invokes the installed
preparation CLI, simulates a job using its newly generated JPEG, and builds the
wheel. No CI test connects to a printer. JPEG golden bytes are enforced for the
recorded/current Pillow builds; arbitrary future encoders are not promised to
produce byte-identical compressed streams.

### Recorded results, 2026-10-24

Implementation commit [`31b065c`](https://github.com/qayshp/zink-probe/commit/31b065c2940ec67fdeaf320b09afbddb1702e9c3)
passed [all six CI jobs](https://github.com/qayshp/zink-probe/actions/runs/40134111389):

| Runner | Python 3.11 | Python 3.14 |
| --- | --- | --- |
| macOS | Passed | Passed |
| Linux (Ubuntu) | Passed | Passed |
| Windows | Passed | Passed |

Each ran **484 passing tests, 2 expected native-binding skips**, plus the 8 earlier
image-research tests and 11 calibration-transcript tests. Both macOS jobs then
installed the native extra and passed the 2 skipped binding tests without opening
Bluetooth. The 66 new image-preparation cases ran on every platform. CLI
preparation, simulated transfer and wheel building also passed in every job.

All six generated the same **125,874-byte** JPEG from the committed synthetic
source using fit, quality 100 and 4:4:4. SHA-256:

```text
819313892c0a381a71ecdf4d8c8be49c86356b56e68945c71b0d7beef98b2c85
```

Every simulated transfer reconstructed those bytes exactly. The three historical
CAL-02/CAL-03 payload comparisons were also byte-exact in all six jobs. This is
cross-platform output evidence for these fixtures, not a blanket guarantee for
every future Pillow/codec version.

Local macOS validation passed **486 tests** with native dependencies installed,
the same 8 + 11 research tests, lint, formatting and wheel build. A separate fresh
environment confirmed that the built wheel's core imports without Pillow, that
`zink-prepare --help` works there, and that image preparation gives an installation
hint until the `images` extra is installed. The committed fit/fill PNGs were
visually inspected and all bundle hashes verified. No printer was contacted.

Primary library references: [Pillow EXIF transpose](https://pillow.readthedocs.io/en/stable/reference/ImageOps.html#PIL.ImageOps.exif_transpose),
[ImageCms color transforms](https://pillow.readthedocs.io/en/stable/reference/ImageCms.html),
and [JPEG encoding options](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#jpeg).
