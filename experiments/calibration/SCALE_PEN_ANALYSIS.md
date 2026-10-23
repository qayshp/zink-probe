# CAL-02: scale-pen photographs

2026-10-22. Two further photographs show the existing chart beside a metal pen
with a graduated face. They provide a rough physical scale check. No print,
device communication, configuration write, or driver change was made.

## Reading the scale

After rotating an inspection crop for legibility, I read the visible end marking
as a **1:300 scale with metre units**. This is an architectural scale: label 10
represents ten metres at 1:300, so its physical distance from label 0 is
`10,000 / 300 = 33.333... mm`. The 0–20 interval is 66.667 mm. These labels should
not be read directly as ordinary centimetres or millimetres. This interpretation
comes from the photograph; the pen's exact model and manufacturing accuracy have
not been established.

## What can be estimated

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
