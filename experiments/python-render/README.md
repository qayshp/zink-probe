# Offline Python Select image preparation

Independent Python implementation of the measured prepared-bitmap path: center
crop to fill 768 × 1152, affine bilinear sampling, baseline JPEG quality 90,
4:2:0 chroma subsampling, optimized Huffman coding. No Bluetooth, network, vendor
binary, print-job serialization, or printer access. This experiment is separate
from the diagnostic CLI and does not add dependencies to the installed probe.

The input contract is **already oriented/edited, sRGB pixels**. The tool does
not apply EXIF orientation, color-profile conversion, PhotoFix, the app's
1000-pixel editor minimum, or decorative frames. It composites transparency on
white as a documented policy; transparent/color-managed inputs were not compared
against Android. Arbitrary-file import parity is not claimed.

From the repository root, create an isolated environment and install
`experiments/python-render/requirements.txt`. Pillow alone suffices for preparation
and tests; NumPy is used only by the comparison. Then run:

```sh
python experiments/python-render/prepare.py prepared-input.png prepared-select.jpg
python experiments/python-render/prepare.py prepared-input.png prepared-select.png
python -m unittest discover -s experiments/python-render -v
```

Only the local output is created. Existing outputs and identical input/output
paths are rejected. PNG provides lossless inspection; JPEG is the measured
quality-90 encoding. No DPI or EXIF is written. Unlike Android, the standalone
encoder does not embed its 456-byte sRGB ICC profile.

`editor_transform(image, matrix)` is an experimental API for replaying a saved
forward affine matrix on a fixed white canvas. It does not reconstruct editor
state from gestures. The comparison starts at Android's captured `measured.jpg`,
replays the recorded matrix, encodes/decodes JPEG 100, and runs our final renderer.
It separately tests the final renderer starting from Android's edited pixels.
Thus earlier loading, EXIF, minimum-size normalization, and initial JPEG encoding
are deliberately outside this replay's validation boundary.

To reproduce the comparisons using the original locally retained synthetic
captures described in `../android-render/README.md`:

```sh
python experiments/python-render/compare.py logs/android-runtime experiments/python-render/evidence/comparison.json
```

No emulator is needed for this command. The raw captures are ignored and are not
part of the public repository; the Android harness can regenerate them with the
specified separately acquired APK. The committed report includes input/reference
hashes, dependency versions, all 72 render comparisons and 38 editor comparisons.
Those are repeated routes/configurations, not 110 distinct photographs. Missing
captures or capture errors fail explicitly. Metrics measure differences; they do
not silently assert equivalence or filter away mismatches.

See [PYTHON_IMAGE_PREPARATION.md](../../PYTHON_IMAGE_PREPARATION.md) for findings,
known omissions, and interpretation. Physical print compatibility is untested.
