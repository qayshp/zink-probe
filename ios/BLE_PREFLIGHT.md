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

## Clearer BLE outcomes after Build 16

The main app and Share extension use the same result presentation. The source
update distinguishes these outcomes without matching words in a diagnostic error:

| Visible result | Meaning and guidance |
|---|---|
| **BLE connection unavailable.** | A usable native BLE connection could not be established. Check that the printer is on, awake and nearby, and Bluetooth access is enabled, then retry manually. This does not identify a specific physical cause: native Bluetooth, service discovery and notification setup all precede readiness. |
| **BLE setup did not complete.** | Native BLE opened, but the printer's protocol setup exchange failed or timed out. Printer readiness has not been established. |
| **BLE communication did not complete.** | An exchange failed after protocol negotiation, including malformed packets, a missing response or an interrupted connection. This does not by itself identify a physical disconnect. |
| **Printer connected; clock sync needed.** | A complete, validated status reply reported flag `0x00000001`. Use the separate clock-sync action in Select Probe, then rerun the check. The read-only check leaves the clock unchanged. |
| **Printer connected; clock sync and other checks need attention.** | The same clock flag accompanies other flags, a busy/job/queue condition, low battery or an unsuitable power state. Syncing the clock alone is not promised to restore readiness. |
| **Printer connected; not ready.** | Valid replies report paused status, battery/power conditions, queued jobs or other status flags. The detail text identifies the category. |
| **BLE printer check did not complete.** | Readiness could not be verified, for example because a reply is malformed or identity validation fails. The bounded diagnostic report retains the original reason. |

`ReadOnlyPreflight` records a typed readiness refusal only after the relevant
reply has been validated. The stream pump retains that metadata; the BLE bridge
separately records the failed operation stage before closing. Neither metadata
value changes the request sequence, strict rejection conditions, deadlines or
output policies. A truncated clock-bearing reply, an invalid battery percentage
or an unknown pause value cannot produce clock-sync guidance. Known additional
conditions are retained even when the clock flag is present.

The screen and exported report include the plain-language outcome, while the
report preserves existing protocol diagnostics and counters. Unknown framework
error descriptions remain excluded. Failure re-enables manual controls without
automatic retry, clock repair, fallback transport or print authorization.

The wording update was tested offline, then installed from `ad954fd` as signed
version `0.1`, build `16`. The physical iPhone displayed **Printer connected;
clock sync needed.** and **BLE connection unavailable.** in both the main app
and Photos Share extension. See the [iPhone Mirroring verification](ble-preflight-tests/BLE_MESSAGE_MIRRORING_VALIDATION.md).

## Validation and installation

The [offline suite](ble-preflight-tests/README.md) passed 4,035 checks through
the production session/controller with simulated packet/adapter seams: strict
success/refusal, identity, packet/ACK/callback combinations, per-packet interruption,
deadlines, duplicate taps, cancellation, stale generations, startup failure,
sanitized reports and the unconditional print guard. It constructs no Bluetooth
manager. CI also compiles both app targets and checks the isolated BLE-only product.

The wording follow-up additionally passed the shared preflight/framing/clock-sync
tests, accessory interruption/binding tests and **362,226** BLE submission checks.
The complete native BLE core/controller typechecked for iOS 16 with application
extension restrictions. Unsigned generic iPhone builds compiled the main app and
its Share extension, plus the isolated BLE-only app and Share extension; the
isolated bundles retained CoreBluetooth linkage without ExternalAccessory
linkage or accessory protocol declarations. These build and simulation checks
ran separately from the iPhone Mirroring verification.

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
and privacy-reviewed. The preflight screen only reads printer state. Physical BLE image
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
or BLE print support. This earlier session recorded the original generic
"Accessory stream error" wording for the unavailable result.
