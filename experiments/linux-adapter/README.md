# Linux adapter validation — 2026-10-24

The [Linux RFCOMM adapter](../../LINUX_ADAPTER.md) and `zink-linux-check` command
are implemented. Simulated jobs and failure tests run through actual local socket
I/O and the adapter's selector readiness code. No physical print is part of this
milestone.

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
from the unresolved authentication step. The Mac's existing Select record was
checked and reported paired but **not connected** during this investigation.

All **41 Linux adapter tests passed on ColorBerry**, including native D-Bus message
construction and both complete simulated JPEG jobs. This establishes execution
on an ARM64 Linux host in addition to the CI platforms.

Initial real-device work found the exact protocol-reported Classic address in
bounded BR/EDR discovery. The printer was not previously paired to ColorBerry.
One one-shot pairing command could not find the expired discovery entry. A
subsequent discovery/pairing session kept discovery active, observed the printer
connect briefly, and ended with BlueZ `org.bluez.Error.AuthenticationCanceled`.
No successful pairing, bond, RFCOMM protocol exchange or Linux print is claimed
from those attempts. Controller power, trust and existing pairing records were
not changed; temporary discovery was stopped when its client exited.

The new read-only CLI was run against the expected MAC and protocol ID. Its
BlueZ preflight refused the unavailable/unpaired target before creating the
RFCOMM socket. The private `linux-readonly.jsonl` therefore contains **zero HP+
application frames**. The failed prerequisite must be resolved before the real
identity/status/configuration/reconnection checks can validate this adapter.
Raw discovery/pairing logs, device identifiers and protocol traces remain private.
The [sanitized preflight audit](validation-2026-10-24.json) records zero transmitted
application bytes and no successful printer sessions. Its original trace uses
UTC timestamps; the report date here uses America/Los_Angeles.

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
