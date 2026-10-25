# First physical Windows queue print — 2026-10-25

The user submitted one photograph from Surface's normal Windows print dialog to
**HP Sprocket Select**, then confirmed that the sheet emerged and matched the
preview closely, with a little more cropping at the edges. This is the first
physical acceptance evidence for the Windows queue, portable job engine and
Windows RFCOMM adapter together. The photo and its image-bearing protocol trace
remain private; only [sanitized metadata](first-physical-print-2026-10-25.json) is
published. No additional print or device command was sent to collect this report.

## Recorded transaction

| Evidence | Result |
| --- | --- |
| Windows-rendered page | 1370 × 2055, sRGB |
| Selected IPP quality | High (`5`) |
| JPEG | 768 × 1152, quality 100, 4:4:4, baseline, optimized Huffman |
| JPEG length / acknowledged payload | 777,668 / 777,668 bytes |
| Copies / PrintStart requests | 1 / 1 |
| Upload chunks / correlated request-reply pairs | 780 / 920 |
| Engine completion | `completed`; upload acknowledged; printing observed |
| Printed-page counter | 12 → 13 |
| Calibration counter | 2 → 2 |
| Final protocol state | Idle, empty queue, zero flags |
| Error / pending request / socket-close error | None |
| Physical sheet | Confirmed by the user |

The independent trace pass correlated all 920 replies, with four separate events
and no trailing partial frame or pending request. The engine's original upload
checks validate handle, absolute acknowledged byte offset and advertised total
for every chunk. There was one allocation and no retry.

Journal timing was approximately **54.48 seconds from claim to upload
acknowledgement**, followed by **60.07 seconds to protocol completion**, for
**114.55 seconds total**. These are host observations with polling intervals,
not camera-measured paper-feed or physical ejection times. The original worker's
`physical_ejection_confirmed: false` remains untouched: the engine cannot itself
verify ejection. The user's physical confirmation is recorded separately.

## Cropping observation and driver consequence

The Windows raster and outgoing JPEG have exactly the same 2:3 aspect ratio.
The preparation manifest's source crop box is effectively
`[0, 0, 1370, 2055]`; its approximately `1e-13` left coordinate is floating-point
rounding. There was no padding and no meaningful crop added by the Python
preparation stage. This does not independently verify what the application drew
in its own preview before Windows rendered the page.

The reported additional edge loss is consistent with the
[CAL-02 geometry evidence](../../experiments/calibration/PHOTO_ANALYSIS.md#geometry-real-content-loss-near-the-paper-edges):
the printer's visible source region was smaller than the submitted image and
not perfectly centered. A digital preview of the complete submitted rectangle
does not yet simulate those physical boundaries. This photograph supplies a
qualitative repeat observation, not new per-edge measurements or proof of the
firmware's exact scaling/offset mechanism.

A useful future driver option is an explicit **preserve edges / safe area** mode
that insets content, plus an approximate physical-edge overlay in the preview.
Borderless fill and content preservation should remain separate choices. Do not
silently apply the first calibration sheet's asymmetric offsets to all photos,
units or paper packs. The submitted image dimensions remain 768 × 1152.

This successful single job does not validate paper-out, interrupted upload,
cancellation during printing, every application, or native macOS/Linux queues.
It establishes the basic requested Windows File → Print path on this Select.
