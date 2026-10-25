# Path to a Select driver for macOS, Linux and Windows

Updated 2026-10-25. The [portable job engine and simulator](PORTABLE_JOB_ENGINE.md)
are implemented with three-OS CI. One Select has physical communication evidence
on macOS and two successful calibration sheets, CAL-02 and CAL-03. Native
One [Windows queue photo](examples/windows-print-queue/FIRST_PRINT.md) has now
printed through the portable engine at quality 100 / 4:4:4. Linux physical
printing remains unvalidated. The original diagnostic CLI is gated
to macOS; its RFCOMM implementation uses PyObjC/IOBluetooth and pumps the native
run loop. Family-wide compatibility remains outside the first shipping target.

The new engine's [macOS adapter](experiments/macos-adapter/README.md) is implemented
and validated with read-only identity/status/capability/configuration/counter
checks across fresh connections. Simulated full jobs traverse the same adapter
with a fake native callback backend. Actual printing through this adapter and
the portable engine together is still a separate, unperformed acceptance test.

## Implemented milestone: a portable single-job engine

The new `zink_probe.jobs` library carries the tested message construction,
acknowledgement checks and finite job states into an OS-independent implementation.
The completed CAL-02 sender and claim remain unchanged. A small asynchronous
byte-stream interface supports framing, events, deadlines and cleanup. Policy
is separate from native I/O; ordinary diagnostics remain read-only.

The deliverable runs against a simulated printer, covering fragmentation,
coalesced events, invalid handles/offsets, lost replies, interruption, and uncertain
completion. Golden tests include every successful CAL-03 upload acknowledgement.
SQLite claims prevent replaying the same local job or creating a new claim for
the same device while an earlier claim is unresolved. This does not promise
exactly-once printing across independent journals, computers or lost replies.

Implemented checks (runner results are linked from the engine documentation):

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
| macOS | Implemented async IOBluetooth RFCOMM stream with a read-only diagnostic command | Real read-only checks passed; full jobs and faults pass through a simulated native facade. Physical printing through the new engine remains untested. |
| Linux | Implemented nonblocking RFCOMM socket stream with read-only BlueZ preflight | Real-socket simulated jobs, ARM64 host tests and two read-only Select connections pass; see the [evidence](experiments/linux-adapter/README.md). Physical printing through this adapter remains untested. |
| Windows | Implemented nonblocking Winsock RFCOMM stream with cached pairing preflight | Simulated jobs, ARM64 Windows tests, real read-only connections and one [user-confirmed photo through the Windows queue](examples/windows-print-queue/FIRST_PRINT.md) pass. Physical fault/cancellation cases remain untested. |

[BlueZ's Profile API](https://bluez.readthedocs.io/en/latest/profile-api/) documents
RFCOMM channel/client integration and connection delivery.
[Microsoft's Bluetooth Winsock documentation](https://learn.microsoft.com/en-us/windows/win32/bluetooth/bluetooth-programming-with-windows-sockets)
provides the implemented Windows route. Native interface availability and
simulated jobs do not by themselves establish physical printer compatibility.

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

The [public image-preparation API/CLI](IMAGE_PREPARATION.md) is now implemented
with EXIF orientation, ICC-to-sRGB conversion, transparency compositing, fit/fill
previews, JPEG quality/sampling options and three-platform tests. The older
`prepare.py` remains the Android-compared research reference. Default CAL-02 and
CAL-03 encodings retain exact regression fixtures. Preparation has no transport.
An optional physical safe-area profile remains future work; one sheet's offsets
are not hard-coded as universal mechanical correction. Digital fit/padding does
not promise lossless physical edge retention.

The [unified CLI](UNIFIED_CLI.md) now exposes offline prepare/preview, saved job
plans, status, explicit single-job submission and read-only reconciliation.
Portable discovery/pairing and friendlier installation remain future work. Thermal
precompensation is optional research and should not block basic printing or be
enabled from one photographed chart.

## OS print queues and later integration

The first [Windows queue](WINDOWS_PRINT_QUEUE.md) is implemented with Microsoft's
IPP Class Driver and a per-user local PAPPL process. Windows renders application
pages to sRGB raster; a bounded subprocess passes them through the existing
preparation and durable submission interfaces. Surface's portrait/landscape
capture jobs validate the actual OS spooler path without Bluetooth writes, and
a two-page job is rejected before dispatch. A subsequent user-submitted photo
physically printed at quality 100 / 4:4:4, with acknowledged transfer, printing
observed, one-page counter increment and return to idle. Native macOS/Linux builds, service installation and queue
registration are the next integration milestone.

CAL-03 has printed at quality 100 / 4:4:4 with B / TWO leading. Appearance analysis
can proceed separately. With all three adapters' read-only hardware milestones
complete and the unified CLI implemented, the next software steps are queue
packaging and native macOS/Linux installation, followed by portable discovery
and friendlier printer profiles. Existing simulated jobs cover transfer and failure behavior
without paper. Printing through each new adapter/engine remains a separately
authorized physical acceptance test; do not spend a sheet as an implicit part of
discovery, packaging or CI.
