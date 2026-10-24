# Python reproduction of Select image preparation

**2026-10-24 update:** the [public API and CLI](IMAGE_PREPARATION.md) now add EXIF
orientation, ICC-to-sRGB normalization, fit/fill previews and JPEG options. The
experiment below is retained as the historical Android comparison; its original
already-oriented sRGB input boundary still applies to those measurements.

2026-10-22. An independent offline Python implementation now reproduces the
Select's measured final bitmap geometry and JPEG settings. We compared it against
existing outputs of the original Android APK 3.0.2921.1 / 74251, rather than against
our own reconstruction of the Java code. No emulator, radio, printer connection,
print submission, or paper was used in this follow-up.

Code: [prepare.py](experiments/python-render/prepare.py).
Usage: [experiment README](experiments/python-render/README.md).
Full measurements and hashes: [comparison.json](experiments/python-render/evidence/comparison.json).
Previous primary execution evidence: [Android renderer](ANDROID_RUNTIME.md) and
[editor investigation](EDITOR_PIPELINE.md).

## Implemented boundary

The input is an already oriented/edited sRGB bitmap. The renderer computes
`s = max(768 / width, 1152 / height)`, centers the scaled image, and samples into
an opaque 768 × 1152 output. This preserves aspect ratio and crops excess image;
it does not stretch to a new aspect ratio or add fit borders. Existing white
borders in an edited image are part of its pixels and can survive the final crop.

Pillow's inverse affine transform with bilinear interpolation is used explicitly.
Its ordinary `resize(..., BILINEAR)` operation produced larger differences on these
fixtures, including where affine sampling was exact. An exploratory run with
skia-python 144.1 also differed more: for 96 × 144 enlargement its average channel
error was 0.3232 versus zero for the chosen method. Sharing a graphics engine's
name does not establish the same version, sampling precision, or raster path.
The exact cause of remaining Android-versus-Pillow sampling differences is not
yet established; subpixel arithmetic/rounding is a plausible explanation.

The result can be saved as lossless PNG or baseline JPEG at quality 90, 4:2:0,
with optimized Huffman coding. It carries no EXIF, physical DPI, or extracted
vendor ICC profile. The implementation imports no vendor library and contains no
printer transport or job commands. It is an experiment outside the diagnostic CLI.

## Final renderer results

Metrics below compare RGB pixels **before JPEG encoding**, against Android with
PhotoFix skipped. Mean errors average absolute differences across all pixels and
all three channels, each on a 0–255 scale. A small mean does not mean every pixel
is identical: sharp synthetic edges have larger local errors.

| Input | Mean channel error | Maximum channel error | Pixels differing | Decoded JPEG mean error |
| --- | ---: | ---: | ---: | ---: |
| 768 × 1152 | 0 | 0 | 0% | 0 |
| 1200 × 1200 | 0.008128 | 11 | 0.173611% | 0.032464 |
| 1600 × 900 | 0.055301 | 13 | 2.956475% | 0.261212 |
| 600 × 1800 | 0.085432 | 13 | 4.380968% | 0.363510 |
| 96 × 144 | 0 | 0 | 0% | 0 |
| 1536 × 2304 | 0 | 0 | 0% | 0 |

The 96 × 144 case scales by exactly 8 in both axes, with no padding/cropping.
This is the direct final-renderer route. The earlier editor's small-image route
still has its separately documented 1000 × 1500 intermediate; this CLI does not
silently insert that stage.

All 72 existing render cases were compared: six synthetic sizes × three routes
× two PhotoFix requests × two harness configurations. These repeated cases share
fixtures. Python always omits PhotoFix. Comparisons to successful Android PhotoFix
therefore measure a missing enhancement step as well as any sampling difference;
they are not evidence of a PhotoFix implementation. The default-tagging harness's
failed enhancement path matched its plain path, as previously documented.

## JPEG equivalence and differences

A later [quality and format experiment](JPEG_QUALITY_AND_FORMATS.md) compares
quality 90/95/100 and 4:2:0/4:2:2/4:4:4 on the unchanged CAL-03 raster, with
isolated firmware header/setup tests. Those research candidates do not change
the quality-90 4:2:0 defaults or the Android-equivalence results below.

All compared Android/Python JPEGs use identical quantization tables and 4:2:0
sampling. For the three pixel-exact sizes above, **the complete JPEG is byte-exact
after removing only Android's ICC APP2 segment**. This is stronger than equal
output dimensions or visually similar images. Across repeated configurations,
27 of the 72 comparisons have this property; the others include nonintegral
sampling and successful PhotoFix cases.

Android embeds a 456-byte sRGB profile whose complete JPEG marker occupies 474
bytes. Python deliberately omits that captured profile. For the 768 × 1152 case,
Python is 41,835 bytes versus Android's 42,309. A diagnostic local encoding with
the captured profile restored was byte-for-byte identical for the three exact
sizes; no extracted profile is distributed or required by this implementation.

Initial encoding without Huffman optimization decoded identically for those
sizes but made larger files (53,146 bytes for the first case). Enabling optimization
resolved that compressed-stream difference. For the other sizes, JPEG compression
spreads small raster differences into neighboring pixels; maximum decoded error
in the six plain cases is 13. Byte equivalence is established only for these
captures and the recorded library versions, not all Python/Android builds.

## Editor transform replay

All 38 previous editor cases were replayed starting at the captured normalized
`measured.jpg`, using the captured forward matrix. Python draws onto a fixed-size
white canvas, saves/decodes JPEG 100, then performs final Select preparation.
This covers recorded identity, half/double scale, rotation, translation, and
fit/fill matrices, including cases whose input had already been EXIF-normalized
by Android. It does not independently reproduce that earlier normalization.

- 27 of 38 decoded edited images were pixel-exact. Across all 38, the largest
  average edited-image error was 0.060407, maximum individual channel error 6.
- After the final render, no complete image was pixel-exact. The largest average
  final error was **0.051236**, maximum channel error **7**. The largest mean
  occurred in the 96 × 144 source's double-scale case.
- Isolating only final rendering from Android's already edited bitmap reduced
  the worst average error to 0.010579, with maximum channel error 6.

This reproduces white-border and clipping geometry closely while retaining
measured differences. It is not a port of gesture limits, the complete app UI,
frame assets, or editor state transitions. The matrix input is recorded Android
state, not a result independently derived from a synthetic touch gesture.

## Remaining gaps and validation

PhotoFix is the largest known omitted processing stage. The successful native
algorithm previously changed average channel values by roughly 0.49–7.87 across
these fixtures. We do not substitute an invented contrast/sharpening operation.
Full source-file preparation (EXIF, image loaders, minimum size, downsampling,
color management), transparency fidelity, decorative layers, and real-photo
coverage remain unvalidated. White alpha compositing is our explicit policy,
not a measured claim about every Android input path.

Eight synthetic unit tests cover center crop, enlargement without padding,
fixed-canvas rotation, white borders, invalid matrices, alpha policy, identity,
and JPEG properties. The comparison independently records every measured
mismatch and reference hash. Python 3.14.8, Pillow 13.0.0, NumPy 2.5.4, and
libjpeg-turbo 3.2.0 produced this report. No physical print quality or device
acceptance follows from these offline results.
