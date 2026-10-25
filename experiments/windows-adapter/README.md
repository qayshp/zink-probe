# Windows adapter validation — 2026-10-25

The [Windows RFCOMM adapter](../../WINDOWS_ADAPTER.md) and `zink-windows-check`
are implemented. This milestone authorizes simulated jobs and read-only printer
checks, not physical printing.

**Two real read-only Select connections from Surface now pass.** The user
completed pairing through Windows settings, after which the existing adapter
connected, inspected the printer, closed and reconnected without code changes.

## Host and native interface evidence

The user confirmed Surface was near the Select. SSH reached the expected
Windows host. It runs Windows build `10.0.26300`, ARM64 Python 3.12.10, a running
Bluetooth service and a Qualcomm FastConnect 7800 Bluetooth adapter. A separate
project environment under the user's temporary directory was created; no system
Python, global driver, Bluetooth service or OS policy was changed.

The actual Windows DLLs loaded successfully. Radio information was read with
the native API; structure sizes were 30 bytes for `SOCKADDR_BTH`, 520 for radio
information and 560 for device information. An actual Bluetooth RFCOMM socket
was created, set nonblocking, bound to the local radio and closed successfully
without connecting to a remote device.

All **41 Windows adapter tests passed on Surface**, including real DLL binding
checks, complete simulated CAL-02 and quality-100/4:4:4 CAL-03 jobs, partial I/O,
failure/cancellation handling, read-only allowlisting and two fresh simulated
inspections. These used the default Windows Proactor event loop. Native DLL
tests use local sockets, not a radio connection.

## Initial printer checks

Before discovery, `BluetoothGetDeviceInfo` returned `0x80070057` for the exact
Select address, while returning success for an existing cached device. A bounded
Classic inquiry (timeout multiplier 8, nominal 10.24 seconds) found the exact
protocol-reported Select address. Cached lookup then returned an unpaired record.
The diagnostic CLI refused this prerequisite before creating a socket and sent
**zero HP+ frames**. This confirms the distinction between radio discovery,
pairing, and application-protocol communication.

One-time host pairing was attempted separately from the read-only CLI under the
user's existing project-specific setup authorization. The exact-device callback
received numeric-comparison method 3 with remote no-input/no-output capability
3 and authentication requirements 4. It allowed only that target's Just Works
confirmation; it did not guess a PIN or accept unrelated devices. The first
attempt returned Windows error **1244 (`ERROR_NOT_AUTHENTICATED`)**, and the
printer remained unpaired. One further bounded setup attempt with callback
logging reached the same method/capability exchange and failed with the same
code. The user was asked to try the normal Windows pairing UI; neither attempt
establishes a cause for the authentication failure. Discovery or authentication
traffic can be observed by the printer; no conclusion about its wake cause
follows from that alone.

The [sanitized frame audit](validation-2026-10-25.json) preserves that initial
preflight refusal with zero transmitted protocol frames, alongside the successful
follow-up below. Raw identifiers, discovery logs and protocol traces remain private.

## Successful physical read-only checks

After the user reported successful pairing through Surface's normal Windows UI,
the native cached-state check confirmed `authenticated=true` and
`connected=false`. All deployed Python source hashes and the private target
selection file were checked against the verified local checkout before use.
The implementation remains the code from `8c6ca18`; no adapter fix was needed.

The existing CLI then completed two fresh read-only inspections, using Surface's
ARM64 Python 3.12.10 and the default Windows event loop. The trace was copied
back and independently audited offline. It was not edited or redacted in place;
the public JSON contains only a sanitized summary and its SHA-256 digest.

| Observation | Both Windows sessions |
| --- | --- |
| Exact expected printer identity | Matched |
| Model / firmware | Select `0x48D3` / `G1L1FA2105AR` |
| Negotiated maximum application message | 1000 bytes |
| Capability table | 227 bytes |
| Status / queue / flags | Idle / empty / zero |
| Battery | 100%, reported charging |
| Printed-page counter | 12 before and after |
| Calibration-card counter | 2 before and after |
| Configuration | Unchanged within and between connections |
| Requests / matching replies | 35 / 35 per connection |
| Application wire TX / RX | 266 / 870 bytes per connection |
| Native send calls | 35 per connection |
| Local socket closure | Closed without error; fresh reconnect succeeded |

The independent [frame auditor](../macos-adapter/audit_trace.py) accepted all
**70 outgoing requests** and correlated all **70 replies**, with no error or
pending request at the end. There were no PrintStart, image FileWrite,
job-property writes, configuration writes, reset, queue-resume or cancellation
requests. Capability FileRead requests were scoped to handles granted during
the corresponding session. Total application-framed traffic was 532 bytes sent
and 1740 bytes received; these counts exclude Bluetooth/link overhead.
An additional offline consistency check confirmed no partial frame remained
in either direction, each session contained exactly 35 complete outgoing and
35 complete incoming frames, and trace byte counts matched the native socket
counters. The public report was checked against the private selection file to
ensure that neither the target MAC nor fixed device ID was included.

Identity, capability-table data and both configuration snapshots also matched
the earlier successful ColorBerry/Linux results exactly. This comparison uses
the private original traces and exposes no MAC, fixed device ID or custom name.

The complete two-session sequence took about 5.38 seconds, including the intended
two-second gap. This is a small read-only transaction timing, not a print-upload
throughput measurement. Local socket closure is not a separate printer disconnect
ACK. Successful ordinary Windows pairing resolved the prerequisite; it does not
explain why the two earlier programmatic pairing attempts failed.

**Real Windows-to-printer read-only communication and reconnection are now
validated.** Physical printing, bulk upload throughput and mid-print loss through
this adapter remain unvalidated. No print or settings change was performed.

## Software checks

Local macOS verification: **568 passed, 2 skipped**, plus lint and formatting.
The skips are the Linux-only and Windows-only native dependency checks. Surface
adds actual ARM64 Windows execution and native interface evidence. The CI matrix
runs the portable tests on macOS, Linux and Windows with Python 3.11 and 3.14;
Windows additionally executes the native DLL smoke test in the regular suite.

All six CI jobs passed for implementation commit `8c6ca18` in
[GitHub Actions run 40171627043](https://github.com/qayshp/zink-probe/actions/runs/40171627043):
macOS, Ubuntu and Windows, each with Python 3.11 and 3.14. Windows passed 567
tests with three platform/dependency skips; the other portable suites passed
566 with four skips. After installing the platform extras, macOS passed two
additional native-binding checks and Linux passed its D-Bus/Python-capability
check. Every job also passed the eight earlier image-research tests, eleven
calibration transcript tests, both simulated-job CLI runs, offline image
preparation/preview and wheel building. Local dependency consistency also passed.
The successful hardware follow-up changes only documentation and audit evidence;
the tested application code is unchanged.

The socket facade replaces only Bluetooth bind/connect and cached metadata;
real local sockets carry requests and replies. Simulated jobs reconstruct both
JPEG fixtures byte-for-byte and confirm that a lost PrintStart reply produces
an uncertain job with one allocation and no replay. This is software evidence,
not physical-print acceptance.

## Correction to the earlier Linux investigation

The [Linux report](../linux-adapter/README.md) now records the user's correction:
the phone app was already closed throughout the preceding day, no app was closed
in response to the question, and no deliberate wake action was taken. The
printer was powered on, possibly asleep, and its large front LED came on during
the investigation. The available evidence does not identify which device or
operation woke it, or the cause of the initial Linux pairing cancellation.
