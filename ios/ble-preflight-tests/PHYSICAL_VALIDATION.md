# Physical native BLE preflight UI validation — Build 16

Date: 2026-11-18. This record distinguishes the new native coordinator adapter's
physical behavior from the earlier [four diagnostic-only BLE
checks](../ble-tests/PHYSICAL_VALIDATION.md).

**Build 16 is installed, and the new native adapter exchanged valid protocol
replies through status in both the main app and the Share extension. Both then
correctly refused readiness because the printer's clock-invalid flag was set.**
Neither run is a successful full readiness preflight.

**The final-source artifact was rebuilt, signed, signature-verified, installed
and launched. Repeated main-app and Share checks both confirmed the same strict
readiness refusal.**
The initial installed Build 16 artifact compiled before a
controller refinement that cleans up a partially started operation when startup
throws. The normal, strict-readiness and background-stop paths observed below
were unchanged by that refinement. These initial observations remain valid for
that installed artifact, but are not presented as verification of an identical
final-source binary. The final-source repeats are recorded separately below.

The signed app and Share extension built successfully. `devicectl` confirmed
installation with the existing bundle identity; no uninstall, data reset or
pairing reset was used. iPhone Mirroring visibly showed the new BLE adapter
preflight entry. Installation evidence is separate from the protocol observations
below.

The final offline suite passed **3,010 checks**, including strict readiness
refusals, lifecycle interruptions, late callbacks, explicit-only start behavior
and report redaction. Those simulated results remain separate from the physical
observations below.

The final signed app bundle passed to installation had these executable hashes.
These identify the local installation artifacts; they are not a device-filesystem
hash readback:

| Executable | SHA-256 |
|---|---|
| Main app | `2e617867348cdf93a9ab879560e4a06546dc24be48d6f3c04947981dde6a778e` |
| Embedded Share extension | `0e5b2b6d91c168eef9664ad240945c32f92b392cc726167f688d7a3d4785eb81` |

Swift source was frozen for this rebuild and subsequent physical repeats. No
installation identifier, device identifier, profile or signing credential is
published here.

Evidence is a manual transcription of reports visibly displayed through
iPhone Mirroring, rather than an exported application log or raw GATT/HCI capture.
Private phone-library images and screenshots are not published. Device UUIDs,
addresses, serials and canonical protocol identities are omitted.

## Scope and results

| Context / observation | Result |
|---|---|
| Build 16 main app installation | Confirmed; no uninstall or data reset |
| Main app: explicit scan and diagnostic identity check | Passed; checked firmware `G1L1FA2105AR`, then offered the separate preflight action |
| Main app: new native BLE adapter preflight | Valid communication through status; **readiness refused**, clock-invalid flag `0x00000001` |
| Main app: cancellation or dismissal | Discovery cancellation and active-preflight background stop observed; no automatic restart on foreground |
| Share extension: explicit scan and diagnostic identity check | Passed from Photos; checked firmware `G1L1FA2105AR` |
| Share extension: new native BLE adapter preflight | Valid communication through status; **readiness refused**, clock-invalid flag `0x00000001` |
| Share extension: cancellation or dismissal | Active-preflight Share-host background stop observed; no automatic restart; final back/Done returned to Photos |

The UI requires a successful diagnostic check to obtain the selected peripheral's
routing UUID and firmware. The diagnostic owner then closes locally. A separate
explicit tap starts the native adapter's fresh preflight; there is no automatic
handoff or submission. CoreBluetooth cancellation is asynchronous, so local
cleanup alone does not independently prove acknowledgement of a physical radio
disconnect before the next tap.

## Initial main-app observations

An initial discovery scan was stopped with the screen's stop control. The UI
reported **Stopped by user**, removed candidates, and offered no adapter-preflight
run action. A new explicit scan and successful diagnostic identity check then
made that separate action available. No automatic preflight followed the identity
check. The cancellation timestamp and scan packet counts were not transcribed;
this observation does not test interruption of an active native preflight.

The subsequent explicitly requested native-adapter report recorded these UTC
times on 2026-11-18:

| Event | Reported time |
|---|---|
| Native BLE preflight requested; expected firmware `G1L1FA2105AR` | 17:16:01 |
| IF_CONFIG completed and both virtual streams opened | 17:16:02 |
| Readiness refusal after a valid status reply | 17:16:03 |

The exact refusal was:

```text
Printer not idle/empty/error-free: flags=0x00000001, state=1, currentJob=0, queue=1, battery=99, power=2
```

| Reported observation | Value |
|---|---|
| Virtual streams opened | 2 |
| Virtual stream TX / RX | 62 / 337 bytes |
| GATT packet TX queued / acknowledged | 34 / 34 bytes |
| Successful native write callbacks | 9 |
| GATT packet RX | 311 bytes |
| Negotiated protocol MTU / ACK period | 514 / 0 |
| Status flags | `0x00000001` |
| Printer state / current job / queue | 1 (idle) / 0 / 1 (empty) |
| Battery / power code | 99% / 2 |

The UI explicitly explained that the time-invalid flag was left unchanged and
that readiness refusal is separate from BLE connection failure. The firmware,
model/device identity, setup, capability and pause exchanges had reached status;
the strict refusal then prevented queue-list and metric reads. No
`VerifiedPrinter` readiness evidence was produced, and no page or calibration
counter value is inferred from this run. Report times have one-second precision
and are not a throughput or latency benchmark.

A second main-app native preflight was explicitly requested at **17:17:05 UTC**.
The agent then sent the app to the Home screen. The report recorded
**BLE adapter preflight entered the background** at **17:17:06 UTC**. On returning
to the same app, its retained screen showed **Stopped; no automatic retry**, the
background-stop reason, and an enabled run button. No automatic restart occurred.
There was no new opened-stream line between that request and stop in the visible
report. GATT byte counts for this cancelled attempt were not transcribed, so this
observation does not assert that no negotiation packets had already been sent.
The cancellation requested local/native cleanup; it is not an independent
over-the-air disconnect capture.

## Initial Share-extension observations

From Photos, the agent selected **Select Probe** in the Share-sheet application
row, then **BLE preflight** in the extension toolbar. An explicit diagnostic
identity check succeeded for firmware `G1L1FA2105AR`; the selected candidate's
reported signal was -36 dBm. The photo was handled locally by the existing
preparation flow and was not sent to the printer. A separate explicit tap then
started the new adapter.

| Event | UTC on 2026-11-18 |
|---|---|
| Native BLE preflight requested; expected firmware `G1L1FA2105AR` | 17:20:21 |
| IF_CONFIG completed and both virtual streams opened | 17:20:22 |
| Readiness refusal after a valid status reply | 17:20:22 |

The Share report contained the same refusal and reported values as the main-app
run: flags `0x00000001`, state 1, current job 0, queue 1, battery 99%, power code
2, virtual TX/RX 62/337, two opened streams, GATT TX queued/acknowledged 34/34,
nine native write callbacks, GATT RX 311, protocol MTU 514 and ACK period 0.
The time-invalid explanation was visible, and the clock was left unchanged.
No `VerifiedPrinter` was produced, and queue-list/metric reads were not reached.

A second Share native preflight was explicitly requested at **17:20:56 UTC**,
then the agent sent the phone to Home. The report recorded **Share host entered
the background** at **17:20:57 UTC**. Returning to Photos retained the Share
screen with **Stopped; no automatic retry**, that stop reason, and an enabled
run button. No automatic restart occurred. Cancellation GATT counts were not
transcribed and are not assumed to be zero. This tests the observed Share-host
background path, not every possible extension termination.

Finally, the agent used Back and Done, and visibly returned to Photos, closing
the Share flow. No image upload, physical job, print, clock synchronization or
persistent printer-setting write was performed in either context.

## Final-source repeats

After rebuilding, signing, verifying and reinstalling the frozen final source,
the main-app diagnostic identity step and separate native preflight were repeated.
The final artifact's main report recorded:

| Event | UTC on 2026-11-18 |
|---|---|
| Explicit native preflight requested; expected firmware `G1L1FA2105AR` | 17:24:42 |
| Both virtual streams opened | 17:24:43 |
| Strict readiness refusal after status | 17:24:44 |

The refusal and all reported values matched the initial run exactly: flags 1,
state 1, current job 0, queue 1, battery 99%, power 2; virtual TX/RX 62/337 with
two opened streams; GATT TX queued/acknowledged 34/34, nine write callbacks,
RX 311, protocol MTU 514 and ACK period 0. Thus the final compiled main-app
source was physically confirmed through status, with readiness still refused.

The final-artifact Share extension was then opened from Photos. Its candidate
signal was -35 dBm, and the explicit diagnostic identity check again succeeded
before the separate native preflight:

| Event | UTC on 2026-11-18 |
|---|---|
| Explicit native preflight requested; expected firmware `G1L1FA2105AR` | 17:27:24 |
| Both virtual streams opened | 17:27:25 |
| Strict readiness refusal after status | 17:27:25 |

All status and traffic values matched the final main-app and initial reports:
flags 1, state 1, current job 0, queue 1, battery 99%, power 2; virtual TX/RX
62/337 with two opened streams; GATT TX queued/acknowledged 34/34, nine write
callbacks, RX 311, protocol MTU 514 and ACK period 0. The clock-invalid
explanation was visible. Back and Done returned to Photos and closed Share.

Both final-source contexts were therefore physically confirmed through the strict
status check against the installation artifacts identified above. The initial
background-cancellation observations remain labeled as initial-artifact tests.
Their cancellation code was unchanged by the later startup-throw cleanup
refinement; the final-source startup-throw cleanup itself was tested offline,
not induced on the phone. No device-binary hash readback is claimed.

## Interpreting readiness

The new adapter retains the existing strict readiness conditions. A nonzero
clock-invalid flag, paused printer, unsuitable battery/power state, busy state,
current job or nonempty queue refuses readiness. A valid status response followed
by such a refusal establishes communication through that stage, not a failed
Bluetooth connection or successful full readiness preflight.

In particular, a clock-invalid refusal must remain a refusal. This test does not
set the clock, clear flags, change settings or continue past a failed readiness
condition. It creates no `VerifiedPrinter` readiness evidence in that case, and
later queue/counter reads may not be reached. No printer state or outcome is
assumed from an earlier session.

## Evidence boundaries

The physical UI work is authorized only for discovery and bounded read-only
protocol exchanges, including connection-local negotiation. BLE printing remains
unconditionally disabled before authorization or Bluetooth creation in the
submission entry point. The read-only screen has no image-upload, print-job,
clock-sync or persistent-settings action. No physical job allocation, upload or
print is part of this validation.

Successful UI tests do not establish image-transfer throughput, physical BLE
printing, never-paired onboarding, or App Store eligibility. Cancellation tests,
as observed above, are recorded independently rather than inferred from offline
coverage. Existing pairing state was retained. The full readiness success path
and subsequent queue/metric reads remain physically unverified for this new
owner because all recorded normal runs stopped at the same strict readiness check.

Structured observations are in
[2026-11-18-build16.json](evidence/2026-11-18-build16.json).
