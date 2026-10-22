# SELECT-CAL-01: preserved offline calibration package

The current revision is [SELECT-CAL-02](REVISION_2.md), with images and a separately
authorized one-sheet experiment. This document retains CAL-01 history.

Prepared 2026-10-22 as an offline-only package. CAL-01 was not sent to a printer.
The later CAL-02 experiment has separate explicit permission for one physical
sheet; see its revision and outcome documents. The purpose of this retained
package was to make a future single-sheet experiment reviewable and reproducible.

## Practical value versus curiosity

The first sheet should primarily test geometry, clipping, orientation, and whether
an independently prepared JPEG behaves as intended. Those results can improve a
driver's scaling/margin policy and avoid wasted sheets. The transaction trace can
improve job submission, progress reporting, and recovery even without a print.

Fine-detail patches can assess effective output detail and help choose a resampler.
Feed-motion measurements mainly inform time estimates and diagnostics. Exact heater
count and native thermal addressing remain research questions: they are not
prerequisites for a useful JPEG-based driver, and this sheet cannot uniquely recover
them. Do not turn this into an open-ended paper-consuming resolution search.

## Which measurements would change a driver?

| Chart or measurement | Potential implementation change | What would not justify a change |
| --- | --- | --- |
| Edge ticks and four corner references | Document actual printable area; offer a measured safe-content inset or explicit fill/fit choice if content is clipped | A tiny apparent loss in an uncalibrated photo; do not compensate for camera perspective |
| Reference spans and center cross | Correct an established placement offset or aspect distortion; distinguish intentional borderless enlargement from a preparation error | Treating input-pixel density as head DPI; do not stretch images simply to make inferred densities equal |
| Asymmetric TOP label and layout | Apply one verified orientation transform if the independent path rotates/mirrors unexpectedly | Changing orientation based on which physical edge emerges first alone |
| Horizontal/vertical line and isolated-mark patches | Choose preprocessing/resampling that preserves useful detail, if future controlled comparisons demonstrate an improvement | Claiming a preferred filter from one sheet, or deriving an exact heater count from visible bars |
| Neutral/color controls | Detect gross channel swaps or processing errors; establish whether a later color study is worthwhile | Creating a color profile, gamma correction, or sharpening default from these few patches |
| Job/status timing and video | Separate uploading/queued/printing/completed UI; improve conservative timeouts and estimates | Changing thermal drive or feed timing: no corresponding control is established |
| Exact native pitch, heater count, line-firing rate | Usually no change for a driver that supplies the firmware's required JPEG | Blocking a useful driver until these hardware facts are known |

A first sheet can find a concrete defect; it cannot by itself prove the best
correction. Any correction should be justified by repeatable, calibrated evidence.
The useful outcome may simply be “geometry is acceptable; leave preparation as is.”

## Files

- `package/source.png`: generated 768 × 1152 chart with no DPI metadata.
- `package/python.png`, `python.jpg`: Python final raster and quality-90 payload.
- `package/android.png`, `android.jpg`: original Android renderer, PhotoFix skipped.
- `package/android-photofix.png`, `android-photofix.jpg`: requested PhotoFix variant.
- `package/manifest.json`: exact reference coordinates, line-patch bounds, hashes.
- `package/comparison.json`: all six Android route comparisons and per-patch metrics.
- `package/transaction-android.json`: original serializers/bookkeeping on synthetic
  handles, job IDs, and bytes. **Not a captured printer transaction.**
- `package/source-index.json`: local decompiled-source fingerprints supporting the
  [transaction trace](../../PRINT_TRANSACTION.md); no vendor source is distributed.
- `measurements.csv`: blank future measurement record; no invented physical results.

The PNG/JPEG assets are our own synthetic chart and its processed outputs. The
Android JPEGs include its standard sRGB ICC segment; vendor APKs/libraries and raw
runtime logs remain ignored. The printed chart says PhotoFix OFF to identify the
proposed geometry baseline. The separately named PhotoFix variant is an offline
comparison and happens to be identical for this chart.

## Measured software results

Original APK 3.0.2921.1 / 74251 on the dedicated Android 16 ARM64 emulator; only
our permission-free harness ran. Native heap pointer tagging was disabled in the
harness, as in the prior successful PhotoFix experiment. Bluetooth, Wi-Fi, and
mobile data were disabled. The emulator was shut down afterward.

Six runs: override/file-Lanczos/file-matrix × PhotoFix skipped/requested. All six
completed, matched `processData`'s JPEG, and produced **pixel-exact Python/Android
rasters**. All six JPEGs equal Python's JPEG after removing only Android's ICC
segment. Python JPEG: 139,679 bytes. Android JPEG: 140,153 bytes. The additional
474 bytes are the ICC marker and profile, not extra image detail.

PhotoFix-requested outputs were identical to skipped outputs. The diagnostic
native apply returned SUCCESS with a positive handle for each requested case.
This chart-specific result does not establish that PhotoFix is generally inert;
the earlier photographic-gradient fixtures changed substantially.

JPEG itself alters the source: mean absolute RGB error 0.437148, maximum channel
error 125, and 14.012203% of pixels differ. Across the 24 black/white line patches,
we separately retain decoded luminance extrema and source-to-JPEG errors. The
one-pixel horizontal zero-phase patch is exact; the vertical zero-phase patch's
maximum error is 4 and mean column luminance runs approximately 0.1–254.85.
Thus fine monochrome structure survives this encoding, but color boundaries and
other regions must be interpreted against the **decoded JPEG**, not the PNG alone.
No paper-resolution conclusion follows from these software measurements.

## Proposed future one-sheet procedure — not executed

1. Explicitly authorize one print later. Choose exactly one hashed payload and
   one copy. Prefer the Python JPEG for testing our independent preparation; the
   Android JPEG is an encoding reference, not a request for a second sheet.
2. Record firmware, battery/external power, paper pack, room conditions, selected
   payload hash, and pre-print page/calibration counters. Keep enhancement and
   editor auto-fit out of this geometry baseline. Sending the chart through the
   phone's ordinary gallery/editor can introduce the 1000-pixel intermediate;
   that would be a different experiment and must be recorded as such.
3. Record upload start/end, job ID, status/queue changes, first visible paper motion,
   and final motion separately. Video from a fixed side/overhead position with a
   stationary ruler can measure edge displacement. Do not touch or restrain the
   moving sheet. Observe which chart edge emerges first rather than assuming TOP
   is the feed direction. Use frame timestamps, especially with variable frame rate.
4. Measure actual sheet width/height. After output has stabilized, scan flat with
   automatic resizing, sharpening, and corrections disabled, retaining a lossless
   original. Include a physical scale in the same plane; verify scanner scaling in
   both axes. If using a camera, control perspective and lens distortion before
   making small-scale claims. Check apparent patterns at more than one acquisition
   scale/orientation to distinguish scanner/camera aliasing from print behavior.
5. Measure the cross centers at (48,48), (720,48), (48,1104), (720,1104), and
   (384,576). The horizontal reference separation is 672 input pixels; vertical
   separation 1056. Compare top/bottom spans and left/right spans to detect skew
   or measurement distortion. Record edge ticks lost to clipping (8-pixel spacing).
6. If a measured horizontal span is Lx mm, effective input-pixel size is
   Lx/672 mm and effective input density is 25.4*672/Lx pixels/inch. Vertically use
   Ly/1056 and 25.4*1056/Ly. These are input-to-paper mappings, **not head DPI**.
   Measure coordinate offsets from paper edges using the same calibrated scale.
   Report uncertainty: a ±e mm span measurement contributes approximately e/L
   relative uncertainty to the inferred density.
7. Compare each printed line/edge patch with the decoded payload. Record which
   alternating lines remain distinguishable in each axis and phase. Do not equate
   a 1-pixel bar with one heater. A black+white pair is a 2-pixel spatial period;
   enhancement, thermal spread, feed behavior, and capture optics can all change it.
8. For motion, compute v = displacement_mm / elapsed_seconds over multiple visible
   intervals, rather than sheet length divided by total job time. This estimates
   transport speed over those intervals. It cannot provide line-firing frequency
   or heater count without independent timing/head-geometry information.

A useful stopping point is one sheet with measured geometry and an accepted JPEG.
Only propose another sheet if the first exposes a specific driver-relevant defect.
A blank measurement CSV is supplied; confidence and capture calibration matter
more than quoting extra decimal places.

## Reproduction

Use the analysis environment described in `../python-render/README.md` (Pillow
13.0.0 / NumPy 2.5.4 for the retained outputs). Run from the repository root:

```sh
python experiments/calibration/build_chart.py
```

Use only the dedicated emulator workflow in `../android-render/README.md`.
Build with `DISABLE_POINTER_TAGGING=1`; install the harness there, and copy the
source into its private files directory with `adb ... run-as`. Launch with
`--es run calibration --ez calibration true`. This mode uses the provided bitmap,
skips the earlier message-inspection routine, and runs six render cases. Capture
`files/results-calibration` locally, then:

```sh
python experiments/calibration/compare_chart.py logs/android-runtime/calibration/files/results-calibration
python experiments/calibration/verify_package.py
```

The `--es run transaction --ez transactionOnly true` mode creates
`files/results-transaction/transaction.json` using original serializers and
transfer bookkeeping only, before device/options/service creation. Its start
length is the fixture's Python JPEG length (139,679); handle 7 and job 0x1234 are
synthetic. No controller, queue client, or transport is instantiated by that mode.
