# SELECT-CAL-02 revision and first-sheet preparation

2026-10-22. The operator authorized this revised chart and, conditional on the
checks passing, **one physical print**. This supersedes the earlier no-print limit
only for this first sheet. CAL-01 remains preserved under `package/`; CAL-02 and
its actual images are committed under `package-v2/`.

![SELECT-CAL-02](package-v2/source.png)

## What changed and why

- Inward crop gauges on each edge at depths 2,4,8,12,16,24,32 input pixels; corner
  IDs A/B/C/D and the existing 672×1056-pixel reference spans remain.
- Three identical source groups at y=140,510,978: gray 128, 3-pixel black/white
  bars, and a 64/192 gray edge. Differences on paper can expose position-dependent
  output, but cannot alone distinguish thermal history, feed, or capture effects.
- A long gray strip at x=690..703 tests spatial uniformity/streaks/bands.
- Equal 80×80-pixel horizontal/vertical bar patches make directional comparisons
  less dependent on different patch shapes. Run widths are 1,2,3,4,6,8 pixels.
- Four controlled slanted edges, slope 0.1, two directions and two contrasts
  (0/255 and 64/192). Coverage is averaged from an 8× source grid. Measured results
  must be compared with the rasterized, decoded JPEG edge, not an ideal analog edge.
- Two moderate-contrast sine sweeps (0.025→0.45 cycles/input pixel), a 2-pixel
  checkerboard, and cyan/magenta/yellow edge-and-line samples.
- Continuous 0..255 ramp, dark steps 0/4/8/12/16/24/32/48, light steps
  207/223/231/239/243/247/251/255. These are signal values, not measured reflectance.
- Most on-sheet prose moved into documentation, leaving only identification and
  essential labels. Source pattern coordinates and formulas are in the generator
  and manifest. No native DPI or heater-count claim is encoded in the chart.

Crop/placement measurements can improve a driver's fill/fit behavior. Detail and
tone tests can reveal defects or motivate a controlled comparison. Position
variation, dot pitch and thermal explanations are equally legitimate curiosity
questions, but a single sheet cannot identify their causes uniquely. Repeated
capture of the same sheet is preferable to spending more paper to diagnose the
scanner/camera. Capture rotations should distinguish paper-fixed from capture-fixed
artifacts. Subsequent [photographs](PHOTO_ANALYSIS.md) permit preliminary geometry
analysis; calibrated physical measurements and rotated captures remain outstanding.

## Offline comparison

The existing permission-free Android harness rendered six cases (three input
routes × PhotoFix skipped/requested). Radio services remained disabled, no printer
client was instantiated, and the emulator was shut down afterward. All cases
matched full processData output and produced exact Python/Android bitmap matches.
All JPEGs match Python after removal of only the Android ICC APP2 segment.
PhotoFix-requested cases were unchanged for this chart, with SUCCESS diagnostic
native calls; this does not generalize to photographs.

Python JPEG is **117,204 bytes**; Android JPEG is 117,678 bytes. Pinned Python SHA:
`14e1530787508578341510cbdf827352a604d19b1b14039fc3cf785e26078206`.
Mean source-to-decoded-JPEG absolute channel difference is 0.335478 (0–255), maximum
116, with 13.129114% of pixels changed. Fine color edges are especially subject
to JPEG chroma subsampling. The retained line-patch metrics separate encoding
artifacts from future paper results. Repeated source patches are exactly equal;
JPEG block placement can still change their decoded edge pixels.

Reproduce from the repository root in the existing image-analysis environment:

```sh
python experiments/calibration/build_chart_v2.py
python experiments/calibration/compare_chart.py logs/android-runtime/calibration-v2/files/results-calibration-v2 --package experiments/calibration/package-v2
python experiments/calibration/verify_v2.py
```

## Bounded first-print sender

`first_print.py` is a separate experiment, not a general printing command. Default
invocation only verifies the pinned JPEG. The explicit `--execute-cal02-once`
argument enables the single operator-authorized attempt. It requires a fresh,
successful local two-transport probe snapshot at `logs/cal02-preflight.json`, then
rechecks exact device identity, idle state, empty queue, zero flags, unpaused
configuration, advertised commands/properties, sufficient battery, and page count.

Before PrintStart it durably creates an exclusive local attempt record. The
record is never automatically removed, including after failure. It binds the
exact payload hash and one copy. There is no arbitrary file/copy argument. Each
mutation requires a validated acknowledgement before the next is generated;
responses must preserve handle, offset, and total length. Unexpected replies,
protocol errors, or timeouts stop the attempt without resending. No automatic
resume, cancellation, reboot, settings mutation, or reconnect is implemented.

The prior Select capability snapshot advertises trigger action 2 (reboot), but
not action 1 (resume). Therefore the generic app's conditional resume behavior
must not be treated as an established requirement for this unit. This experiment
uploads the one job and observes it; it does not issue a trigger or clear pause.
The ordinary diagnostic transport allowlist remains unchanged.

Nine synthetic tests cover exact one-copy serialization and payload reconstruction,
wire framing, lost-start/chunk acknowledgements, malformed acknowledgements,
rejected starts, persistent attempt exclusion, pinned payload, preflight refusals,
and continued rejection of printing/resume by ordinary probe sessions. All 314
existing probe tests also passed. Private device identities and full frames stay
under ignored logs. Actual physical outcome is recorded separately after execution.

## Execution outcome

The authorized attempt has now run. The Select accepted job 12 and reported one
additional printed page (10→11), no calibration cycle, unchanged configuration,
and return to idle/empty. See [FIRST_PRINT.md](FIRST_PRINT.md) for timings, trace
audit and newly observed target events. Subsequent
[operator photographs](PHOTO_ANALYSIS.md) confirm physical output and provide
preliminary crop/detail observations. The persistent one-attempt record remains
in place.
