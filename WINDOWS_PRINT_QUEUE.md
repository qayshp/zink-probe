# Windows File → Print → HP Sprocket Select

The first standard Windows queue uses **Microsoft IPP Class Driver**, a local
PAPPL process, and this project's existing Python preparation/job engine. It is
an experimental photo printer integration, not an HP-provided driver. The native
queue process is x64; Windows ARM64 emulation runs it on Surface while Python,
Bluetooth, and Microsoft's print driver remain ARM64 native.

## Using the queue

Choose **HP Sprocket Select** in an application's Print dialog. Select the
**58 × 87 mm** paper size (some dialogs display the custom media name), color,
one page, and one copy. Set portrait/landscape and fit/fill in the application's
preview. The Windows renderer supplies the complete page; the bridge preserves
that layout and resamples it to 768 × 1152 before JPEG encoding. Mechanical edge
loss remains possible, just as in the original app. This integration does not
apply an unproven crop/thermal/color correction.

| Standard quality selection | JPEG produced by the worker |
| --- | --- |
| Draft (IPP 3) | quality 85, 4:2:0 |
| Normal (IPP 4, default) | quality 90, 4:2:0 |
| High/Best (IPP 5) | quality 100, 4:4:4 |

Applications differ in which quality controls they expose. The bridge implements
the standard IPP quality attribute; an app that does not send it uses Normal.
These settings change image encoding only. They do not alter heater temperature,
paper speed, firmware LUTs, or firmware color processing. The advertised
600 × 600 DPI is a **Windows page-rendering resolution**, not a claim about the
Select's physical heater grid. The Bluetooth payload is still 768 × 1152.

The user who paired the Select must be logged in. A per-user scheduled task
starts the bridge at logon. The printer must be powered on, nearby, and available
to this host. The bridge listens only on `127.0.0.1`; it is not shared on the LAN,
does not require a firewall exception, and does not change the default printer.

## Supported scope and remaining acceptance test

- One page and one copy per job. Multi-page jobs are rejected before **any** page
  is submitted, even when the first raster page was decoded successfully.
- Windows applications can render through the native IPP driver to PWG raster.
  The PAPPL endpoint also accepts JPEG/PNG via its built-in raster filters. It
  does **not** advertise native PDF input; a Windows application renders the PDF.
- Capture mode validates Windows spooling, page geometry and JPEG preparation
  without opening Bluetooth. The differently named capture queue must not be
  mistaken for the live printer.
- Simulated jobs validate complete protocol execution and payload equality.
  Read-only Bluetooth checks validate the real adapter separately. A physical
  sheet through this new Windows queue remains a separate acceptance test.
- Queue availability describes the local bridge. It is not a continuous live
  battery/paper/temperature reading. Actual identity and readiness are checked
  when a job connects, before any mutating protocol command.
- Cancellation stops the worker while preserving durable claims. Once a device
  has accepted a job it may still print. No software claim guarantees that
  cancellation can retract a physically started sheet.
- A timeout or uncertain result is not retried automatically. Windows reports a
  failed/aborted job; inspect the private result and journal before resubmitting.
  A new Print action creates a new job, so do not blindly repeat it after a
  possible transfer. Claims protect this installation's journal, not independent
  computers or unrelated CLI journals.

## Installation and capture-first validation

Prerequisites: Windows 10/11 with Microsoft's IPP Class Driver, Python 3.11+,
the Select paired in Windows Settings, and the trusted Classic address/protocol
device ID obtained by the existing read-only tools. The current packaged native
frontend supports ASCII installation paths. A distributable signed installer,
native ARM64 C build and Windows Protected Print Mode certification are future
work; no such certification is claimed.

Build the wheel with `python -m build --wheel`. Download the native artifact from
the repository's [Native IPP queue workflow](https://github.com/qayshp/zink-probe/actions/workflows/native-queue.yml),
extract it to a local directory, and keep its dependency licenses. In an elevated
PowerShell session **as the user who paired the printer**:

```powershell
.\native\Install-SelectQueue.ps1 `
  -NativeDirectory C:\path\to\zink-ipp-windows-x64 `
  -Wheel C:\path\to\zink_probe-0.1.0-py3-none-any.whl `
  -Python C:\path\to\python.exe
```

This defaults to **Capture** and registers **HP Sprocket Select (capture)**. The
private `%LOCALAPPDATA%\ZinkProbe` directory grants access to the current user,
SYSTEM and administrators. The installer does not submit a job. For an explicitly
guarded, paper-free end-to-end Windows spooler check:

```powershell
.\native\Validate-CaptureQueue.ps1
```

It verifies that the running process uses a capture configuration with **no
printer credentials**, then renders portrait and landscape pages and deliberately
rejects a two-page document. Inspect `capture\jobs\*\preview.png`, `result.json`
and `capture\bridge.log`. The rejected Windows job and raw diagnostic raster are
retained for inspection; remove that **capture-only** queue item and archive its
raw raster before activating. The installer refuses activation with unresolved
capture work.

To intentionally enable subsequent application printing, rerun the installer
with `-Mode Live -DeviceConfig C:\private\device.json` and the same other
arguments. `device.json` contains `address` and the 32-hex `device_id`; never
commit it. Activation creates a fresh `live` data/spool directory, stops the
capture task, and renames the checked-empty Windows capture queue to
**HP Sprocket Select**, retaining its native IPP port. Direct Live installation
registers a new queue. Old captures are not replayed. A timestamp gate rejects
rasters created before activation, and a per-job exclusive directory claim
prevents reusing a captured or interrupted worker job.

Installation/activation alone does not print. A later **Print** action to the live
queue does consume paper. Never use Windows' “Print test page” during a paper-free
installation check.

## Private records and recovery

`%LOCALAPPDATA%\ZinkProbe\live` contains:

- `config.json`: expected device identity and Bluetooth endpoint.
- `jobs.sqlite`: the shared durable engine journal for this queue.
- `jobs\<UUID>`: immutable claim, prepared JPEG, decoded preview, preparation
  manifest, raw protocol trace and result (when the worker finishes).
- `incoming`: temporary raw pages; successful pages are removed after a durable
  receipt is written. Failed/uncertain raster data is retained.
- `spool`: PAPPL queue state and its spool files; `bridge.log` is its diagnostic log.

Image previews and traces remain private and are retained for diagnosis; this
initial implementation has no automatic retention cleanup. Do not erase journals
or failed claims to force retries. Use the existing read-only protocol tools to
check the device and investigate uncertain work first. An aborted job with no
final receipt may mean a stopped worker, not that the printer received nothing.

The scheduled task is **ZinkProbe-Select**. To remove the integration while idle,
remove the named Windows printer, stop/unregister that task, and retain the private
directory until every outstanding device job is understood. No Bluetooth pairing
needs to be removed. The installer deliberately refuses to overwrite an existing
mode's data directory; upgrades must preserve journals and stop the idle bridge
before replacing its binaries.

## Implementation and reproducibility

[`native/select-app.c`](native/select-app.c) supplies PAPPL's raster callbacks.
It buffers an entire bounded page (maximum 4096 on either axis), requires an exact
8-bit chunky sRGB raster, and dispatches the worker only after successful end of
the whole job. It has no raw printer-byte path. The worker is a fresh Python
process, which also accommodates macOS's main-thread IOBluetooth requirements.
[`ipp_worker.py`](src/zink_probe/ipp_worker.py) validates the private input location,
dimensions, 2:3 page ratio and complete byte count; prepares the image through the
existing API; and calls the existing durable engine. Capture mode exits before
constructing a transport.

The native workflow builds PAPPL commit
`02050bdbd4b3e610180c0433f47b7bf2c4569e44` with its pinned Windows NuGet dependencies.
[`patch_pappl.py`](native/patch_pappl.py) applies three exact-source replacements
to make IPP copy advertising/defaults/validation honor `copies_supported` instead
of hardcoding 999. It fails if the pinned source changes. The separate reference
PAPPL checkout is untouched. The pinned JPEG package uses v142 import-library
paths; the build explicitly selects those ABI-compatible imports under v143.

The workflow runs a real loopback IPP capture test for Normal and High JPEG jobs,
checks media/copy/format capabilities, and rejects two copies. Portable worker
tests run with the existing macOS/Linux/Windows matrix. Surface's actual Windows
spooler test is separate from that CI evidence.

## macOS and Linux next

Keep the same IPP frontend, preparation and job engine. Next build/link the native
PAPPL frontend on each platform, install it with the correct user service and
Bluetooth permissions, and register a local IPP queue with the platform's print
system. Validate actual OS raster output, color, page size, cancellation and
restart recovery before a separately authorized sheet. Linux requires BlueZ;
macOS requires its existing IOBluetooth/PyObjC backend. These queue installers
are not implemented by the Windows milestone.
