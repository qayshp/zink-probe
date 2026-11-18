# BLE-only control app and Share extension

**Select BLE Check** is a separate read-only control experiment, using fresh bundle
identifiers `org.qayshp.zink.BLEOnlyProbe` and
`org.qayshp.zink.BLEOnlyProbe.Share`. It can coexist with Select Probe without
replacing that app or touching its saved drafts and job journal.

Both targets compile only their tiny UI owner, the shared
[`BLEProbe.swift`](../SelectAccessoryProbe/BLEProbe.swift) CoreBluetooth owner,
and [`BLEReadOnlyCheck.swift`](../BLECore/BLEReadOnlyCheck.swift). They have no
External Accessory declarations or linkage, no print core, no saved jobs, no
photo preparation and no background mode. The Share extension is offered for
one shared image but deliberately never loads that image. Opening either UI
starts no scan, connection or application write.

The control is useful because a BLE connection in the existing Select Probe
product could coexist with an already-declared External Accessory route.
Success in this separate product would show that the fixed BLE check works
without linking or declaring External Accessory. It still would not establish
fresh-pairing behavior, BLE job acceptance/upload/printing, or App Store approval.
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
profile is committed. Build number is 1, deployment target iOS 16. Installation
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
installation and package checks do not establish a physical connection. The
user deferred the phone tests until later; no radio session or printer command
was started by this control during development.
