# Offline iOS photo preparation (build 5)

Open **Prepare a photo offline** in Select Probe. Select a photo with the system
Photos picker, choose Borderless / Fit / Preserve edges and JPEG quality 90, 95
or 100. The preview is decoded from the actual prepared JPEG. Save prepared JPEG
to Files exports it without sending anything to the printer. No Print or Send
button exists; no transport/print engine is called by the preparation code.
The system picker may need to retrieve an iCloud-only original; processing itself
is local. No broad photo-library permission or automatic photo upload is added.

## Image handling

- ImageIO applies EXIF orientation, including mirrored variants, during decoding.
- JPEG, PNG and HEIC inputs; single-image JPEG/PNG, first HEIC image. GIF/animated
  PNG and unsupported types are rejected. HEIC auxiliary/HDR behavior has not
  been physically compared on iPhone; use SDR originals for controlled comparisons.
- Input bound: 50 MB / 80 MP; decoding is capped to a 4096-pixel long edge to bound
  working memory. This adds a resampling stage for larger originals. Native work
  is serialized off the UI executor; generation tokens discard obsolete results.
- CoreGraphics draws into an 8-bit sRGB canvas using relative-colorimetric intent.
  Embedded image color spaces are handled by the Apple color pipeline. Untagged
  image interpretation is delegated to ImageIO. This is not the same strict
  input-color policy or LittleCMS implementation as the Python API.
- Alpha is composited on white; final canvas is 768 × 1152. Borderless uses centered
  cover, Fit uses centered contain, and Preserve edges uses centered contain
  inside (48,48)–(720,1104). No automatic landscape rotation or PhotoFix.
- The purple safe-area overlay is a UI layer only, absent from JPEG exports.
  Preserve edges is conservative guidance, not a guaranteed trim correction.
- New JPEG is encoded from the raster, not source metadata; output explicitly
  declares EXIF sRGB. Source EXIF/GPS/author metadata is not copied.
- Apple JPEG quality is a native compression parameter, not a libjpeg-equivalent
  promise. This version does not offer a chroma-subsampling selector. macOS tests
  observed 4:2:0 at 90/95 and 4:4:4 at 100. Do not infer that all iOS versions or
  inputs do the same, or that q100 is lossless.

## Comparison and validation

`photo-tests/main.swift` compiles the same Foundation/CoreGraphics/ImageIO engine
on macOS and writes all three layouts at all three qualities. `check.py` generates
synthetic orientation/alpha/color fixtures and compares optional private saved
Android render fixtures. CI runs the synthetic checks on macOS and compiles the
complete iPhone application; it does not validate the physical iPhone UI.

```sh
swiftc ios/SelectAccessoryProbe/PhotoPreparation.swift ios/photo-tests/main.swift -o build/ios-photo-tests
.venv/bin/python ios/photo-tests/check.py build/ios-photo-tests logs/ios-photo-preparation \
  --android logs/android-runtime/full-default/files/results-full-default
```

All eight EXIF orientations passed corner-color checks; transparency became white;
source author metadata was absent; output sRGB declaration and size were checked.
A Display P3 midtone is compared against LittleCMS with a three-level tolerance.
The numeric evidence is in [photo-tests/evidence/summary.json](photo-tests/evidence/summary.json).

For the existing synthetic Android plain/file-matrix fixtures, comparison is of
pre-JPEG RGB rasters, no PhotoFix:

| Source | Apple vs Python max channel difference | Apple vs Android max channel difference |
| --- | ---: | ---: |
| 96 × 144 | 73 | 73 |
| 768 × 1152 | 0 | 0 |
| 1200 × 1200 | 15 | 26 |
| 1600 × 900 | 24 | 31 |

Mean absolute per-channel differences are recorded too. Native-size output was
identical for this fixture; interpolation differs on resized fixtures. Apple
uses high-quality native interpolation, while our reference uses bilinear.
These results do not establish universal visual equivalence, byte-identical JPEGs,
or physical-print quality. The Android results are previously captured outputs,
not a new Android run. The Apple comparison runs on macOS, not an iPhone runtime.

The signed iPhone application build and installation are checked separately.
Selecting a real photo, switching layouts and exporting on the phone still need
user confirmation. No paper is consumed by this milestone.

## Connection guidance

The existing diagnostic screen includes instructions distinguishing pairing from
connection, an awake nearby printer, iPhone Settings and possible other-host
connections. Power cycling/toggling Bluetooth is described only as an observed
workaround, not a guaranteed fix. Photo preparation requires no printer connection.
A Share extension and actual iOS job submission remain separate future milestones.
