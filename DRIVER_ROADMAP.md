# Proposed path to a Select driver for macOS, Linux and Windows

2026-10-22. This is a proposal, not a claim of cross-platform support. One Select
unit and one CAL-02 print have been physically validated on macOS. The normal CLI
is explicitly gated to macOS; RFCOMM uses PyObjC/IOBluetooth and pumps the native
run loop. The existing portable pieces are protocol parsing, much of the probe
logic, and the offline image-preparation experiment. Family-wide compatibility
remains outside the first shipping target.

## Highest-return next milestone: a portable single-job engine

Extract the tested message construction, acknowledgement checks and finite job
state from `experiments/calibration/first_print.py` into an OS-independent library.
Retain the completed experiment and its persistent attempt record unchanged.
Introduce a small transport interface around connection, framed request/reply,
asynchronous events, timeout and close behavior. Keep policy separate from native
I/O so ordinary diagnostics remain read-only and printing is an explicit path.

The first deliverable should run entirely against a simulated printer on all
three operating systems. Cover stream fragmentation/coalescing, interleaved
events, invalid handles/offsets, lost acknowledgements, disconnects and completion
that cannot be confirmed. Test job bytes against sanitized evidence from the
successful print. An upload-complete reply must not be equated with physical
completion. An ambiguous outcome must never cause an automatic resubmission.
Durable local job identity and an uncertainty state are more useful than promising
exactly-once printing that the protocol cannot guarantee after a lost reply.

Acceptance criteria:

- macOS/Linux/Windows CI can import and exercise the core without Bluetooth
  hardware or native macOS modules; share the same protocol golden fixtures.
- Simulated printing reconstructs the requested payload and copy count exactly,
  validates each acknowledgement, and records accepted/uploaded/printing/completed
  or uncertain states without inventing progress percentages.
- Timeout/disconnection tests preserve enough state for later read-only status
  reconciliation and never silently resend a potentially accepted job.
- The existing diagnostic allowlist and completed CAL-02 experiment retain their
  behavior. Vendor APKs/native libraries are not runtime dependencies.

This work needs no paper. It converts a successful one-off experiment into a
maintainable implementation before adding another operating system's I/O.

## Transport adapters and physical validation

| Platform | Proposed route | Required evidence |
| --- | --- | --- |
| macOS | Adapt the existing IOBluetooth RFCOMM implementation to the interface | Existing diagnostics still work; event-loop and timeout behavior remain explicit. |
| Linux | Prototype BlueZ discovery/pairing integration and an RFCOMM byte stream | Physical read-only identity/status, clean disconnect and reconnection; no assumption that macOS identifiers or pairing behavior transfer. |
| Windows | Prototype a narrow native Bluetooth socket adapter, or an equivalent verified Windows RFCOMM API | Physical read-only identity/status and failure reporting on a supported Windows host. |

[BlueZ's Profile API](https://bluez.readthedocs.io/en/latest/profile-api/) documents
RFCOMM channel/client integration and connection delivery.
[Microsoft's Bluetooth Winsock documentation](https://learn.microsoft.com/en-us/windows/win32/bluetooth/bluetooth-programming-with-windows-sockets)
provides a supported Windows route. These are candidate adapter foundations,
not evidence that this printer has been tested there.

[Bleak](https://bleak.readthedocs.io/en/latest/) already offers BLE GATT backends
for these platforms and may be retained for discovery/diagnostics. It is not an
RFCOMM transport. The macOS BLE UUID must not become the portable device identity;
use platform discovery identifiers plus verified protocol identity and the
protocol-reported Classic address. Retain the successfully tested Classic upload
path; do not make unvalidated BLE bulk printing a prerequisite for portability.

Most adapter validation can be read-only. Once an adapter passes that stage,
physical printing is still a separate end-to-end acceptance test, with one
explicitly authorized job and no automatic retry. Simulator/CI success does not
establish Bluetooth or physical print compatibility.

## User-facing preparation and printing

Promote the offline preparation code into a public API/CLI with explicit EXIF
orientation, transparency compositing, input color-space handling, preview and
fit/fill choices. The current `prepare.py` intentionally assumes an already
oriented/edited sRGB input, so it is not yet a complete arbitrary-photo pipeline.
Keep the measured Select crop as a provisional profile with an optional safe-area
mode; do not hard-code one sheet's offsets as universal mechanical correction.
Retain image fixtures and recorded encoder versions across operating systems.

Expose discovery, status, offline prepare/preview, and explicit single-job print
as separate operations. Add useful error/status reporting before a GUI. Thermal
precompensation is optional research and should not block basic printing or be
enabled from one photographed chart.

## OS print queues and later integration

After the shared engine and transport adapters are proven, add a spooler/service
front end so ordinary applications can reach it through an OS print queue or IPP.
PAPPL remains a later integration target, with host/platform suitability checked
at that milestone. Queue integration should translate documents/jobs into the
same preparation and submission interfaces, not duplicate protocol logic.

CAL-03 can run in parallel as a bounded image-quality experiment. The recommended
next engineering task is the portable job engine plus simulated-printer test
suite and three-OS CI, followed by read-only Linux/Windows adapter validation.
