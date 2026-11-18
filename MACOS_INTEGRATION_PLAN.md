# macOS File → Print integration proposal

Prepared 2026-11-18. This is a proposal based on the current code and read-only
host inspection. No macOS queue, login item, launch agent, Bluetooth permission,
or printer setting was changed while preparing it. No print was submitted.

## Recommended outcome

Make the Select available in an ordinary Mac application's Print dialog, with
Borderless and Preserve edges choices, a quiet background bridge, and a small
setup/status app. The user should not need a Terminal window, Homebrew, an
external Python installation, or the research tools to use a distributed build.

Start with a capture-only integration on this Mac. Prove actual application
rendering, accurate job status, service lifecycle and data preservation before
activating the Bluetooth path. Then validate the packaged app's read-only printer
access. Physical printing is a separate acceptance step requiring authorization.

Keep the first pilot to one Select, one logged-in user, one page and one copy.
The current Classic RFCOMM transport is the initial macOS backend. The parallel
iOS BLE investigation need not block macOS integration or replace that backend.

## What is already available

| Component | Established evidence | Remaining boundary |
|---|---|---|
| Portable image preparation and job engine | Cross-platform tests, previews, durable claims, conservative interruption handling | Installed Mac print-system behavior |
| macOS IOBluetooth adapter | Read-only physical sessions and simulated jobs through the adapter | Packaged app permission identity and physical job acceptance through the full queue |
| Native PAPPL frontend | macOS build, four direct-IPP captures and bounded worker cancellation | Actual Mac application → system queue → frontend rendering and status |
| Borderless / Preserve edges | Capture fixtures and shared preparation API | macOS print-dialog presentation and user defaults |
| Local service/queue installer | Linux user-service and Windows scheduled-task precedents | A macOS installer, upgrade/removal and login lifecycle |

The [POSIX foundation](POSIX_PRINT_QUEUE.md) deliberately builds private PAPPL
and libcups versions without replacing macOS's system CUPS. Its current executable
still depends on host package-manager libraries; it is not a redistributable app.
Read-only inspection on this development Mac found macOS 27.2.1, an Xcode tools
directory, and the system `lpadmin`/`lpstat` tools. The printer listing contained
an existing Xerox queue and no Select queue. That observation is local and dated;
it does not establish support on older macOS versions or Intel Macs.

## Architecture to retain

```text
Mac application → macOS print system → loopback IPP endpoint
  → existing PAPPL raster frontend → existing preparation/job worker
  → existing IOBluetooth RFCOMM adapter → Select

Small setup/status app → background-service registration, queue setup,
                        explicit diagnostics and saved-job recovery
```

This uses the standard IPP route described by [Apple's printer setup guide](https://support.apple.com/guide/mac-help/add-and-manage-printers-mh14004/mac).
Do not introduce a kernel extension, replace system print libraries, or install
a custom CUPS Bluetooth backend that runs the job engine as the spooler account.
The system print service submits IPP data; the logged-in user's bridge owns the
private files and Bluetooth connection.

The existing frontend binds only to `127.0.0.1` and disables DNS-SD. Retain those
defaults, register an explicit endpoint, leave LAN sharing disabled, and preserve
the user's default printer. No firewall exception or network discovery is needed.
Loopback is machine-local, not inherently isolated from other local accounts:
the first pilot must document its single-user scope, detect endpoint ownership
and refuse to replace another listener. Fast user switching and two concurrent
user agents need a deliberate policy before claiming multi-user support.

Retain two named layout profiles initially, following the existing Windows/Linux
design, rather than adding custom Print-dialog UI. Their future live configurations
must share one durable job journal for the same physical printer. Separate queues
must not bypass each other's unresolved-job reservation. A later single queue
with an in-dialog layout selector is optional polish, not a prerequisite.

## Background service and permission identity

**Use a per-user launch agent, not a root launch daemon, for the first version.**
The bridge belongs to the logged-in user and does not require a persistent window.
It may restart its local IPP listener after a crash; it must never retry an
uncertain printer job because it restarted. After logout, the system queue may
still be listed while the user service is unavailable. The app must explain that
distinction; continuous printing while logged out is outside the first pilot.

For a packaged app, use a helper bundled in the app and registered through
[`SMAppService`](https://developer.apple.com/documentation/servicemanagement/smappservice).
Apple supports that API for login items, launch agents and launch daemons on
macOS 13 and later. A development capture installer may use an ordinary user
launch-agent property list first, but it should be disposable integration scaffolding,
not the public installation experience. Queue registration is a separate system
print-configuration action; request administrator authorization only if the
actual host requires it. Do not embed passwords or add a permanent root service.

Bluetooth permission is a separate implementation gate. The existing Python
worker currently owns IOBluetooth, and the permission granted to a development
launcher cannot be assumed to transfer to a new signed app/helper. Use stable
bundle identifiers and executable locations, supply the appropriate purpose
string, and invoke the same packaged worker for an explicit read-only setup check
and later jobs. Apple's [protected-resource guidance](https://developer.apple.com/documentation/bundleresources/protected-resources)
and [`NSBluetoothAlwaysUsageDescription`](https://developer.apple.com/documentation/bundleresources/information-property-list/nsbluetoothalwaysusagedescription)
describe the user permission and purpose string; they do not prove the attribution
of this project's particular helper/process chain.

First test a signed, bundled Python/worker arrangement that reuses the engine.
Record which identity appears in Bluetooth privacy settings, approve/deny behavior,
and whether a restart/update preserves the expected access. If its attribution
is unsuitable, move only the native Bluetooth boundary into an app-owned helper;
do not preemptively rewrite image preparation or the job engine. Do not reset
the user's Bluetooth privacy database or reuse Terminal's permission as the fix.

## Proposed implementation sequence

| Stage | Deliverable | Acceptance check |
|---|---|---|
| **1. Capture installation** | A plan-only macOS installer, then an explicitly installed user agent and clearly named capture queue. Configurations contain no printer address/device ID. | No existing queue/default changes; only loopback listeners; agent can start/stop without Terminal; installation is repeatable or refuses existing state safely. |
| **2. Real Mac print-system validation** | Capture through Preview and one ordinary image/document application, using both layouts. | Portrait/landscape, 58 × 87 mm media and supported quality selections produce the expected 768 × 1152 preparation, encoding and separate safe-area preview. Unsupported multi-page/copy jobs do not dispatch a worker. |
| **3. Status and restart correctness** | Actual-spooler failure/cancellation tests, idle restart and interruption fixtures. | Mac queue and PAPPL both report failed/canceled work accurately; no false success; terminal captures survive restart; interrupted claims stay blocked; nothing replays on login or service restart. |
| **4. Stable app/helper package** | A minimal setup/status app, bundled runtime/libraries and `SMAppService` registration. | No Homebrew/external Python dependency; clean launch without console windows; paths with spaces work; service status and disabled-login-item states are understandable; dependency licenses are included. |
| **5. Packaged read-only Bluetooth** | Explicit printer selection/identity binding and a read-only check through the final worker identity. | Purpose-string/permission behavior, denial recovery, paired-device validation and connection cleanup work from the packaged route. No image or job-allocation command is sent. |
| **6. Explicit live activation** | Fresh live spool/configuration plus shared journal and timestamp boundary. | Capture rasters cannot replay; pending/uncertain work blocks activation or submission; queues remain distinguishable; fresh read-only preflight passes. Activation itself submits no job. |
| **7. Authorized physical acceptance** | A user-selected one-photo print from the ordinary Mac print dialog. | Exact job, acknowledged transfer, observed printer status/counters, physical output and layout assessed separately. Any uncertain outcome stops automatic resubmission. |

Stage 3 must explicitly investigate the [Linux CUPS status mismatch](LINUX_PRINT_QUEUE.md#important-status-limitation-before-live-linux-printing).
That host reported a deliberately rejected job as completed even though PAPPL
reported aborted. macOS also has a system-spooler → local IPP hop, so test it
rather than assuming the Windows result carries over. The same cause on macOS
is a hypothesis, not an established defect. A shared fix, if appropriate, benefits
Linux too.

The first useful macOS milestone is **stages 1–3**, all without printer traffic
or paper. Stages 4–5 settle usability and permission requirements. Do not label
the resulting queue production-ready solely because direct-IPP CI passed.

## Small app, private data and lifecycle

The setup/status app should initially expose only:

- Install/remove the local queues and enable/disable the background service.
- Show capture/live mode, local service availability and the last printer-check
  result with its time. A listed queue is not a continuous printer-ready signal.
- Run an explicit read-only printer check and show actionable permission/pairing
  instructions; do not automatically change pairing or disconnect other devices.
- Open captured previews/results and identify unresolved jobs for read-only
  reconciliation. A canceled connection cannot promise the sheet stopped.

Keep mutable data outside the application bundle, under a private
`~/Library/Application Support/…` directory, with separate capture/live/profile
spool directories and one shared live journal per printer. Logs, source rasters,
prepared JPEGs and identity records are private. Avoid indefinite unbounded
retention in a public build, but cleanup must never erase unresolved claims or
turn an old image into a new submission.

Upgrade only when idle, preserve journal/schema compatibility and saved artifacts,
replace versioned app/runtime components together, and retain a rollback path.
Removal unregisters the service and owned queues; it does not silently delete
job history, pairing records or unresolved work. A separate explicit data-removal
action can be designed after reconciliation rules exist. Preserve the original
queue/service configuration so a failed installation can undo only its own work.

## Distribution and remaining decisions

Recommend a directly distributed app first. A Mac App Store submission is not
required to prove File → Print and would add a separate distribution/sandbox
evaluation. A public direct-distribution package should use Developer ID signing,
hardened runtime and notarization, with all bundled executables/native libraries
handled consistently. Apple's [Developer ID guidance](https://developer.apple.com/developer-id/)
and [notarization instructions](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution/)
describe that route. No signing credential or notarization upload is part of this
proposal, and successful notarization is not a hardware compatibility test.

Resolve these through implementation evidence, rather than making them promises:

- Actual macOS print-driver/IPP capability matching, quality control visibility
  and whether the two queue profiles present clearly in common applications.
- The packaged Python/helper's effective Bluetooth permission identity and
  behavior after an app update.
- Deployment target and architecture coverage. Start on this Apple Silicon Mac;
  produce and verify separate Intel support or a complete universal dependency
  build before claiming it. The current host-only native build does neither.
- Accurate system-queue failure/cancellation status and the no-replay boundary
  across a bridge crash, OS logout and later login.
- Local-account access policy before expanding beyond the single-user pilot.

Additional paper calibration, family-wide printer support, BLE migration on Mac,
automatic retry, printing while logged out, a permanent menu-bar monitor and a
large printer-settings interface are not needed for the first useful integration.
