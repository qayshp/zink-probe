# Bounded native iPhone BLE check — Build 15

Implemented 2026-11-18. The app and Share extension now have an independent
CoreBluetooth diagnostic. A separate **Select BLE Check** control app and Share
extension contain only this diagnostic, without External Accessory declarations
or linkage. The existing photo-submission coordinator is not
connected to this BLE path. No BLE job allocation, image upload or printing is
implemented or authorized by this diagnostic.

## Question and decision boundary

Can our own iPhone app, and separately its Share extension, discover the Select,
connect to its protocol service and complete identity/status/capability reads
using CoreBluetooth instead of External Accessory?

The [Android/firmware investigation](../experiments/ble-printing/README.md)
establishes a credible BLE printing route in source plus successful Mac BLE
reads. The subsequent [physical iPhone checks](ble-tests/PHYSICAL_VALIDATION.md)
establish read-only access in the tested processes and pairing environment;
actual BLE print acceptance remains untested. This check addresses the
iPhone-access question without creating a job.

A successful report establishes access and parser/transport compatibility for
that signed process, phone, printer and connection environment. It does not
establish fresh pairing, universal connection reliability, sustained transfer,
print acceptance, physical output, App Store approval or manufacturer permission.
A main-app success is not a Share-extension success. The primary test should use
the [isolated control app](BLEOnlyProbe/README.md), whose fresh bundle identifiers,
Bluetooth permissions and minimal source list remove the existing app's eager
External Accessory enumeration/declarations from the experiment. Its extension
does not even load the shared image. The phone's existing pairing history remains
a confound for first-time onboarding; do not unpair/reset it for this milestone.
The original Select Probe Build 15 screens remain useful comparison controls.
Busy/error/clock-invalid
status is reported without trying to change it; this is not print preflight.

## Controls and protocol boundary

Constructing/opening the screen does not create a central manager, prompt for
Bluetooth, scan or connect. **Scan for Select over BLE** explicitly starts a
service-filtered ten-second scan; peripherals already connected to the phone
with that service are also considered. Up to 32 candidates are retained.
Advertisement SuperModel data, when present, must identify `0x48d3`; the protocol
model read must subsequently confirm the Select. The user selects one candidate.

The adapter discovers only the known service and TX/RX characteristics, subscribes
to RX notifications, and writes only to TX with response. It neither reads the
pairing/control characteristic nor requests fast BLE/interface switching. The OS
may still perform Bluetooth authorization, pairing/encryption or connection work.
Opening a connection can wake a printer. This is not an HCI traffic capture.

The core itself generates the only possible application requests:

| Stage | Exact protocol bytes | Meaning |
|---|---|---|
| Configure | `0a 01 00` | Connection-local BLE configuration, downstream ACK period zero |
| Firmware | `04 01` | Firmware identity |
| Model | `04 09` | Select SuperModel must be `0x48d3` |
| Setup | `24 00 10` | Host receive-message bound 4096; report peer maximum/security |
| Before status | `08 01 02 03 04 05 06 07 09` | Flags, state, battery, progress, current job, power, queue, hosts |
| Discover | `2a` | Obtain capability-table read handle/encoding |
| Read capabilities | `28 <returned-handle> 01` | Read only the handle returned by discovery; bounded pagination |
| After status | Same status request | Compare reported state after reads |

Capability discovery creates a read handle for the feature table; it is not
print-job or resource allocation. There is no arbitrary command entry or
caller-supplied opcode interface. No device-ID/MAC/serial query is needed by this
experiment. A fixed read sequence does not grant print authorization or bind a
saved job. The existing iAP print path remains separate.

## Framing, callbacks and lifecycle

`BLEPacketCodec` adds/removes one sequence byte per packet, starting at one with
the high bit set on the final fragment. Each notification is passed as a whole
packet. The packet encoder respects the smaller of the printer's negotiated
protocol MTU and the native `maximumWriteValueLength(for: .withResponse)` limit.
These are separate limits. IF_CONFIG is decoded as opcode, interface, two-byte
little-endian MTU and ACK period; the ACK byte is index 4.

One native write may be outstanding. Its successful write-with-response callback
permits the next write; it is not treated as a protocol response. Notifications
that arrive first are held until the write callback. Nonfinal receive fragments
get `00` ACK packets only at the negotiated period; ACK writes use the same
pacing. The diagnostic requests are short, so tests of its general fragment
encoder do not establish sustained image-upload behavior on hardware.

Unknown sequences, malformed responses, unexpected opcodes/handles, failed writes,
disconnects and deadlines stop without retry or resynchronization. Bounds are:

- Ten seconds per protocol exchange and sixty seconds for the protocol sequence.
- Ninety seconds from explicit connection selection, including setup; each
  connection/discovery/subscription stage has a ten-second deadline.
- Thirty seconds waiting for initial Bluetooth authorization/state, then a
  ten-second scan, with a forty-five-second overall scan-setup bound.
- 4096 assembled message bytes, 127 sequence fragments, 64 capability chunks,
  64 KiB capability table, 72 requests, 256 KiB received and 16 KiB transmitted.

Stop, screen dismissal and app/Share backgrounding cancel the connection and
release timers/delegates. Transient inactivity during a system permission/pairing
prompt does not itself cancel the BLE check. A fresh scan/manager is required
after a terminal connection attempt, preventing late disconnect callbacks from
an earlier attempt from terminating a new one. No restoration or background
Bluetooth mode is enabled.

The report contains decoded firmware/status/capabilities and queued versus
acknowledged GATT byte counts. It omits device UUIDs, addresses, serials and raw
identity frames. Native errors use domain/code rather than uncontrolled localized
descriptions. The user's candidate names appear only in the local selection UI.
The report stays in the view and can be explicitly shared; no automatic upload
or change to existing saved-print data occurs.

## Physical test procedure

1. Keep the Select awake and nearby. End any active printer test in another
   process/host. Do not infer that another device caused a failure without evidence.
2. Open the separate **Select BLE Check → Scan for Select over BLE**.
   Approve Bluetooth access if prompted. Wait for the scan to finish.
3. Select the intended printer with **Run read-only BLE check**. Keep the screen
   visible until a terminal report. Save/share the report before leaving the screen.
4. After that connection has closed, share one photo from Photos to **Select BLE
   Check** in the app row/More menu. Repeat the scan and diagnostic there. The
   photo is not loaded or transmitted by this control extension.
5. Compare main-app and Share results separately: discovery, subscription, firmware,
   model, native write limit, negotiated maximum/security, status and capabilities.

If a comparison is useful, Select Probe Build 15 exposes the same diagnostic
under **Read-only BLE check** in the main app, and **BLE check** in its Share
toolbar (also **Connection test → Read-only BLE check**). It still declares the
working External Accessory protocols elsewhere in that app, so its result has
a narrower independence claim than the isolated product.

An empty scan or missing accessory does not establish rejection or permanent
incompatibility. A denied permission has a different diagnostic from Bluetooth
off, discovery timeout, subscription failure or protocol refusal. The diagnostic
does not automatically toggle Bluetooth, alter pairing or disconnect other hosts.
Report a failed stage rather than trying an unbounded reset sequence.

## Validation and current outcome

- **3,054 offline checks passed**, using only an in-memory peer. They exercise
  platform packet limits, MTU 20/514, ACK periods 0/1/2/7, callback order, every-stage
  cancellation/rejection/deadlines, fragmented notifications, capability JSON/TLV
  pagination, malformed fields and message/table/byte/page bounds.
- The core also passes when compiled alongside the existing PrintCore and
  IdentityWire sources; it typechecks for the iOS 16 deployment target.
- Existing native-accessory/durable-binding and one-job authorization/interruption
  suites passed after integration. No hardware was accessed by those tests.
- Unsigned iPhone app/extension compilation passed. Both signed Build 15 targets
  built, and `devicectl` confirmed installation of the app on the paired iPhone.
  Existing bundle identifiers/team were retained; no uninstall/data reset occurred.
- The separate BLE-only app and extension also built unsigned and signed. Binary
  linkage checks confirm CoreBluetooth and no ExternalAccessory; built plists
  contain no External Accessory protocols or background modes. `devicectl`
  confirmed installation of **Select BLE Check Build 1**, beside the working app.
- A generic simulator compile of Select Probe also passed; no simulator was
  booted or launched and no Bluetooth result is inferred from that compile.
- **Physical tests on 2026-11-18 passed in both main apps and both Share
  extensions.** Each independently completed the fixed sequence: firmware
  `G1L1FA2105AR`, model `0x48d3`, 227-byte capability table, 40 GATT TX bytes
  acknowledged through eight callbacks, and 314 RX bytes. Before/after status
  matched within each run: power 1, idle/empty, current job 0, clock-invalid flag 1.
  Battery was 99% in the first three runs and 98% in the final isolated Share run.
  The clock flag was reported and left unchanged. The isolated app and its Share
  extension passed without External Accessory linkage/declarations. See the
  [physical result record and evidence limits](ble-tests/PHYSICAL_VALIDATION.md);
  these are observations from
  iPhone Mirroring, not an exported application log or HCI capture.
  No job allocation, image upload, print, clock sync or persistent printer-setting
  change was performed. Existing pairing history was retained, so never-paired
  onboarding and BLE printing remain separate validation gates.

The new headless tests and iOS typecheck are included in
[iOS CI](../.github/workflows/ios-probe.yml). CI can compile the native owner with
extension-only API restrictions and verify the isolated bundles' framework/plist
boundary, but cannot establish physical Bluetooth access.
See [offline test commands and API](ble-tests/README.md).

## Sources

- [Apple CoreBluetooth](https://developer.apple.com/documentation/corebluetooth):
  central/peripheral model and Bluetooth purpose-string requirement.
- [Maximum write length](https://developer.apple.com/documentation/corebluetooth/cbperipheral/maximumwritevaluelength(for:)):
  per-write-type platform limit.
- [Writing characteristic data](https://developer.apple.com/documentation/corebluetooth/cbperipheral/writevalue(_:for:type:)):
  write-with-response callback/error semantics.
- [Central initialization](https://developer.apple.com/documentation/corebluetooth/cbcentralmanager/init(delegate:queue:options:)):
  main-queue delegate behavior with a nil queue.
