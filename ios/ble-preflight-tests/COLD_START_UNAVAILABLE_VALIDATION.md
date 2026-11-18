# Share-first cold start and printer-unavailable checks — 2026-11-18

This follow-up uses the installed Select Probe Build 16 and its native BLE
read-only preflight. It follows the successful
[clock-sync and full-preflight session](CLOCK_SYNC_VALIDATION.md).

The user reported force-closing both apps before reconnecting iPhone Mirroring.
The follow-up started at **18:22:42 UTC**. Before opening Share, an Apple device-tool
process snapshot at approximately **18:22:55 UTC** listed no executable matching
the project's main/extension targets: `SelectAccessoryProbe`, `SelectShare`,
`BLEOnlyProbe` or `BLEOnlyShare`. The agent opened Photos without launching the
Select Probe main app first. This supports the Share-first process-lifetime
check; it does not prove that iOS removed prior cached accessory/radio state.
Existing phone pairing history is retained.

A second scoped process snapshot while the Share extension was open identified
one `SelectShare` executable and no `SelectAccessoryProbe`, `BLEOnlyProbe` or
`BLEOnlyShare` executable. Matching uses the exact final executable name: the
extension's enclosing app path contains the main-app name and must not be
mistaken for a running main-app executable. The complete snapshot is ignored;
only these project-specific counts and its hash are retained in the evidence.

The authorized sequence was to open Photos and invoke the Select Probe Share
extension before opening the main app, run the bounded read-only check and
export its report, then coordinate printer power-off for an unavailable-printer
check. The user turned the printer off after the agent signaled readiness.

**The Share-first full preflight passed. With the printer off, an explicit
attempt stopped after ten seconds with zero application bytes. After power-on,
BLE communication resumed, but strict readiness stopped for the time-invalid
flag.** That flag was left unchanged. The final Back/Done actions returned to
Photos; the session was confirmed over by **18:34:07 UTC**.

BLE printing remains unconditionally disabled. No print-job allocation, image
upload, print, clock synchronization, other persistent-setting write, pairing
reset or Bluetooth-permission change is authorized by this session.

## Results

| Check | Observed result |
|---|---|
| Force-close context | User reported completing it; no project executable identified in pre-Share process snapshot |
| Share-first native BLE preflight | Full strict readiness passed after fresh passive presentation and explicit identity/preflight actions |
| Exact Share-first report export/retrieval | Actual report retrieved and privacy-reviewed; exact copy retained |
| Selected printer unavailable | Terminal failure after 10 seconds, zero application bytes/streams; exact report retrieved |
| Explicit recovery after power-on | BLE reconnected; strict readiness refused the time-invalid flag; exact report retrieved |

## Share-first full native BLE preflight

The extension initially showed Ready for an explicit scan/preflight with no
previous selection. A scan and identity check were explicitly requested; the
identity check passed for firmware `G1L1FA2105AR`. The main app was not opened as
a preparation step, and the scoped process snapshots above identified the Share
executable without the main executable.

The explicit full native preflight started at **18:25:17 UTC**, opened both
virtual streams at **18:25:18 UTC**, and passed at **18:25:19 UTC**. It reached
the final queue/counter queries and reported firmware `G1L1FA2105AR`, **100%**
battery, idle/empty queue, no flags, not paused, maximum message **1000**, setup
byte **33**, job-name limit **16**, **13 pages** and **2 calibration cycles**.
These counter snapshots match the preceding successful session; no new job was
allocated and no image or print request was sent.

Virtual stream counts were TX/RX **86/469 bytes**, two opened streams. Native
GATT counts were TX queued/acknowledged **46/46 bytes**, **12** write callbacks,
RX **431 bytes**, protocol MTU **514**, ACK period **0**. The report's “GATT
packets” label describes byte counters, with callbacks counted separately.

The [exact Share-first report](evidence/2026-11-18-cold-share-first-ble-report.txt)
was exported through Share → Save to Files → iCloud Drive using Keep Both.
Actual synced `text 4.txt` bytes were retrieved into an ignored local build
file, inspected for privacy, and copied without redaction. Its SHA-256 is in
the structured evidence. This is an exported application log, not a radio capture.

After that successful export, the user was asked at approximately **18:25:45 UTC**
to turn the printer off. The selected identity remained in the same preflight
screen for the subsequent explicit connection attempt.

## Printer unavailable

The user confirmed **“Off.”** A new explicit **Run BLE adapter preflight** action
was requested at **18:29:16 UTC**, retaining the previously checked identity and
without requesting a new scan. The screen first showed Opening,
then by approximately **18:29:40 UTC** showed **Read-only BLE adapter preflight
did not pass.** The result was **Accessory stream error; no retry**. The spinner
had stopped and Run/Scan controls were enabled again. No automatic retry was
observed.

The [exact cumulative unavailable report](evidence/2026-11-18-cold-share-unavailable-ble-report.txt)
was exported and retrieved from synced `text 5.txt`, privacy-reviewed and copied
without redaction. It includes the earlier cold success and the later failure.
The failure event was recorded at **18:29:26 UTC**, **10 seconds** after the
explicit request. This is consistent with the native connecting-stage bound;
the generic report does not establish the exact framework-level error cause.

The failed attempt opened **zero** virtual streams and accepted/received **zero**
virtual application bytes. GATT TX queued/acknowledged bytes, write callbacks and
RX bytes were all **zero**. Its reported MTU **20** and ACK period **0** were the
initial defaults, not a successful negotiation with the unavailable printer.
These are application counters, not proof that no system Bluetooth traffic occurred.

The displayed wording is generic and says “Accessory” in this BLE context. This
could be clarified in a later UI cleanup; no source code was changed here.

The user was asked at approximately **18:29:50 UTC** to turn the printer on
again and subsequently confirmed **“On.”** No recovery attempt preceded that
confirmation.

## Explicit recovery after power-on

Using the same retained selection, a new explicit native preflight started at
**18:31:19 UTC**. Both virtual streams opened at **18:31:23 UTC**. In that second
the printer returned a valid status that stopped strict readiness:

```text
flags=0x00000001, state=1, currentJob=0, queue=1, battery=99, power=1
```

The time-invalid flag was present after the user-reported power cycle, whereas
the initial cold Share-first pass had reported no flags. This single observation
does not independently measure the current printer clock, determine its drift,
or establish a general clock-retention rule. No clock synchronization was sent,
and the strict readiness rule was not weakened or bypassed.

This is **successful BLE reconnection with a readiness refusal**, rather than a
failed BLE connection or a full post-cycle preflight success. The queue-list and
metric queries after the status gate were not reached. **13 pages / 2 calibration
cycles** remain the earlier pre-cycle snapshots, not fresh post-cycle counters.

The failed-readiness attempt reported virtual TX/RX **62/337 bytes**, two streams;
GATT TX queued/acknowledged **34/34 bytes**, **9** write callbacks, RX **311 bytes**,
protocol MTU **514**, ACK period **0**. No automatic retry occurred.

The [exact cumulative recovery report](evidence/2026-11-18-cold-share-recovery-ble-report.txt)
was retrieved from actual synced `text 6.txt`, privacy-reviewed, and copied
without redaction. It retains the initial cold success, the unavailable failure,
and the post-cycle status refusal. All three report hashes are in the structured
evidence. The agent did not launch the main app during this session.

## Unavailable-printer method

After a successful identity check, retain the selected identity in the same
BLE preflight screen. A new scan clears that selection, so the intended native
connection-failure test uses **Run BLE adapter preflight** after the user confirms
the printer is off. The native owner creates a new CoreBluetooth central,
retrieves the selected peripheral routing UUID and attempts a connection.

The source bounds the connecting stage to ten seconds after `connect` is issued;
a framework failure may finish earlier. The Bluetooth-state wait has a separate
30-second limit, and the shared setup composition has a 90-second upper limit.
These are source limits, not observed timings. Record the actual report rather
than assuming which deadline caused a failure.

After the user switches the printer on again, a new explicit attempt can test
recovery. If clock-invalid reappears, a readiness refusal must remain distinct
from a Bluetooth transport failure. This session does not authorize clearing it.

## Evidence boundaries

The ignored pre-Share process snapshot contains 392 process rows; the during-Share
snapshot contains 399. Only the scoped project executable counts are retained
here; the full phone process inventories, process identifiers, enclosing private
paths and device identifier are not published. The raw snapshot hashes are in
the structured evidence. The device-tool JSON has no event timestamp, so
collection time is the agent's approximate observation, not a timestamp
extracted from the file.

Record actual on-screen outcomes and exact exported report bytes separately.
Do not label a visible Save-to-Files action as Mac retrieval until the actual
file has been read and inspected. Native report logs omit routing and canonical
device identities; privacy-review every export before committing it.

Do not publish private phone screenshots, photo-library images, device UUIDs,
addresses, serials, account details or photo metadata. Application virtual-stream
and GATT byte counters are not over-the-air captures. No radio-teardown,
never-paired onboarding, image-transfer or printing success is inferred from
these read-only checks. No source code changed during this session; the remaining
cleanup item is clearer BLE-specific wording for the generic unavailable error.

Structured observations are in
[2026-11-18-cold-start-unavailable.json](evidence/2026-11-18-cold-start-unavailable.json).
