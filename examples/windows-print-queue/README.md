# Windows spooler capture examples

**A subsequent real photo has now printed successfully through the Windows
queue.** See the [first physical print report](FIRST_PRINT.md). The images below
remain paper-free capture tests, separate from that user-confirmed print.

These images were rendered by Windows' **Microsoft IPP Class Driver** on an
ARM64 Surface, received by the local PAPPL queue as 1370 × 2055 sRGB raster,
and prepared by the Python worker at 768 × 1152, JPEG quality 90 / 4:2:0.
The PNGs below are decoded JPEG previews. **No paper was printed.** The capture
configuration contained no printer credentials and never constructed Bluetooth.

The small dimension labels use Windows PrintDocument's hundredths of an inch
(228 × 343 portrait, 343 × 228 landscape), not pixels. The media itself is
advertised as 58 × 87 mm. Landscape content is correctly rotated within the
fixed portrait-shaped printer payload.

| Portrait document | Landscape document on the same paper |
| --- | --- |
| ![Captured portrait page](portrait.png) | ![Captured landscape page](landscape-on-paper.png) |

[`Validate-CaptureQueue.ps1`](../../native/Validate-CaptureQueue.ps1) generated
these synthetic pages through the Windows spooler. It also submitted a two-page
document **to the capture queue**; the native driver rejected that complete job
before invoking the worker, so there was no partial first-page dispatch.

See the [installation and operation guide](../../WINDOWS_PRINT_QUEUE.md) and
[sanitized validation record](validation-2026-10-25.json). Raw device identifiers,
protocol traces, local configuration and spool logs remain private.

## Successful read-only hardware follow-up

After the user said they would wake the printer, the installed Windows queue's
Python environment completed **two fresh Bluetooth connections** at
2026-10-25 17:43 UTC. Both matched the expected Select identity and firmware
`G1L1FA2105AR`, reported idle/empty with 100% battery and charging, and closed
without error. The printed-page counter remained 12 and calibration counter 2;
configuration was unchanged within and between the two checks.

The [sanitized frame audit](read-only-followup-2026-10-25.json) independently
validated all 70 outgoing requests as read-only and correlated all 70 replies.
It also checked complete frame boundaries, dynamically granted capability-read
handles, and byte counts against the native socket counters: 532 bytes sent and
1,740 received in total, excluding Bluetooth overhead. No printing, image upload,
settings write, reset or cancellation command was sent. The live Windows queue
and worker directories remained empty, and its background task remained running.

This supersedes the earlier timeout as the latest communication result. It does
not establish the cause of that timeout, provide continuous readiness monitoring,
or validate a physical sheet through the Windows queue. No code, pairing or
permission change was required for this successful follow-up.
