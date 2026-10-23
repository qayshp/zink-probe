# CAL-02: scale-pen photographs

2026-10-22. Two further photographs show the existing chart beside a metal pen
with a graduated face. They provide a rough physical scale check. No print,
device communication, configuration write, or driver change was made.

## Subsequent operator measurements

The operator clarified the physical dimensions as **approximately 58×87 mm for
the paper and 53×83 mm between the printed reference lines**. These values
supersede the earlier conflicting inch fractions. They are approximate reports,
with no stated uncertainty or separate readings for the two opposite sides.
The photo-only pen estimates below remain historical evidence rather than the
preferred physical-scale estimate.

The known reference spans are 672 input pixels across the short dimension and
1056 along the long dimension. Therefore:

| Quantity | Short dimension, x | Long dimension, y |
| --- | ---: | ---: |
| Reported paper dimension | ~58 mm | ~87 mm |
| Reported printed reference span | ~53 mm | ~83 mm |
| Reference span in the input image | 672 px | 1056 px |
| Calculated input-image scale | ~322 pixels/inch | ~323 pixels/inch |
| Physical size corresponding to one input pixel | ~0.079 mm | ~0.079 mm |
| Extrapolated full 768×1152 image size | ~60.6 mm | ~90.5 mm |
| Approximate input span fitting on the paper | ~735 px | ~1107 px |
| Total input pixels beyond the paper, both edges combined | ~33 px | ~45 px |
| Fraction of input dimension outside the paper | ~4.2% | ~3.9% |

For example, `672 / 53 * 25.4 = 322.05` input pixels per inch across, and
`1056 / 83 * 25.4 = 323.16` along. The difference is only about 0.34%, smaller
than these approximate measurements can reliably resolve. The results support
nearly equal physical scaling of the input raster in both directions. They do
not establish a precise anisotropic stretch requiring correction.

Extrapolating the frame's scale to the whole image assumes approximately uniform
scaling. The resulting visible span, about 735×1107 input pixels, closely agrees
with the earlier photograph-based estimate of roughly 736×1107. This strengthens
the evidence for about 4% total loss in each input dimension on this sheet. The
four physical dimensions alone cannot locate that loss between opposing edges;
the earlier left/right/top/bottom asymmetry remains photo-derived.

**Driver implication:** preserve the validated 768×1152 target and record the
observed physical placement separately. A future fit/safe-area option could
compensate for this apparent overfill; no correction is enabled from this one
sheet. The roughly 79-micrometre input-pixel footprint describes image scale on
paper, not physical heater spacing. Native DPI, element count, and how the
firmware maps the image to its physical marking process remain unresolved.

The clarified inputs, formulas and full arithmetic are retained in
[operator-measurements.json](package-v2/operator-measurements.json). The existing
blank measurement worksheet remains a template; unreported opposite-side spans,
corner offsets, feed timing and uncertainty have not been filled by assumption.

## Reading the scale

After rotating an inspection crop for legibility, I read the visible end marking
as a **1:300 scale with metre units**. This is an architectural scale: label 10
represents ten metres at 1:300, so its physical distance from label 0 is
`10,000 / 300 = 33.333... mm`. The 0–20 interval is 66.667 mm. These labels should
not be read directly as ordinary centimetres or millimetres. This interpretation
comes from the photograph; the pen's exact model and manufacturing accuracy have
not been established.

## What can be estimated

The following estimates were made from the oblique photographs before the
operator supplied the physical dimensions above.

Using manual picks of the 0, 10 and 20 tick positions, a one-dimensional
projective fit accounts for changing spacing along the ruler. Transferring that
mapping approximately to the paper edge nearest the pen gives:

| Capture | Calculated apparent long-edge length | Appropriate reported precision |
| --- | ---: | --- |
| Photo 1 | 86.86 mm | Roughly 87 mm |
| Photo 2 | 87.87 mm | Roughly 88 mm |

This is consistent at a rough level with HP's nominal **87 mm** sheet length.
HP specifies the Select media as 5.8×8.7 cm, also marketed as 2.3×3.4 inches:
[HP Select datasheet](https://press.hp.com/content/dam/hpi/press/press-kits/2019/hp-expands-sprocket-portfolio/gallery/HPSprocket-Select-Photo-Printer-DataSheet.pdf).
The comparison does not establish the actual cut length to a fraction of a
millimeter. The short side is not independently measured in this calculation.

Both views are strongly oblique, and the scale is on the raised pen surface while
the paper lies lower. A projective correction for one plane cannot simply remove
parallax between two different planes of unknown separation. The calculation
uses x coordinates along roughly parallel image directions; it is not a full
camera/plane reconstruction. The observed difference between the captures is not
a calibrated error bar, and averaging them would not remove systematic bias.

The attachments are 1280×960 pixels. They show the sheet sideways relative to the
earlier close-ups, but the shallow angle heavily compresses one paper axis and
there is glare. They therefore do not provide a clean rotated fine-detail control.
No native-resolution, heater-count, or contrast measurement is inferred here.
Earlier crop estimates and the driver preparation remain unchanged.

## More useful capture with this same reference

The pen can serve as the reference; no additional purchase or print is needed.
Place it beside the flat sheet with the chosen scale facing the camera and take
a photograph from directly above, with the whole sheet and scale visible. Keep
the phone parallel to the supporting surface and avoid grazing light/glare.
A modest camera distance reduces the relative effect of the pen's height; the
height difference still prevents treating the result as precision metrology.
If the pen has an ordinary mm/cm face, that would simplify reading, but the
visible 1:300 face is usable with the conversion above.

## Evidence

Private originals and inspection crops are under ignored
`logs/calibration-photos/scale-pen/`. Public
[scale-pen-analysis.json](package-v2/scale-pen-analysis.json) contains photo hashes,
manual x-coordinate picks, the scale interpretation, and calculated values. It
contains no original photographs or camera/location metadata.

```sh
python experiments/calibration/analyze_scale_pen.py
```

The script reproduces the arithmetic from the recorded picks without needing the
private photos. Those picks and the plane approximation, rather than numerical
precision, limit the measurement. The displayed decimal values are retained
only to make the computation reproducible.

Validation: both private photo hashes and dimensions, the unchanged payload hash,
and reproducibility of the recorded results passed. An independent synthetic
projective mapping checked interpolation beyond the three fitted ticks. Lint and
format checks passed. These validate arithmetic and provenance, not the physical
plane approximation.
