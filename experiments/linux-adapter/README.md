# Linux adapter validation — 2026-10-24

The [Linux RFCOMM adapter](../../LINUX_ADAPTER.md) and `zink-linux-check` command
are implemented. Simulated jobs and failure tests run through actual local socket
I/O and the adapter's selector readiness code. No physical print is part of this
milestone.

**Two live read-only connections from ColorBerry to the Select passed.** The
initial pairing prerequisite was resolved during this session; the adapter code
did not need to change. No physical print was requested or sent.

## Linux host evidence

ColorBerry (an ARM64 Linux host) was brought online near the Select. It has Python
3.11.2, BlueZ, a powered `hci0` controller, and Python's native RFCOMM socket
constants. A project-specific temporary environment was created without changing
the system Python. Its missing `ensurepip` was handled with a local `virtualenv`
bootstrap; the adapter was installed with dbus-fast 5.2.0.

The native `AF_BLUETOOTH / SOCK_STREAM / BTPROTO_RFCOMM` socket was also created,
bound to `hci0`'s actual address and closed successfully as the ordinary user,
without a remote connection. Host kernel: `6.1.31-sun50iw9`, architecture
`aarch64`. Thus basic socket support/binding and access are established separately
from the authentication step. The Mac's existing Select record was
checked and reported paired but **not connected** during this investigation.

All **43 Linux adapter tests passed on ColorBerry**, including native D-Bus message
construction and both complete simulated JPEG jobs. This establishes execution
on an ARM64 Linux host in addition to the CI platforms.

Initial real-device work found the exact protocol-reported Classic address in
bounded BR/EDR discovery. The printer was not previously paired to ColorBerry.
One one-shot pairing command could not find the expired discovery entry. A
subsequent discovery/pairing session kept discovery active, observed the printer
connect briefly, and ended with BlueZ `org.bluez.Error.AuthenticationCanceled`.
Those initial attempts did not establish a bond. The user then closed the phone
app and ensured the printer was awake. The Mac was checked and was not connected.
A new bounded discovery/pairing session succeeded, leaving the Select paired and
bonded on ColorBerry. This sequence does not prove which prior condition caused
the cancellation. One-time host pairing was performed separately from the
read-only CLI, using the user's project-setup authorization. Existing pairings,
controller power and trust flags were not removed or changed; temporary discovery
was stopped when its client exited.

The new read-only CLI was run against the expected MAC and protocol ID. Its
BlueZ preflight refused the unavailable/unpaired target before creating the
RFCOMM socket. That initial private trace contains **zero HP+ application frames**.
After successful pairing, the same CLI completed its two fresh inspections.
Raw discovery/pairing logs, device identifiers and protocol traces remain private.
The [sanitized audit](validation-2026-10-24.json) retains both the initial refusal
and successful connection evidence. Original traces use UTC timestamps; the
report date here uses America/Los_Angeles.

## Successful physical read-only checks

| Observation | Both Linux sessions |
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
| Local socket closure | Closed without error; fresh reconnect succeeded |

The independent [trace auditor](../macos-adapter/audit_trace.py) accepted all
**70 outgoing requests**, correlated all 70 replies, and found no pending
request or error. There were no PrintStart, image FileWrite, job-property write,
configuration write, reset, queue-resume or cancellation requests. Capability
FileRead requests were permitted only for the handles discovered in that session.

The 2-second inter-session gap is inherited from the measured Select teardown
behavior; this test does not establish a minimum Linux reconnect delay. Socket
closure is local-kernel evidence, not an additional printer disconnect ACK.
These results establish Linux read-only protocol communication and deliberate
reconnection. Physical printing, bulk-transfer speed and actual mid-print loss
through this adapter remain untested.

## Tests and evidence boundary

The Linux tests cover:

- Exact-address/controller selection; refusal of missing, ambiguous, unpaired,
  blocked, random-address or powered-off targets.
- Only `GetManagedObjects` on the D-Bus metadata path, with cleanup after
  successful reads, malformed/error replies, bus errors and cancellation.
- Actual selector notifications and socket I/O around partial writes, blocked
  writes, fragmented reads, unsolicited events, EOF and deadlines.
- Socket and selector cleanup, competing owners, single-use connections and
  refusing any resend after partial-write failure.
- Two fresh simulated read-only inspections, scoped capability handles and
  rejection of job mutations before native I/O.
- Byte-exact simulated CAL-02 and quality-100/4:4:4 CAL-03 uploads; a lost
  PrintStart reply leaves one uncertain allocation without replay.

The fake socket facade substitutes only Bluetooth bind/connect; its reads/writes
use real local sockets. It validates the transport implementation, not Linux
Bluetooth interoperability. The hosted CI matrix supplies macOS/Linux/Windows
Python 3.11/3.14 coverage, while ColorBerry adds the ARM64/Python 3.11 execution.
Native Windows Bluetooth support, physical Linux upload/printing and actual
mid-print loss/recovery remain untested.

The first hosted run exposed a Python-build distinction: GitHub's Linux Python
3.11/3.14 builds omit `socket.AF_BLUETOOTH` (ColorBerry's Python includes it).
The adapter already rejected that case; its error now recommends a Python build
with Bluetooth support, and tests explicitly cover either missing constant.
The native dependency smoke test checks real D-Bus message construction and
verifies the installed Python's supported-factory or unsupported-build path
without opening Bluetooth. This is not substituted for the successful native
socket/bind and real-printer evidence above.

Final local verification: **528 passed, 1 skipped** on macOS, **43 Linux adapter
tests passed** on ColorBerry, lint/format checks passed, and installed dependency
consistency passed. The macOS skip is the Linux-only dependency smoke check.
