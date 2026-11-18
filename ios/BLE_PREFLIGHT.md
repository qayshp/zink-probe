# Build 16: read-only native BLE preflight UI

Build 16 exposes the [native BLE coordinator adapter](BLE_SUBMISSION.md) in
Select Probe and its Share extension. BLE submission remains unconditionally
disabled before authorization or radio creation. The new screen has no print,
clock, settings, recovery or saved-job action.

## Run the check

Main app: **Connection help → BLE adapter preflight**.

Share: select one image in Photos, open **Select Probe** in the app row, then
tap **BLE preflight** in the photo screen's toolbar. The connection-test screen
also offers **BLE adapter preflight**. The image is prepared locally by the
existing Share flow; the BLE check never receives or uploads its JPEG.

1. Tap **Scan for Select over BLE** and wait for the ten-second scan.
2. Choose **Read Select identity over BLE** for the intended candidate. The
   existing bounded diagnostic validates the model and firmware, then closes its
   local connection owner. No automatic adapter action follows.
3. Explicitly tap **Run BLE adapter preflight**. The new native owner connects,
   negotiates BLE and performs its own strict preflight.

The checked peripheral UUID and firmware are held in memory, not a new printer
binding or print authorization. The full preflight independently reads canonical
protocol identity. A new scan or identity attempt clears the old selection.
The prior owner requests CoreBluetooth cancellation before publishing its result;
local cleanup does not independently confirm the physical disconnect via HCI.

## Readiness, lifecycle and reports

The adapter reads firmware/model/identity, negotiates connection-local limits,
reads capabilities and pause/status, and reads the job list and counters only
if the earlier readiness checks pass. Capability discovery returns a read-only
table handle, not a print-job or image-resource allocation.

Strict readiness rules are unchanged. Clock-invalid, paused/busy, low battery,
wrong model/firmware and malformed replies stop the check. Canonical identity
is discovered on this unbound diagnostic screen; callers supplying an expected
device ID also require it to match. In particular,
`flags=0x00000001` remains a time-invalid readiness refusal. It is not cleared,
ignored or classified as a BLE connection failure. An early status refusal
does not establish successful job-list/counter reads or produce a `VerifiedPrinter`.
No clock or persistent printer setting is written.

Opening the screen starts no Bluetooth manager, scan, connection or write. Active
operations disable the other owner's controls. Stop, screen disappearance, app
backgrounding and Share-host backgrounding cancel both owners without automatic
restart. Temporary inactivity during permission prompts does not cancel the test.
The controller invalidates its generation before stopping, so inline/late
callbacks cannot replace a cancelled result. Every adapter attempt uses a fresh owner.

Reports omit peripheral UUIDs, canonical device IDs, serials, candidate names and
raw identity frames. Unknown startup errors use fixed text rather than framework
descriptions. Firmware and nonidentifying readiness values remain visible.
Reports are bounded and shared only through an explicit Share action.

Internal virtual HP+ stream counts and GATT packet counts are labeled separately.
GATT counts include sequence/ACK bytes and represent application callback statistics,
not an over-the-air capture or a sustained-throughput benchmark.

## Validation and installation

The [offline suite](ble-preflight-tests/README.md) passed 3,010 checks through
the production session/controller with simulated packet/adapter seams: strict
success/refusal, identity, packet/ACK/callback combinations, per-packet interruption,
deadlines, duplicate taps, cancellation, stale generations, startup failure,
sanitized reports and the unconditional print guard. It constructs no Bluetooth
manager. CI also compiles both app targets and checks the isolated BLE-only product.

The signed update retains the existing bundle identifiers and development team;
installation uses an update with no uninstall or data reset. Installation alone
is not protocol validation. See the [physical Build 16 report](ble-preflight-tests/PHYSICAL_VALIDATION.md)
and structured transcription for observed main-app, Share and cancellation outcomes.
Private phone screenshots, library images and device identifiers are not published.

The subsequent [bounded clock-sync and full-preflight session](ble-preflight-tests/CLOCK_SYNC_VALIDATION.md)
on 2026-11-18 used the installed Build 16 on firmware `G1L1FA2105AR` and passed
full strict native BLE preflights in both the main app and Share extension,
including the previously unreached job-list and counter queries. A fresh Share
presentation passed again after dismissal/relaunch. The clock action was a
separately authorized time/time-zone write; it was acknowledged, but flags were
already zero before that write and remained zero afterward. This does not prove
that it cleared the earlier time-invalid flag, whose refusal remains recorded
as historical evidence. Actual clock/main/Share report exports were retrieved
and privacy-reviewed. BLE printing remains disabled, and physical BLE image
upload and printing remain untested.

A [Share-first cold-start and unavailable-printer follow-up](ble-preflight-tests/COLD_START_UNAVAILABLE_VALIDATION.md)
on the same date passed full readiness without first opening the main app;
scoped process snapshots found the Share executable and no main-app executable.
With the selected printer switched off by the user, an explicit rerun stopped
after ten seconds, with zero application/GATT bytes and controls enabled again.
After the user switched it on, one explicit rerun re-established BLE communication
and read status in four seconds. Strict readiness correctly refused the reported
time-invalid flag (`0x00000001`). The clock was left unchanged. Exact cumulative
reports were exported, retrieved and privacy-reviewed. These observations retain
existing phone pairing/cache history and do not establish fresh-device onboarding
or BLE print support. The generic "Accessory stream error" wording on the
unavailable result remains a UI cleanup item.
