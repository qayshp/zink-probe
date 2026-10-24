# macOS adapter validation — 2026-10-24

The portable engine now has a native `MacOSRfcommStream` adapter. The new
`zink-macos-check` command exercises the same stream and `FramedSession` used by
the job engine, with an additional read-only request gate. The final two-session
hardware check passed on the existing Select. **No print was requested or sent.**

## Implementation

- Native IOBluetooth imports are lazy, so the portable package still imports and
  tests on Linux and Windows without PyObjC or Bluetooth hardware.
- Async channel opening and async writes use Cocoa delegate callbacks. A task
  pumps the main-thread run loop while asyncio waits; the stream belongs to one
  event loop and rejects use on a background thread.
- One adapter instance per Classic address may own an active channel within a
  process. This guard prevents another instance stealing it; it is not a lock
  across other applications or computers.
- Native writes respect the negotiated RFCOMM MTU. An HP+ frame can span native
  writes; received fragments are buffered and decoded by the shared framing layer.
- Native write completion only means handed to Bluetooth hardware. The portable
  engine still requires the matching printer reply and checks acknowledged offsets.
- Open, write, and read waits have deadlines. Failures/cancellation close the
  owned channel, with no automatic reconnect or resend. Receive buffering is
  capped at 64 KiB. Closing is idempotent and waits up to two seconds for the close
  callback, reporting unconfirmed cleanup through `close_error`.
- Native API entry points and `closeChannel` are synchronous calls even though
  opening/writing continue asynchronously. Python deadlines cannot interrupt a
  hung OS call; callback waits are bounded. No pairing record or other Bluetooth
  link is intentionally closed or changed.
- The raw stream can support a job engine. The diagnostic command wraps it in
  `ReadOnlySession`, which applies the existing allowlist before every write,
  permits capability file reads only on a discovered handle, and exposes no
  JPEG input, submission, settings-write, or arbitrary-command option.

The I/O contract was checked against the installed Apple SDK headers and PyObjC
method metadata: `IOBluetoothDevice.openRFCOMMChannelAsync`,
`IOBluetoothRFCOMMChannel.writeAsync`, and their delegate callbacks. See Apple's
[open API](https://developer.apple.com/documentation/iobluetooth/iobluetoothdevice/openrfcommchannelasync(_:withchannelid:delegate:))
and [write API](https://developer.apple.com/documentation/iobluetooth/iobluetoothrfcommchannel/writeasync(_:length:refcon:)).

## Run read-only checks

Install the existing macOS extras and obtain the protocol-reported Classic MAC
and fixed device ID from a trusted `zink-probe probe` result. A CoreBluetooth BLE
UUID is not the Classic address.

```sh
python -m pip install -e '.[macos,dev]'
zink-macos-check --address AA:BB:CC:DD:EE:FF --device-id YOUR_32_HEX_DIGIT_DEVICE_ID
```

The placeholders must be replaced with the selected printer's actual values.
The command rechecks the model and exact device ID before reading capabilities,
configuration, status, job list, and counters. It defaults to two fresh sessions;
`--sessions 1` or `3` is also available. Each session has a 90-second overall
deadline and 15-second individual operation/request deadlines. The existing
macOS Bluetooth permission and Classic pairing are required; this command does
not attempt to bypass or modify them.

There is a two-second gap between explicitly requested sessions. Immediate reopen
failed on this unit even after a close callback, while three pairs with that gap
succeeded. This is an observed reconnection constraint, not proof of whether the
remaining teardown time is in macOS or printer firmware. Library callers should
also allow that gap when deliberately creating a replacement stream. The runner
stops at the first failure; the gap does not introduce automatic retries.

Raw traces and full identities are written to a new private, exclusive-create
JSONL file under ignored `logs/`. Standard output omits the MAC/device ID and
custom printer name. `--log` selects another new trace file.

## Hardware evidence

The final command (`20261024T183522-macos-adapter-9169b9f7.jsonl`, retained privately)
completed two connections through the native async adapter:

| Observation | Both sessions |
|---|---|
| Exact expected protocol identity | Matched |
| Model / firmware | Select `0x48D3` / `G1L1FA2105AR` |
| Maximum application message / RFCOMM MTU | 1000 / 1006 bytes |
| Capability table | 227 bytes, read successfully |
| Printer / queue / flags | Idle / empty / zero |
| Battery | 100%, reported charging |
| Printed-page counter | 12 before and after |
| Calibration-card counter | 2 before and after |
| Configuration | Unchanged within and between connections |
| Requests / replies | 35 / 35 per session |
| Application wire TX / RX | 266 / 870 bytes per session |
| Channel close callback | Observed; no close error |

No `PrintStart`, image `FileWrite`, job-property write, configuration write, reset,
queue resume, or cancellation request appeared. This establishes real read-only
communication and deliberate reconnection. It does **not** establish a physical
print through the new adapter, bulk-upload throughput, recovery from an actual
mid-print radio loss, or Linux/Windows Bluetooth compatibility.

## Development failures and fixes

1. The first check aborted after the read-only `0A 02` session request. Explicit
   formal-protocol declaration on the Python delegate replaced PyObjC's buffer
   metadata with a bare `void *`, yielding an integer instead of a byte buffer.
   The delegate now uses the framework's inferred metadata, as the existing probe
   does. A native metadata regression checks both the input-buffer qualifier and
   its length argument; conversion failures are also caught inside the callback.
2. The next check completed one snapshot but immediate reopening inherited a
   close notification. Close now waits for its callback before detaching the
   delegate and ending the run-loop pump.
3. Immediate reopening still timed out in the subsequent run. Adding the explicit
   two-second inter-session gap produced three successful pairs, including the
   final command. No failed request was resent within any session.

The independent [offline audit](audit_trace.py) checks every attempted outgoing
HP+ frame against the existing read-only allowlist and correlates returned file
handles. Across all six traces, **281 attempted requests** were allowlisted;
280 replies were observed. The one missing reply belongs to the initial crashed
session, not a print operation. Eight complete snapshots across the later runs all
retained counters 12 and 2. See the [sanitized evidence](validation-2026-10-24.json).
Raw trace contents and printer identifiers are intentionally not published.

```sh
python experiments/macos-adapter/audit_trace.py logs/*-macos-adapter-*.jsonl
```

## Simulated validation and remaining boundary

The native facade tests run on all three CI operating systems without touching a
radio. They exercise actual adapter methods and callback delivery against the
existing simulated printer: MTU splitting, partial reads, events arriving before
native write completion, open/write return errors, callback errors, timeouts,
disconnects, cancellation, receive-buffer overflow, close confirmation, wrong
identity, scoped read permissions, and stopping the session sequence on failure.
Both CAL-02 and quality-100/4:4:4 CAL-03 complete through the adapter facade with
exact reconstructed JPEG bytes. A lost PrintStart reply leaves the engine's job
uncertain and is never resent. These jobs remain wholly simulated.

The macOS CI legs additionally install PyObjC and check delegate metadata without
opening Bluetooth. Existing diagnostics, calibration senders, and their spent
physical-print claims are unchanged. General photo preparation, native Linux and
Windows transports, and print-queue/IPP/PAPPL integration remain future work.

Local validation: **420 tests passed**, including 32 adapter cases and the native
metadata check; all 11 separate calibration transcript tests passed. Lint and
formatting checks passed. The built wheel contains the current adapter and diagnostic entry point.
The CI matrix runs the portable cases on Python 3.11
and 3.14 for macOS, Linux, and Windows; its native-only tests are separately
enabled on the macOS legs.
