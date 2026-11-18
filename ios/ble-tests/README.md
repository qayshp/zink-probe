# Offline BLE read-only checks

`BLEReadOnlyCheck` is a Foundation-only, fixed-request experiment. It has no
CoreBluetooth dependency and no way to submit a caller-provided opcode. The
native owner supplies an actual platform write limit, calls `nextWrite(now:)`,
performs that single write with response, and calls `didWrite(now:)` only on
success. Each received characteristic notification is passed whole to
`receive(_:now:)`; arbitrary slices of one notification must not be passed as
separate packets. Errors or user/lifecycle cancellation call `stop()`.

The sequence is BLE IF_CONFIG, firmware, Select SuperModel, connection-local
maximum negotiation, status, capability discovery/download, and final status.
Only the capability handle returned in that experiment can be read. There are
no print-start, resource-allocation, image-upload, time, settings, fast-mode or
pairing-control operations. Security and busy/error states are reported as raw
diagnostics; a successful check is not print readiness or print authorization.

The core has a 60-second overall deadline and 10-second exchange deadlines,
72-request/64-capability-page bounds, 4 KiB assembled-message/64 KiB table bounds,
256 KiB cumulative receive and 16 KiB transmit bounds, and no retry or
resynchronization. BLE sequence numbers start at one; the final packet has bit
7 set. Receive ACKs are emitted only at the negotiated nonfinal-fragment period,
and share the same single native write-in-flight rule. Notifications that precede
write completion are held until the native callback. Terminal success tolerates
cleanup/late callbacks; failures and cancellation remain terminal.

Run from the repository root:

```sh
swiftc ios/BLECore/*.swift ios/ble-tests/main.swift -o build/ios-ble-tests
build/ios-ble-tests
```

The executable currently performs **3,054 checks** with an in-memory simulated
peer. It covers packet-budget variants, negotiated ACK periods including zero,
notification/write callback order, ACK callback races, JSON/TLV and paged
capability files, exact fixed request bytes, sequence and size errors,
every-stage rejection/timeouts, cancellation before and after request delivery,
partial responses, remaining-length inconsistencies and page exhaustion.

These tests perform no Bluetooth access and establish no physical iPhone BLE
session, fresh pairing behavior, sustained image transfer or print success.
