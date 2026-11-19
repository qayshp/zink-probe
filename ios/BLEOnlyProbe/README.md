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
profile is committed. The current build number is 2 and deployment target is iOS 16. Installation
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

1. Use a small, known image and one awake Select with paper loaded. If the
   Select reports that it needs clock sync, use the separate clock-sync action
   in Select Probe and close that session before returning to the pilot. This
   pilot only reads printer readiness. BLE clock sync and first-time onboarding
   are separate validation items.
2. Open **Prepare one BLE print**, prepare one photo, scan and tap the intended
   printer, then tap **Check printer and save draft**. Draft binding uses the
   canonical printer identity plus the selected JPEG's exact bytes and settings.
   This step sends only preflight traffic.
3. Review the saved photo and the one-sheet confirmation. The final **Print one
   sheet** tap spends the persisted authorization before the session begins.
   The coordinator verifies the binding and full readiness again before it
   sends any print command. Keep the confirmation screen open during transfer.
4. Check the acknowledged image byte count, the final protocol outcome and
   whether the expected photo physically emerges. **Share BLE pilot report**
   exports the byte counts and protocol outcome without the JPEG, raw frames,
   or printer identifiers. An interrupted or uncertain
   attempt stays blocked. Where a printer job ID and baseline were saved,
   **Check job outcome read-only** can observe it after relaunch. If the outcome
   remains uncertain, check the actual paper before taking any further action.

The normal and opt-in Build 2 packages compiled for generic iPhone. Inspection
confirmed that the print UI is only in the opt-in main app. The signed pilot
app and embedded extension also passed signature and entitlement inspection.
Both link CoreBluetooth and omit ExternalAccessory and accessory protocol
declarations. Simulations completed exact 30,374-byte and 554,670-byte
transfers and exercised interruption, process death and duplicate prevention.
The pilot has been built and signed for development. Physical evidence still
covers BLE identity, status, capabilities and strict readiness. The one-sheet
trial is the remaining check for physical BLE job allocation, image upload
and ejection.
