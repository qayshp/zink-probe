# Native BLE coordinator adapter — offline milestone

Implemented 2026-11-18 after the [four successful physical read-only
checks](ble-tests/PHYSICAL_VALIDATION.md). The complete single-job coordinator can
now run over the Select's BLE packet transport against an in-memory peer. A
CoreBluetooth owner is compiled into the main app and Share extension, but
**real BLE submission is unconditionally disabled**. This milestone did not
connect to a printer, allocate a physical job, upload an image, install an app,
or print. The existing External Accessory print UI and the isolated Select BLE
Check product are unchanged at that milestone. The subsequent
[Build 16 read-only UI](BLE_PREFLIGHT.md) exposes this owner's preflight in both
contexts; physical results and readiness refusals are recorded separately.

## Composition and authorization

`BLECoordinatorSession` supplies the same composition to the simulated packet IO
and the native facade: `SubmissionCoordinator`, `JobJournal`, the immutable saved
JPEG/binding, `SingleJobFrameGate`, `AccessoryStreamPump`, `AccessoryStreamDriver`
and `BLESubmissionDuplex`. The simulator does not substitute a different upload
planner or duplicate-prevention policy.

The stream interface inside this composition still uses virtual HP+ frames.
`BLESubmissionDuplex` removes that internal envelope and sends only protocol
payloads with the BLE sequence envelope. Assembled replies are rewrapped for the
existing coordinator. **HP+ stream headers never go to GATT.** This preserves the
existing exact-frame authorization and durable pending-write boundaries without
duplicating them in a second coordinator.

The `.singleJobSubmission` duplex policy only admits the transport's known print
opcodes; it grants no authorization. The upstream permit gate still checks every
PrintStart, properties and FileWrite against the exact saved JPEG, one-copy
request and committed pending journal record before any fragment can be queued.
Native read-only preflight/recovery use the independent `.readOnly` policy.

`NativeBLEAdapter.submitOnce` first calls
`BLESubmissionAvailability.requireLiveSubmission()`, which always throws.
There is no user setting or runtime switch that changes this. The complete native
authorized-session composition is compiled behind that guard, but cannot reserve
or consume a permit, construct a Bluetooth manager, connect or transmit. Tests
verify this refusal with a valid bound draft and an unchanged journal.

Changing transports does not create a new identity or store. The canonical
16-byte **protocol device ID** and existing journal determine binding and device
claims. A CoreBluetooth peripheral UUID routes a connection; it cannot bypass a
pending/uncertain job. Saved IDs and spent attempts remain blocked across process
restart and across accessory/BLE compositions. Recovery uses fresh identity and
firmware checks plus read-only observation; it never reconstructs an upload plan.
This remains local duplicate prevention, not a printer-side exactly-once promise.

## Native API and lifecycle

The main-run-loop `NativeBLEAdapter` exposes:

- `preflight(peripheralID:expectedDeviceID:expectedFirmware:update:)` — a fresh
  full readiness preflight, capable of producing the existing `VerifiedPrinter`.
- `recover(peripheralID:id:journal:update:)` — read-only observation of a saved,
  possibly submitted job. It cannot resend its image.
- `submitOnce(peripheralID:reviewed:journal:update:)` — disabled before any side
  effect, as described above.
- `stop(_:)` — terminal cancellation without reconnect/retry.

The initial offline milestone exposed no UI. Build 16's [read-only UI](BLE_PREFLIGHT.md)
now calls preflight; submission and recovery still have no new UI. A caller must
supply a deliberately chosen
peripheral from discovery and the expected firmware/binding; opening a view must
not start a session. The owner retrieves that exact peripheral UUID, connects,
discovers only the known service and TX/RX characteristics, subscribes to RX, and
uses write-with-response on TX. It never accesses the pairing-control
characteristic, requests fast BLE, changes the clock or writes printer settings.
Constructing the adapter does not create a central manager.

Each operation creates a fresh native owner. Callbacks must match its current
central, peripheral, service and characteristic identities. Terminal paths clear
delegates, cancel the connection, release timers and close once. Build 16's UI
calls `stop` on cancellation, dismissal and backgrounding. There is no background
execution or restoration behavior.

## Packet pacing and limits

The bridge completes IF_CONFIG `0a 01 00` before opening either virtual stream.
It parses interface, little-endian protocol MTU and acknowledgement period.
Only one GATT packet may be outstanding. A successful native callback permits
the next packet; only the validated protocol reply acknowledges a print request.
A reply arriving before the last native callback is held until that callback and
any required host ACK writes finish. Inline simulated callbacks are serialized
until the virtual writer has returned its accepted-byte count.

The requested downstream ACK period is zero. A device `[00]` packet is therefore
rejected rather than treated as a native callback, response or instruction to
replay a fragment. For fragmented incoming replies, the negotiated acknowledgement
period controls the host's `[00]` writes; those also require native callbacks.

These limits are independent:

| Bound | Behavior |
|---|---|
| Native write-with-response size | Each outgoing packet fits the reported platform limit |
| Negotiated protocol MTU | Each packet also fits this limit; bootstrap is 20 bytes |
| Sequence space | At most 127 fragments, with one sequence byte per packet |
| Message payload | At most 4096 bytes and the sequence-space capacity |
| Effective upload maximum | `min(peer maximum, 4096, 127 × (min(platform limit, protocol MTU) − 1))` |

The coordinator samples the transport bound after negotiation and **before its
durable claim or PrintStart**. For example, a 4096-byte peer maximum with 20-byte
packets yields a 2413-byte message bound. Upload chunks are planned to that bound;
the bridge never silently truncates or splits a protocol request into new requests.
Existing accessory callers retain their previous default message bound.

The BLE composition permits at most 90 seconds for authorization/connection/
discovery/subscription and IF_CONFIG together. Native authorization has a
30-second bound and each connection/discovery/subscription stage has ten seconds.
IF_CONFIG and subsequent exchanges each have ten seconds. The bridge and normal
coordinator retain a 300-second overall bound; recovery retains its shorter
coordinator bound. Accessory-only callers retain their ten-second opening default.
The bridge additionally bounds callback/ACK queues, 4096-byte reassembly and
32 MiB in each traffic direction. Invalid or reversed monotonic time stops it.

An accepted virtual write means its whole authorized message was queued, not that
all GATT callbacks or the printer acknowledgement have arrived. Any subsequent
write failure, timeout, cancellation or disconnect reaches the durable coordinator.
A possibly accepted mutation stays uncertain and blocks resubmission. No fragment
retry, reconnection, automatic restart or transport fallback is implemented.

Virtual stream byte counts include internal HP+ headers. The bridge's TX queued,
TX acknowledged and RX counters measure actual BLE packet bytes, including
sequence/ACK bytes. These counts must not be presented as interchangeable.

## Offline verification and remaining gates

The [BLE submission suite](ble-submission-tests/README.md) drives the shared
composition with a deterministic packet peer, independently reconstructs outgoing
messages and compares the complete saved JPEG. It covers packet/ACK combinations,
callback order, interruptions, malformed traffic, missing responses, durable
recovery, process death and duplicate attempts. Existing coordinator, journal,
accessory authorization and read-only BLE tests remain enabled. CI runs the new
suite, typechecks the adapter against the iOS SDK with extension API restrictions,
and builds both main and Share targets without signing or device access.

Local validation on 2026-11-18 passed the new suite: 16 MTU/ACK/callback-order
transfer combinations, 63 mutating packet boundaries with five interruption types,
all 53 fragments of the first MTU20 upload message, and three abrupt process exits.
It compared an exact 30,374-byte JPEG and a valid 554,670-byte JPEG with added
comment segments for the large inline-callback case. The executable's check
total includes low-level packet assertions rather than that many independent
scenarios; encoder byte counts can differ between OS releases.
Existing coordinator, journal, one-job authorization, accessory/binding, Share-flow
and 3,054 read-only BLE checks also passed. The native adapter typechecked for
iOS 16 with extension API restrictions, and the unsigned generic iPhone build
compiled both app and Share targets successfully. No simulator or phone was
launched for these checks.

The previous four physical tests prove short read-only exchanges only. They do
not validate this new native owner's lifecycle, fragmented physical transfers,
throughput, BLE allocation/upload/printing, first-time pairing, or App Store
eligibility. The simulated printer is not firmware emulation. No physical success
is inferred from these tests or from a generic iPhone build.

Build 16 adds [read-only UI/lifecycle integration and physical checks](BLE_PREFLIGHT.md)
with submission still blocked. Successful strict readiness and a separately
authorized one-job BLE print remain later gates. Printing would require a source
change to the unconditional
availability guard as well as an explicit saved-photo confirmation; it cannot be
enabled by selecting an existing UI option.
