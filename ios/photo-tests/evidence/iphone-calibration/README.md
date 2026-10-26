# Physical iPhone JPEG exports, 2026-10-26

User supplied six JPEG files exported from the build-5 offline preparation flow,
using the original CAL-02/CAL-03 PNGs and named quality settings 90/95/100.
The names identify the selected quality; JPEG headers independently establish
sampling, dimensions and quantization. Original attachments remain private;
SHA-256 fingerprints and numeric results are in results.json.

All are 768 x 1152, non-progressive, and declare EXIF sRGB. Quality 90 and 95
use 4:2:0. Quality 100 uses 4:4:4 and all-one luminance/chroma quantization tables.
This is actual iPhone-export evidence, not a universal guarantee for Apple APIs.

| Chart | Quality | Bytes | Sampling | Mean absolute RGB error | Maximum channel error |
| --- | ---: | ---: | --- | ---: | ---: |
| CAL-02 | 90 | 172589 | 4:2:0 | 0.183762 | 126 |
| CAL-02 | 95 | 178587 | 4:2:0 | 0.163559 | 125 |
| CAL-02 | 100 | 241366 | 4:4:4 | 0.018877 | 3 |
| CAL-03 | 90 | 140951 | 4:2:0 | 2.111030 | 164 |
| CAL-03 | 95 | 145528 | 4:2:0 | 2.086742 | 164 |
| CAL-03 | 100 | 222967 | 4:4:4 | 0.041269 | 4 |

Method: Pillow JPEG get_sampling/layer/quantization/header inspection; decode RGB,
compare directly against experiments/calibration/package-v2/source.png and
package-v3/source.png using ImageChops.difference and ImageStat. Mean absolute
error averages all pixels and RGB channels, on a 0–255 scale. PSNR in results.json
uses mean squared channel error. No rescaling or registration was applied. These
metrics include the complete preparation/export/decode path, not isolated JPEG
quantization. High-frequency synthetic charts are not representative natural photos.

For CAL-03, q100 adds 82016 bytes (58.2%) over q90. For CAL-02 it adds 68777
bytes (39.8%). Transfer time was not measured and no images were printed. The
large improvement at q100 coincides with both removal of chroma subsampling and
finer quantization, so these files alone do not isolate either contribution.
The remaining q100 errors establish that it is not pixel-lossless.
