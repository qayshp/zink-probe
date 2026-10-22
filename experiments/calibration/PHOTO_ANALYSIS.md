# CAL-02: first photographs of the physical output

2026-10-22. The operator supplied two 2880×3840 photographs after the authorized
first print. They show the CAL-02 layout on paper, upright and readable, with no
gross rotation, mirroring, missing interior panel, or obvious transfer corruption.
This adds direct visual evidence to the [job trace and page counter](FIRST_PRINT.md).
Treat these as two captures of the first sheet, not independent print repetitions.
No additional device connection, print, configuration change, or Android run was
needed for this analysis. The previously validated payload remains unchanged.

Original photographs and local inspection figures remain in ignored
`logs/calibration-photos/`. Public evidence consists of manually picked coordinates,
photo hashes, reproducible geometry calculations, and these qualified findings.
Camera/location metadata is not included.

**Follow-up:** four [closer photographs](CLOSEUP_ANALYSIS.md) now reveal faint
one-pixel vertical structure at approximately the expected period. The original
wide-view impression of an almost solid patch should be read as low captured
contrast, not proof that the pattern was erased. Geometry estimates below are
unchanged; the close-ups add detail rather than independent whole-sheet geometry.

## Geometry: real content loss near the paper edges

Both photographs retain the four reference crosses and center cross. Several
outer crop gauges and the perimeter ticks are absent. The top and right edges
show the deeper three gauges, the left shows two, and no bottom gauge is clearly
retained. This agrees with the geometric estimate below: approximately the
16/24/32-pixel gauges survive at top/right, 24/32 at left, and the deepest bottom
gauge at 32 pixels lies at or beyond the paper boundary. Visibility of a very
fine mark near a blurred edge is not an exact threshold measurement.

Four corner crosses at source coordinates (48,48), (720,48), (48,1104), (720,1104)
define a projective transformation from each photograph to the input image.
Independent picks on the paper boundaries then estimate how much of that input
falls outside the photographed sheet. No assumption about physical paper size or
printer DPI is needed for this source-coordinate calculation.

| Apparent missing depth, input pixels | Photo 1 | Photo 2 | Working interpretation |
| --- | ---: | ---: | --- |
| Left | 19.6 | 20.5 | About 20 px |
| Right | 12.6 | 12.0 | About 12 px |
| Top | 10.9 | 12.4 | About 12 px |
| Bottom | 33.2 | 32.6 | About 33 px |

These are approximate, with uncertainty of several input pixels rather than the
decimal precision shown for reproducibility. The fit assumes a flat sheet and
projective camera geometry; lens distortion, paper curl, blurred edges, and manual
coordinate selection are not calibrated. The withheld center cross lands within
0.28 and 1.58 input pixels of its expected position in photos 1 and 2 respectively.
That is a useful independent interior check, not an accuracy guarantee everywhere.

The approximate visible source window is **x=20..756, y=12..1119**, or roughly
**736×1107 input pixels**. About 96% of each input dimension is visible. The
off-center placement and clipped gauges are consistent with overscan and print
registration; this experiment does not identify the firmware's exact scaling,
offset, edge masking, or their repeatability on other sheets and units.

**Driver consequence:** model image placement separately from JPEG preparation.
A future fit mode should support a measured safe content area, while a fill mode
can deliberately allow edge loss. The existing 48-pixel-inset reference frame
survives on this sheet. Do not hard-code these four offsets as a universal Select
profile or change the submitted 768×1152 dimensions on this evidence alone.

## Fine detail: a large directional difference, with capture artifacts

Both photos show the one-input-pixel **vertical** bars as an almost solid dark
patch. One-input-pixel **horizontal** bars still show distinct horizontal
structure. Vertical bars vary across x; horizontal bars vary across y. Two-pixel
vertical bars and the coarser patches retain visibly more structure.

The decoded JPEG that was actually transmitted preserves both one-pixel patterns:
each central 64×64 patch spans 0..255 and has mean channel value 127.5. Offline
Python/Android comparison already established matching decoded payload pixels.
Consequently, the severe darkening of the vertical patch is not explained by the
Python image preparation or disappearance of the pattern during JPEG encoding.
It arises later in the printer/output/capture chain.

At two-pixel horizontal runs, the fine texture differs visibly between captures:
photo 1 has a conspicuous dotted/rippled appearance, while photo 2 has smoother
segments and a different fine texture. Thus at least part of that apparent micro
structure depends on capture conditions. The photos have similar orientation,
so they do not isolate printer-axis behavior from camera-axis behavior.

Possible contributors to the directional loss include firmware resampling,
physical spreading of dark regions, the print process's nonlinear tone response,
and camera focus/sampling/processing. These images do not distinguish their
contributions. Neither a native resolution nor a heater count follows from the
last visibly separated line pair. In particular, the approximately 736 visible
**input columns** from the geometry calculation are not a measurement of 736
physical heating elements. The earlier 768×1152 versus advertised DPI question
remains open at the hardware level.

**Driver consequence:** retain the validated raster dimensions and preparation
baseline. Do not add directional sharpening, change resolution, or promise
one-pixel detail based on this capture. A controlled capture of this same sheet
can determine whether the strong directional difference follows the paper.

## Tone, color, and repeated controls

Nominally neutral gray patches look mauve/purple, while the dark gray areas look
blue-purple. The ramp has a visible color excursion, and many of the darkest and
lightest steps are difficult to distinguish in these photos. The A/B/C gray patches
also differ in apparent brightness or tint. The repeated source patches were
identical; their decoded JPEGs are the appropriate digital baseline for any later
measurement because JPEG block placement can affect edges.

The paper itself shows uneven illumination and differs between captures. There
is no calibrated gray/color reference or fixed exposure/white balance record.
These observations are reasons to investigate neutrality, highlight/shadow
compression, and spatial uniformity, but not measurements of printed color error,
thermal drift, paper sensitivity, or a defective heater. The long strip does not
by itself identify a physical defect. PhotoFix was off in the submitted payload.

**Driver consequence:** no color correction curve or profile is justified yet.
Such a correction could otherwise compensate for the camera or lighting and
make actual prints worse. Color management is a separate experiment from geometry.

## Most useful next evidence: recapture this sheet

No additional print is required. Close-ups have now been supplied and analyzed
in [the follow-up](CLOSEUP_ANALYSIS.md). The controlled capture rotation and
physical-scale measurements below remain outstanding:

1. For a controlled follow-up to the close-ups, keep the sheet flat with even
   diffuse light and sharp focus. Rotate the **sheet** 90 degrees while
   keeping the camera orientation and capture conditions as similar as possible.
   This exchanges the printed axes relative to the sensor; digital image rotation
   after capture cannot provide this control. Preserve full-resolution originals.
2. For geometry, measure the physical A–B span (672 input pixels), A–C span
   (1056 input pixels), and paper width/height with an appropriate ruler or
   caliper. A flat capture with a ruler in the same plane is also useful. These
   give input-pixel placement in mm and effective input pixels/inch, not the
   number of heating elements.
3. If available, scan the same sheet at the scanner's genuine optical resolution,
   preferably 1200 ppi or higher, without automatic sharpening, contrast, color
   enhancement, or resampling; retain a lossless file. Scan again with the sheet
   physically rotated 90 degrees to check the scanner's own directional effects.
   A claimed scan setting alone does not establish optical resolving power.

Static photos cannot recover paper-feed velocity, the exact first/last instant
of paper movement, which edge emerged first, or charging-cable continuity during
the earlier job. The recorded protocol time is still not a feed-speed measurement.

## Reproduction and verification

Using the same Pillow/NumPy environment as the renderer:

```sh
python experiments/calibration/analyze_photo_geometry.py
# Optional: verify the private originals match the recorded hashes/dimensions.
python experiments/calibration/analyze_photo_geometry.py --photo-dir logs/calibration-photos
```

Inputs: [photo-landmarks.json](package-v2/photo-landmarks.json), the unchanged
[manifest](package-v2/manifest.json), and [transmitted JPEG](package-v2/python.jpg).
Output: [photo-geometry.json](package-v2/photo-geometry.json). The script verifies
the payload hash, corner mapping, and JPEG baseline; the independent center
residuals are reported rather than folded into the fit. It reads no Bluetooth
interfaces and changes no printer settings. All derived quantities remain in
input pixels or percentages; there is no unsupported mm, DPI, MTF, color-profile,
heater-count, or feed-speed estimate.

Validation: the private-original hash/dimension checks passed; results with and
without those optional files were identical. A synthetic known projective map
and independent interior points verified the transform/inverse arithmetic. The
existing CAL-02 verifier again passed payload/image hashes, source repeat equality,
patch bounds, crop gauges, and all six retained Android comparisons. Lint and
format checks passed. No rendering or transport implementation was changed.
