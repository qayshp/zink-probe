# CAL-02: directional contrast and possible thermal interactions

2026-10-22. A further operator close-up shows the existing sheet's 4/6/8-input-pixel
black/white bars. The vertical gaps appear more cyan and less white than the
horizontal gaps. Cyan fringes are also visible around black edges. This supports
investigating a direction-dependent response, but does not identify its cause.
No additional print, device connection, setting change, or rendering was performed.

## What the transmitted image establishes

The pinned JPEG remains SHA-256
`14e1530787508578341510cbdf827352a604d19b1b14039fc3cf785e26078206`.
Its central 64×64-pixel samples of all six relevant patches have exactly equal
R, G and B values at every pixel. All six reach 0 and 255. Matching orientations
have identical minimum, maximum and mean values. After transposing the horizontal
sample, the largest difference from its vertical counterpart is 0 code values
for 4-pixel runs and 2 for 6- and 8-pixel runs. The transmitted pattern therefore
does not contain the observed cyan fringe or a substantial directional contrast
difference. This check does not exclude firmware decoding, resampling or color
processing downstream.

[contrast-source-check.json](package-v2/contrast-source-check.json) records the
exact sampling boxes, results and photo hash. The original 2880×3840 photo is
retained only in ignored `logs/calibration-photos/contrast-closeup/1-Photo-1.jpg`;
its SHA-256 is
`7b4c07588206d3a10354740e28c7e526e7bd0e5ca238d60e0f243e59dc532f49`.
No camera/location metadata or original photograph is published.

The earlier [close-up analysis](CLOSEUP_ANALYSIS.md) already found weaker captured
modulation in the one-pixel vertical pattern. The present observation extends
the question to the hue and brightness of wider gaps. It is a visual assessment,
not a calibrated reflectance, contrast, or physical color-layer measurement.

## Mechanisms worth distinguishing

| Candidate | Discriminating observation to seek |
| --- | --- |
| Residual heat from earlier printing by the same heater | An asymmetric trail after a dark region, aligned with known paper travel; a dependence on the preceding image and recovery after blank space. |
| Heat spreading between adjacent heaters or through the medium | Stronger filling of narrow gaps between neighboring dark tracks; isolated lines differing from closely spaced lines. |
| Interactions among the heat pulses used to develop different colors | Different edge/gap behavior for otherwise matched requested C/M/Y, composite colors and black. |
| Firmware resampling, spatial filtering, or unequal physical sampling along the two axes | A stable directional response that depends on pattern frequency or phase; this can coexist with thermal effects. |
| Camera optics/processing and lighting | Fringe or contrast behavior that changes with a controlled paper rotation relative to the sensor, focus, exposure or illumination. |

These are candidate signatures, not exclusive diagnostic rules. For example,
color-dependent blur could arise in the camera as well as the printer.

General thermal-printing literature explicitly distinguishes residual heat
affecting succeeding rows from lateral heat sharing that reduces fine-detail
contrast: see the background of Codonics'
[US8063925B2, *Thermal or density management of imaging device*](https://patents.google.com/patent/US8063925B2/en).
That patent is not a description of this Select's implementation.

If paper travel is along the chart's long axis, vertical bars repeatedly energize
the same neighboring tracks, while horizontal bars repeatedly switch a given
heater between dark and light. Under that assumption, the stronger vertical loss
fits lateral interaction more directly than a simple residual-heat trail alone.
The physical feed mapping/first edge was not recorded, so this remains conditional.

ZINK's own
[US20120218367A1, *Thermal Response Correction System for Multicolor Printing*](https://patents.google.com/patent/US20120218367A1/en)
describes compensation for both printhead thermal history and heating of the
medium by other colors within a line. Brian Busch of Zink Holdings also describes
color-specific temperature sensitivity and interactions between color energies
in *Temperature Control for Direct Thermal, Three Color, Single-Pass Imaging*,
[Printing for Fabrication 2019, program pp. xvii–xviii](https://www.imaging.org/common/uploaded%20files/pdfs/Conferences/Print4Fab/2019/Printing%20for%20Fabrication%202019%20Technical%20Program%20and%20Abstracts%20WEB.pdf).
That abstract reports dependence on print speed, line density and pulse pattern.
These primary sources make the thermal hypothesis credible; they do not establish
which compensation or residual errors this Select has.

## Why requested-color controls would help

Black in a CMY medium combines color formation. Repeating identical geometry in
cyan, magenta and yellow is consequently a useful comparison, but our RGB JPEG
interface does not directly command individual dye layers or heater pulses.
Firmware color conversion may mix colorants even for a nominal RGB primary or
secondary. A requested cyan patch is a requested-color control, not a verified
cyan-only thermal exposure. Fewer requested colorants also do not establish a
simple ordering of pulse temperature, duration or total heat.

The existing chart's isolated two-pixel C/M/Y lines survived visibly. They are
not matched dense bar patterns, so they cannot answer whether the same contrast
loss occurs in each color. A blue/cyan-looking fringe alone also does not identify
one malfunctioning or overdeveloped dye layer.

For a future, separately authorized sheet, the highest-value comparisons would be:

1. Identical horizontal and vertical bar geometry in black, gray and requested
   C/M/Y, with local white references. Compare edge width and gap contamination
   relative to each color's solid patch and nearby white, rather than comparing
   raw brightness contrast across colors; yellow naturally has low brightness
   contrast against white.
2. Isolated bars versus dense bars, plus fixed-width bars separated by several
   gap widths. This separates line width from neighboring coverage better than
   changing black and white run widths together.
3. Identical test regions preceded by a solid dark patch or white space, using
   several blank separations and a recorded feed direction. This tests a history
   effect more directly than orientation alone.
4. Repeated controls at different positions. A stable pattern-dependent result
   should be distinguished from page-position, illumination or warm-up changes.

Before spending another sheet, a controlled 90-degree paper rotation under the
same camera setup would help determine whether the existing directional effect
follows the paper. Keep the physical rotation documented; auto-rotation of the
saved image is not evidence of sensor-relative orientation.

## Driver consequence

Retain the existing raster preparation. Neither blanket sharpening nor a fixed
color correction follows from these photos. If repeatable color- and
direction-dependent behavior is established, optional image preprocessing could
be evaluated against real output. We have no validated command for changing
per-heater timing, temperature or thermal-history compensation. For now this is
an evidence-backed experimental direction, not a firmware diagnosis or driver fix.

## Reproducing the source check

Using Pillow and NumPy, decode `package-v2/python.jpg` as RGB. For 4/6/8-pixel runs,
the 80×80-pixel patch origins are x=378/480/582 and y=232 (vertical) or 362
(horizontal). Sample offsets `[8:72, 8:72]`. For each sample compute per-pixel
`max(R,G,B) - min(R,G,B)`, global minimum/maximum/mean, and the maximum absolute
difference between the vertical sample and the transposed horizontal sample.
Cast to a signed integer type before subtraction. The JSON stores exclusive
rectangle endpoints and all outputs; no image processing is applied to the photo.
