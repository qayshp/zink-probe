# Read-only iOS accessory feasibility probe

A small native SwiftUI app, separate from the Python engine. It asks whether an
independently signed app can discover the Select through ExternalAccessory and
open a session using a protocol actually advertised by that accessory. It is not
a Share extension or a print implementation.

## Safety and scope

- No print engine, image payload, settings commands, network service or BLE writes.
  Build 2 adds exactly one fixed firmware-identity request; see
  [the transport trace](TRANSPORT_TRACE.md). Passive tests still send nothing.
- Session opening necessarily involves iOS-managed accessory negotiation and may
  wake/connect the printer. "Zero application bytes transmitted" does not mean
  zero Bluetooth traffic or zero transport-level state changes.
- Explicit per-accessory/per-protocol test buttons; no automatic session attempts.
- Only the intersection of the app's four declared HP protocols and the live
  accessory's advertised protocols can be opened. No arbitrary protocol entry.
- Both streams are scheduled and opened. Only **Read firmware once** writes the
  fixed seven-byte request; no arbitrary command input or automatic retry exists.
- A session closes after 10 seconds, 4096 received bytes, stream error/end,
  disconnection, manual stop, or leaving the foreground. No background mode.
- Apple accessory picker filters names containing “sprocket”; use iOS Settings
  for a renamed printer. The picker can establish pairing, not just scan.
- This is connected-accessory enumeration, not a raw Bluetooth radio scan.

## Build and run

Open `SelectAccessoryProbe/SelectAccessoryProbe.xcodeproj` in Xcode. Choose your
own development team and a unique bundle ID if necessary, select a physical
unlocked iPhone, and Run. No signing team or provisioning profile is committed.
The source currently uses `org.qayshp.zink.SelectAccessoryProbe`; this is our own
app identity, not an impersonation of HP's app.

Unsigned build (also run by CI):

```sh
xcodebuild -project ios/SelectAccessoryProbe/SelectAccessoryProbe.xcodeproj \
  -scheme SelectAccessoryProbe -destination 'generic/platform=iOS' \
  -derivedDataPath build/ios-probe CODE_SIGNING_ALLOWED=NO build
```

A simulator compile cannot validate MFi/accessory authorization or Bluetooth.
The real-device test needs the printer awake nearby. Avoid competing Sprocket
sessions on other apps/computers. Do not assume an empty list proves rejection.

1. Open **Select Probe**, approve its Bluetooth permission if prompted.
2. Refresh connected accessories; if needed use Apple's picker or pair/connect
   in iOS Settings, return to the app, and refresh.
3. Confirm the listed accessory is your Select. Tap **Passive test** for a
   no-write test, or **Read firmware once** for the bounded identity request.
4. Wait for the bounded observation to finish; test another advertised protocol
   separately if needed. No photo or paper is needed.
5. Review/share the diagnostic report, or retrieve the app's `Documents/probe.txt`
   using Xcode/device tools. Reports are private and may contain accessory names
   and raw unsolicited data. They omit serial numbers, are capped at 64000 text
   characters, and are replaced on the next launch. No automatic upload occurs.

## Interpret the result carefully

| Result | Establishes | Does not establish |
| --- | --- | --- |
| App builds/installs | Toolchain, signing and installation | Accessory visibility/authorization |
| Accessory listed | iOS exposes that accessory to this app | Permission to open a protocol |
| Protocols empty | No protocol is advertised at this instant | Permanent incompatibility; authentication may still be pending |
| Session initializer returns nil | Session creation failed | A definitive authorization failure; contention/state can matter |
| Session object exists | Initialization succeeded | Streams actually opened |
| Both streams report `openCompleted` | Accessory session access for this signed app/protocol | That the desktop HP+ protocol works here or printing is supported |
| Incoming bytes | Unsolicited data arrived | A response to a printer command; none was sent |

Do not treat the four protocol names as four proven Select transports. They were
found in the official app's manifest; its exact Select transport remains to be
established. Declaring a name is not evidence of manufacturer authorization.

Sources: [project IPA research](../IOS_EXPLORATION.md),
[Apple EASession](https://developer.apple.com/documentation/externalaccessory/easession),
[Apple protocolStrings](https://developer.apple.com/documentation/externalaccessory/eaaccessory/protocolstrings),
[Apple accessory guidance](https://developer.apple.com/accessories/).

## Validation record — 2026-10-26

- Local generic iPhone build: passed (Xcode 27.1 SDK, iOS minimum 16).
- Local iOS Simulator compile: passed; no simulated Bluetooth claim.
- Signed physical-iPhone build: passed using local development credentials.
- Initial installation rejected its provisioning profile (`0xe8008012`).
  Rebuilding with the actual iPhone destination and automatic provisioning/device
  registration enabled resolved installation. Exact cause of the first rejection
  was not independently established.
- Installation on the user's iPhone 16 Pro Max: confirmed by `devicectl`.
- Remote launch: denied because the phone was locked. No app report existed yet.
- Subsequent user-operated physical test: accessory discovery and both session
  streams opened successfully; details below. No incoming bytes were observed.
- Build 1 source review: no accessory output write API, printer-command payload,
  or print-engine dependency. Build 2 adds only the fixed identity request
  described in [TRANSPORT_TRACE.md](TRANSPORT_TRACE.md).
- Dedicated CI compiles the iPhone target without signing. It cannot validate
  Bluetooth, pairing, manufacturer authorization, or a physical session.

This app does not alter the existing desktop queues or printer settings. The
user's authorization here is for this read-only feasibility test, not printing.

## Physical session result — 2026-10-26

Evidence: user supplied the app's diagnostic report from the installed iPhone
build (commit `01eca78`). This is physical-device evidence, not simulation.

| Time (UTC) | Observed event |
| --- | --- |
| 18:16:35–18:17:17 | Connected-accessory enumeration returned zero |
| 18:17:19–18:17:27 | Apple accessory picker completed without error; accessory became visible |
| 18:17:36 | A second picker invocation reported error domain EABluetoothAccessoryPickerErrorDomain, code 2; accessory remained visible |
| 18:17:39 | EASession created for `com.hp.protocol.lifestyle`; both streams requested open |
| 18:17:40 | Input and output each reported `openCompleted` |
| 18:17:49 | User stopped session; both streams had opened, RX=0, application TX=0 |

Reported identity: name `Sprocket Select`, manufacturer `HP`, model `HPISPSLE`,
firmware `G1L1FA2105AR`, hardware `4138`. The only advertised protocol in this
report was **`com.hp.protocol.lifestyle`**, not `com.hp.protocol.bahama`.
Protocol labels must not be inferred from Android model-family names.

This establishes accessory-session access for our independently signed app on
this iPhone and this printer/firmware, without additional manufacturer
coordination during this test. It does not establish unrestricted access for
other app identities, production distribution, other devices, or other firmware.
The second picker error did not prevent the later successful session; its exact
cause was not investigated. Initial empty enumeration was not permanent denial.

No application-level command was transmitted and no unsolicited bytes arrived.
Thus HP+ frame compatibility, request/response behavior, image transfer and
printing over this iOS session remain untested. Next useful research is a
source-backed comparison of the iOS transport framing with our established
read-only status/identity commands before adding any narrowly bounded request.
This result does not authorize printing or broad command probing.

GitHub iOS compile check for `01eca78`: run `40376389014` passed. The real-device
session result above comes from the user report, not that build check.
