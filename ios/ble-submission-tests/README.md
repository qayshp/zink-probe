# Offline BLE submission and interruption tests

These tests exercise the same `BLECoordinatorSession.authorizedSubmission`
composition used by the native adapter's currently disabled submission branch:
the saved binding, single-use print permit, durable journal, submission
coordinator, frame gate, stream driver and BLE packet bridge. Only `BLEPacketIO`
is replaced with a deterministic memory peer. No CoreBluetooth manager is
created, no physical device is accessed and no paper is used.

Run on macOS from the repository root:

```sh
mkdir -p build
swiftc ios/PrintCore/*.swift ios/BLECore/*.swift ios/BLESubmission/*.swift \
  ios/SelectAccessoryProbe/NativeBLEAdapter.swift \
  ios/ble-submission-tests/main.swift -o build/ios-ble-submission-tests
build/ios-ble-submission-tests
```

The suite generates an upright, sRGB 768 × 1152 JPEG, saves it in a real SQLite
journal, then compares every received JPEG byte with that exact saved image.
The memory peer receives only BLE sequence packets; the internal virtual `HP+`
headers must never appear on its GATT boundary. Protocol replies use the existing
`SimulatedPrinter`, not a firmware emulator or captured-printer replay.

The transfer matrix covers protocol MTUs 20 and 514; native write limits 20 and
512; negotiated acknowledgement periods 0, 1, 2 and 7; and protocol notifications
both before and after the native write callback. A valid unknown capability TLV
makes the simulated feature reply long enough to require period-7 ACKs at MTU20.
Inline callback delivery is tested separately, including a second valid JPEG
enlarged beyond 500 KiB with legal comment segments. That extra byte volume
exercises thousands of inline packet callbacks; it is not a different raster or
an image-quality experiment. Native writes never overlap, and the exact saved
JPEG and one-copy PrintStart are checked after completion.

Additional scenarios cover:

- A peer advertising 4096-byte messages at ATT20: the shared coordinator caps
  each message at 127 × 19 = 2413 bytes before making a durable print claim, and
  the full exact-byte job succeeds without changing or replaying a prepared
  message after transmission starts.
- Invalid transport-message limits, rejected before a durable print claim or
  PrintStart, and invalid negotiated MTU/ACK/native-limit values.
- Every mutating packet boundary in the 512-byte native-limit transfer, with
  refusal before acceptance, disconnect after acceptance, host cancellation,
  a missing write callback and an asynchronous native error. Every fragment of
  the first 1000-byte upload message at MTU20 is independently disconnected too.
- Lost PrintStart, properties, upload-chunk and final-upload responses; wrong
  upload offsets; foreign job IDs; extra pages; and calibration-counter changes.
  Uncertain results retain their durable device claim and cannot be authorized
  again.
- The read-only transport policy refusing an accidentally supplied, otherwise
  authorized upload coordinator before a PrintStart reaches the peer.
- Missing readiness/configure/callback events, malformed sequences, duplicate
  notifications, wrong printer identity, paused/time-invalid status, reversed
  monotonic time, native errors and harmless late callbacks after terminal close.
  Missing/error callbacks on the downstream BLE ACK write itself are checked
  separately: no duplicate ACK or print request is emitted.
- Native setup delayed by fifteen seconds, plus the ninety-second setup bound.
  The BLE composition does not inherit the stream adapter's shorter opening
  deadline.
- Three real child-process abrupt exits: committed PrintStart intent, a partial
  BLE FileWrite message, and durable final upload acknowledgement. A new journal
  owner refuses resubmission. Where recovery is possible it sends only reads;
  no saved JPEG bytes are loaded into another upload plan. A lost final reply
  stays uncertain, while an acknowledged upload can complete through attributable
  read-only observation.
- Two processes racing for the same durable authorization; independent journal
  objects; one-use permit consumption; and refusal to replay a BLE attempt through
  the existing accessory coordinator.
- Shared-session construction failure and the public native `submitOnce` action
  rejecting before authorization or Bluetooth access. The latter leaves the
  unsubmitted binding and journal untouched.

The number printed by the executable includes low-level packet-bound checks,
not just independent scenarios. Passing these tests establishes host-side
composition, framing and conservative failure behavior against this simulated
peer. It does not prove native callback timing, real BLE job acceptance, sustained
radio throughput, physical print output, or first-time phone pairing.

The earlier [read-only physical BLE results](../ble-tests/PHYSICAL_VALIDATION.md)
remain a separate milestone. Real BLE submission is still disabled; existing
External Accessory printing is a separate transport and authorization path.
