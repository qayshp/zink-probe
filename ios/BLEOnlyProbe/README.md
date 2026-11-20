# BLE-only control app and Share extension

**Select BLE Check** is a separate BLE control experiment using its own bundle
identifiers `org.qayshp.zink.BLEOnlyProbe` and
`org.qayshp.zink.BLEOnlyProbe.Share`. It can coexist with Select Probe without
replacing that app or touching its saved drafts and job journal.

By default both targets offer the shared CoreBluetooth diagnostic
[`BLEProbe.swift`](../SelectAccessoryProbe/BLEProbe.swift) and its
[`BLEReadOnlyCheck`](../BLECore/BLEReadOnlyCheck.swift) sequence. The Share
extension is offered for one image and deliberately leaves that image unread.
Neither target declares or links External Accessory or uses background modes.
Opening either UI starts no scan, connection or application write.

The control is useful because a BLE connection in the existing Select Probe
product could coexist with an already-declared External Accessory route.
The [physical main-app and Share results](../ble-tests/PHYSICAL_VALIDATION.md)
show that the fixed BLE check works without linking or declaring External
Accessory in those processes and the tested phone's existing pairing environment.
It does not establish fresh-pairing behavior, BLE job acceptance/upload/printing,
or App Store approval.
The same native owner is reused so differences in framing do not confound the
comparison. The products retain separate system Bluetooth permissions.

Build without signing from the repository root:

```sh
xcodebuild -project ios/BLEOnlyProbe/BLEOnlyProbe.xcodeproj \
  -scheme BLEOnlyProbe -destination 'generic/platform=iOS' \
  -derivedDataPath build/ios-ble-only CODE_SIGNING_ALLOWED=NO build
```

For installation, open the project in Xcode, select your own development team and
physical phone, and use ordinary development signing. No team or provisioning
profile is committed. The current build number is 4 and deployment target is iOS 16. Installation
and opening a UI do not authorize automatic device tests.

For a deliberate physical test, open **Select BLE Check**, tap **Scan for Select
over BLE**, select the printer after the bounded scan, then tap **Run read-only
BLE check**. Share the report when finished. To test the extension independently,
share one photo from Photos, choose **Select BLE Check** in the application row,
and repeat the explicit scan/check. The shared image is not read or sent.

Validation during development: an unsigned generic physical-iOS build passed
for both targets. Built Info.plists contain Bluetooth usage descriptions but
neither `UISupportedExternalAccessoryProtocols` nor `UIBackgroundModes`.
`otool -L` confirms both binaries link CoreBluetooth and do not link
ExternalAccessory. Both targets subsequently built with development signing,
and `devicectl` confirmed installation of Select BLE Check Build 1 on the paired
iPhone beside Select Probe. No app data or pairing was reset. Those build,
installation and package checks alone do not establish a physical connection.

On 2026-11-18 the separate main app and its Share extension each physically
completed the fixed read-only sequence. The main app received its own Bluetooth
permission prompt; the extension was subsequently authorized without another
prompt. Both reported firmware `G1L1FA2105AR`, model `0x48d3`, 227 capability
bytes and unchanged before/after
status (99% battery in the main app, 98% in Share, idle/empty, clock-invalid flag
left set). Each run used 40 TX bytes acknowledged in eight write callbacks and
314 RX bytes. See the [sanitized physical evidence and
limitations](../ble-tests/PHYSICAL_VALIDATION.md). No job, image, print or
persistent printer-setting write was attempted. Existing phone pairing history
was retained; this result does not establish first-time onboarding or App Store
eligibility.

## One-sheet BLE pilot

The distinct, opt-in main app build uses CoreBluetooth for discovery, strict
printer preflight, the complete journaled one-job submission, and read-only
recovery. It uses the same packet bridge and durable coordinator exercised by
the [simulated transfer and interruption suite](../BLE_SUBMISSION.md).
The package uses the ordinary Bluetooth permission. Apple's
[MFi FAQ](https://mfi.apple.com/en/faqs.html) and
[Bluetooth accessory guidance](https://developer.apple.com/library/archive/qa/qa1657/_index.html)
describe standard BLE through CoreBluetooth as outside the MFi program.
App Store distribution remains a separate review question.

```sh
xcodebuild -project ios/BLEOnlyProbe/BLEOnlyProbe.xcodeproj \
  -scheme BLEOnlyProbe -destination 'generic/platform=iOS' \
  -derivedDataPath build/ios-ble-pilot CODE_SIGNING_ALLOWED=NO \
  ZINK_BLE_PILOT_CONDITION=ZINK_EXPERIMENTAL_BLE_PRINT \
  ZINK_BLE_APP_NAME='Select BLE Pilot' build
```

Omit `CODE_SIGNING_ALLOWED=NO` and use your development team to build an
installable package. The pilot condition applies only to the standalone app
target. The normal build has no BLE print UI, and the embedded Share extension
stays read-only in either build. The pilot uses the same bundle identifier as
the standalone control and its own private job journal, separate from
Select Probe's app and Share extension.

For the first authorized physical trial:

1. Use a small, known image and one awake Select with paper loaded.
2. Open **Prepare one BLE print** and choose a photo. In Build 5 and later,
   **Rotate left** and **Rotate right** turn the photo 90° at a time before
   layout and show the resulting JPEG preview. Tap **Save photo for printing**.
   The exact prepared JPEG and its settings remain in a private draft while
   the Select is unavailable, including across app relaunch.
3. Tap **Find a Select** and choose the intended printer. The pilot runs the
   identity and readiness checks in sequence and binds the draft only after
   they pass. If the clock is the only blocker, choose **Sync printer clock**,
   confirm **Sync clock only**, then tap **Check printer again**.
4. Choose **Review one-sheet print** and inspect the saved preview. **Print
   one sheet…** opens a separate confirmation with **Cancel**. The final
   **Print one sheet** tap spends the persisted authorization before the
   session begins. The coordinator verifies the binding and full readiness
   again before it sends any print command. Keep the review open during
   transfer.
5. Check the final protocol outcome and
   whether the expected photo physically emerges. **Last print attempt** and
   **Share last print report** remain available after reopening the pilot.
   An uncertain attempt stays blocked. Where a printer job ID and baseline were
   saved, **Check outcome without printing** can observe it after relaunch.
   **Prepare another attempt** is available only after a proved pre-submission
   stop. It creates a new reviewable draft with the same verified JPEG and
   keeps the earlier attempt's outcome. A new one-sheet confirmation is required.

The normal and opt-in Build 2 packages compiled for generic iPhone. Inspection
confirmed that the print UI is only in the opt-in main app. The signed pilot
app and embedded extension also passed signature and entitlement inspection.
Both link CoreBluetooth and omit ExternalAccessory and accessory protocol
declarations. Simulations completed exact 30,374-byte and 554,670-byte
transfers and exercised interruption, process death and duplicate prevention.
Build 3 adds the standalone clock action and durable report. Clock sync opens
a fresh BLE connection, matches firmware, model and the canonical printer ID,
and checks that the Select is idle and its queue is empty. If the clock is
already valid or another condition blocks sync, the action ends before a write.
Success requires both the printer acknowledgement and a status reply with the
invalid-clock flag clear. If the connection ends during the update, the pilot
reports whether the write may have reached the printer or was acknowledged,
and leaves any next action to the user.

The protected journal keeps the outcome separately from the optional BLE
diagnostics. An interrupted session can reopen with a conservative outcome
even if the app closed before diagnostics were saved. Reports use byte counts
and printer counters and omit the JPEG, raw frames and printer identifiers.
Read-only recovery records its own diagnostics alongside the original transfer.

The [clock simulator tests](../ble-clock-tests/main.swift) exercise the exact
session setup and update, mismatched printers, and interruptions on either
side of the acknowledgement. The [authorization and history tests](../authorization-tests/main.swift)
verify the journal after abrupt exits, including completion before the report
can be saved. The opt-in Build 4 main app adds the guided photo and printer
flow, resumable preparation before connecting, and plain-language progress.

### Physical validation without paper

On 2026-11-20, signed pilot Build 4 on an iPhone was tested against an HP
Sprocket Select running firmware `G1L1FA2105AR`. With the Select off, discovery
ended with “No Select found during this scan” and made the scan button available
again. After power-on, the pilot found a service candidate and identified the
invalid clock as the only readiness blocker. The separately confirmed native
BLE clock write was acknowledged and the subsequent status reply cleared the
flag. A fresh read-only check reported the printer ready.

The iPhone prepared a 768 × 1152 JPEG with **Preserve edges** and quality 100,
saved it in the pilot, and reopened the same preview and settings after the
app process was terminated and relaunched. One subsequent scan found no
printer. Its power state during that scan was unconfirmed, and the photo
remained available in the pilot. After the Select was woken, a new scan
identified it as the last verified printer. Fresh read-only checks passed,
and the app bound the saved JPEG to the verified unit. The review displayed
one sheet, the saved layout, and 4:4:4 chroma sampling for that JPEG.
Canceling the final confirmation returned to the review with the draft still
available and the displayed BLE counters unchanged.

The phone had previously discovered this Select. First-time onboarding, image
upload, and one-sheet BLE printing still need a physical trial. This session
sent no print command or JPEG to the printer.

### Simulator validation

The [screen tests](Tests/BLEPilotUITests.swift) exercise the regular pilot
view and journal with a synthetic photo and an in-memory printer. The fixture
supplies Bluetooth discovery and packet I/O so the clock and print coordinator
still process the real protocol. It is compiled only into the opt-in debug
simulator app. Run against an explicitly chosen, booted simulator:

```sh
xcodebuild -project ios/BLEOnlyProbe/BLEOnlyProbe.xcodeproj \
  -scheme BLEOnlyProbe -destination "platform=iOS Simulator,id=$SIMULATOR_ID" \
  -derivedDataPath build/ios-pilot-ui -parallel-testing-enabled NO \
  CODE_SIGNING_ALLOWED=NO ZINK_BLE_PILOT_CONDITION=ZINK_EXPERIMENTAL_BLE_PRINT test
```

The screen tests cover a saved draft reopening after a failed connection,
clock sync, a canceled confirmation, a fresh review after a proved stop,
an uncertain job blocked after reopening, and a rotated draft reopened for
review. The Photos picker and native BLE discovery use iOS services outside
this fixture.
