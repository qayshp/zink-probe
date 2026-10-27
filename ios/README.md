# iOS Select probe and Share preparation experiment

A native SwiftUI app and embedded Share extension, separate from the Python
engine. The main app supports passive connection tests, fixed firmware/status
reads, a bounded read-only preflight and an explicitly selected clock-sync action.
The extension prepares a shared photo and now tests its own accessory connection.
Neither target exposes print submission. Historical build notes below retain the
evidence and boundaries for each milestone.

## Safety and scope

- No print submission or arbitrary-command input. Photo preparation stays local.
- Main-app clock synchronization is a separately labeled write action. All other
  main-app diagnostics are read-only; the Share connection test only permits
  passive streams or a single fixed firmware request.
- Opening a session involves iOS-managed accessory negotiation and may wake the
  printer. Zero application bytes does not mean zero Bluetooth traffic.
- All session tests require an explicit tap. Sharing a photo does not connect.
- The main app declares four HP protocols; active Select queries require
  HPISPSLE/lifestyle. The extension declares lifestyle only.
- Sessions are bounded and close on cancellation or lifecycle departure. Simple
  reads/passive sessions have a ten-second limit; full preflight/clock-and-preflight
  has a sixty-second overall bound with ten-second exchange deadlines.
- The main app's picker filters names containing “sprocket.” The extension only
  enumerates connected accessories; connect in the main app/Settings if necessary.
- Enumeration is not a raw Bluetooth radio scan. Pairing does not ensure a current
  accessory connection. No background execution mode is requested.

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


## Physical firmware query succeeded — build 3

The user confirmed the separate **Read firmware once** button sent exactly seven
bytes and received a valid twenty-byte HP+ reply identifying `G1L1FA2105AR`, matching
accessory metadata. The app closed the session on success. See the
[exact frames and evidence limits](TRANSPORT_TRACE.md#physical-identity-exchange-succeeded--build-3).
This is real iOS request/response validation, not a print test.

## Read-only status screen — build 4

Tap **Refresh printer status** under HPISPSLE / lifestyle. Each tap opens one
bounded session and sends only `48502b01050801020306`: status request 08 with
fields 01 (32-bit system flags), 02 (printer state), 03 (battery percentage),
and 06 (battery/power state). These are the established desktop protocol fields;
iOS identity framing was physically verified before adding this request.

The screen shows battery percentage, charging/external-power state, named printer
state, alerts and raw codes/flags. “Charging / external power” deliberately does
not assert that battery current is flowing at full charge. Alerts include known
flags and error states such as paper jam, tray open, overheat and battery error.
“No alerts in queried fields” does not claim a complete diagnosis of hardware.
Unknown codes and flag bits remain visible. Transport/protocol failure is shown
as a failed refresh, not a printer fault. A refresh clears the previous values;
success carries a timestamp and remains explicitly a last snapshot, not live
monitoring. No polling, retries, settings writes, printing, or new setup command.

The status reply must contain each requested field exactly once, in any order.
Unknown tags, missing/duplicate/truncated fields, invalid battery percentages,
wrong response opcodes, extra frames and excess data stop the attempt. Unknown
state/power values are preserved. Existing 10-second / 4096-byte bounds and
partial-write handling apply. A complete status response closes the connection.

Validation: Swift offline tests passed, including every split of a status frame,
one-byte partial transmission without replay, reordered fields, missing/duplicate
fields, invalid battery values and unknown status bits/codes. Signed physical
build and installation succeeded. Physical status values were subsequently confirmed in the user report below;
no hardware result is inferred from installation or synthetic test data.

## Physical status validation — 2026-10-26

User-supplied build-4 report confirms two successful status exchanges:

| Time UTC | TX | RX | Decoded result |
| --- | --- | --- | --- |
| 19:39:04 | `48502b01050801020306` | `48502b010c090100000000020103410601` | Battery 65%, power 1 (in use), state 1 (idle), flags 0 |
| 19:39:42–43 | `48502b01050801020306` | `48502b010c090100000000020103400601` | Battery 64%, power 1 (in use), state 1 (idle), flags 0 |

Each request sent 10 bytes, received 17 and closed on a validated response.
Both exact replies are covered by Swift regression tests at every two-part
frame split. The same report confirms a bounded passive test and two successful
firmware queries between these status reads. These are separate sessions, not
an automatic retry loop. No print or settings commands were sent.

Repeated picker results with domain EABluetoothAccessoryPickerErrorDomain/code 2
preceded connection. The local Apple iPhoneOS27.1 SDK EAAccessoryManager.h enum
maps 0=already connected, 1=not found, **2=cancelled**, 3=failed. This reports a
cancelled picker outcome; the log alone does not identify who/what cancelled it
or establish sleeping, radio contention, permission denial or a printer fault.
At 19:38:57 the picker succeeded, the accessory appeared, and subsequent requests
worked. Discovery/reconnection usability remains a separate issue to investigate.

The one-percent reported battery change is not a measured energy cost of these
requests; rounding, estimate updates and elapsed use are possible explanations.
Flags 0 means none of the queried system flags were set, not a comprehensive
health test. Charging and fault-state iOS observations remain untested; their
mappings come from the established protocol and synthetic tests.

Build-4 commit `155c0d7` passed the dedicated iOS CI workflow. Status hardware
validation comes from the user's report, not CI. No new device commands were sent
while recording this result.

## Offline photo preparation — build 5

**Prepare a photo offline** opens the Photos picker, layout/JPEG options, safe-area
preview, and Files export. No submission is connected. See
[PHOTO_PREPARATION.md](PHOTO_PREPARATION.md) for supported inputs, Apple/Python/
Android comparisons, encoder differences and validation limits.

## Build 6: JPEG details and offline Share extension

The photo screen now labels the control **JPEG compression quality**, defaults to
**Maximum · 100**, and explains that it changes compression rather than dimensions.
The preview reports exact JPEG bytes and chroma sampling parsed from the encoded
JPEG SOF header, not guessed from the quality setting. The six physical iPhone
exports previously examined used 4:2:0 at 90/95 and 4:4:4 at 100; this observation
is not an Apple API guarantee. Quality 100 remains lossy.

**Prepare for Select** is an embedded Share extension. From Photos or another app,
share one image, choose More if necessary, then Prepare for Select. It reuses the
same offline layout, quality, decoded-JPEG preview, safe-area guide and Save to
Files controls. Done dismisses the extension. It accepts image data subject to the
existing preparation limits (50 MB encoded, 80 MP source, bounded decode), and
rejects unsupported formats. Host app representations can vary; large photos may
also encounter iOS extension memory limits. Multiple-image jobs, app handoff,
background jobs and printing are not implemented. There is no accessory transport
code in the extension and no App Group is required for this in-extension workflow.

Validation: local signed iPhone app + embedded extension build passed; offline
orientation, color, layout and metadata checks passed. Added sampling tests cover
4:4:4, 4:2:2, 4:2:0, grayscale, other factors, every truncated prefix and invalid
segment lengths. CI builds the embedded extension through the app dependency.
Physical Share-sheet activation and Files export remain unverified for build 6:
the iPhone was unavailable at build time. This is a development prototype, not an
App Store distribution or review claim. No printer commands were sent.

## Next printing milestone: offline Swift upload sequencing

See [PrintCore](PrintCore/README.md) for the native upload state machine and
Python/Swift golden-trace tests. This component is not linked into the app or
Share extension yet. Durable job journaling is now implemented and tested offline. Its integration,
full preflight, framed stream I/O and completion observation remain required
before enabling real submission.

## Build 7: bounded read-only preflight

The main app now has **Run read-only preflight** under the Select's lifestyle
protocol. Keep the printer awake, connect with Apple's picker if needed, then tap
it and inspect the local report. It checks identity, capabilities and readiness,
including an empty queue and page counters. Each exchange is limited to 10 seconds;
the whole run is limited to 60 seconds. It does not print or change persistent
settings. A failed check stops without retry. See [PrintCore](PrintCore/README.md)
for the exact checks, connection-local negotiation and test coverage.

Build 7's signed app and embedded offline Share extension were installed on the
physical iPhone successfully. Local framing/preflight, durable-journal and legacy
identity/status/upload regression tests passed. Physical preflight testing is
pending the user's report; installation alone is not protocol validation.

Build 10 physical result: the user's explicit clock-sync action was acknowledged,
the time-invalid flag cleared (1 → 0), and the complete read-only preflight passed
on the Select. See [the evidence record](PrintCore/README.md). This validates
connection/setup/readiness queries, not iOS print submission. No paper was used.

## Build 11: test the connection inside the Share extension

The Share extension now includes a manual **Connection test** screen. From Photos,
share one image → **Prepare for Select** (under More if needed) → **Connection test**
in the preparation screen's toolbar. Sharing a photo does not open an accessory
session automatically. The extension runs in its own process, not in Select Probe;
main-app success does not establish extension access.

1. Keep the Select awake. Close any active connection test in Select Probe.
2. In the extension's Connection test, tap **Refresh connected accessories**.
3. If the Select is visible, tap **Open streams without writing**. Wait for its
   ten-second close, or close it manually. Both streams opening establishes session
   access; application TX must remain zero.
4. Tap **Read firmware once**. It sends the same fixed seven-byte firmware request
   validated in the main app, with a ten-second/4096-byte bound and no retry.
5. Copy the report or use **Share connection report**. The report labels itself as
   originating inside the Share extension. It omits serial number and device ID.

If no Select is visible, connect through the main app/Settings, close the main-app
session and return to Share. The extension does not provide another pairing picker.
A missing accessory or nil session is inconclusive about cause: OS connection state,
app access and another session may matter. The test does not guess which one.

Sessions close on explicit stop, screen departure, extension-host inactivity and
controller dismissal. This must still be physically checked; an extension can be
terminated by iOS, and a ten-second test says nothing about long print transfers
or background reliability. No App Group/handoff or attempt to launch the main app
is used. The photo preparation/export workflow remains available.

The extension declares lifestyle protocol support and a Bluetooth usage description
in its own Info.plist. It builds with APPLICATION_EXTENSION_API_ONLY=YES. The SDK
headers do not mark the enumeration/session APIs used as extension-unavailable;
successful compilation is not a promise of runtime access or App Store approval.
Apple's extension lifecycle restrictions and EASession behavior are documented at:
- https://developer.apple.com/library/archive/documentation/General/Conceptual/ExtensibilityPG/ExtensionOverview.html
- https://developer.apple.com/documentation/externalaccessory/easession

Validation: signed iPhone app/extension build passed, existing IdentityWire framing
and partial-write tests passed, embedded-bundle metadata inspected. Binary symbol
inspection confirms that upload, journal, clock-sync and preflight cores are absent
from the extension. It has no print or settings action. Physical extension visibility,
stream opening and firmware response remain pending the user's test report.
