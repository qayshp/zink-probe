# Windows adapter validation — 2026-10-25

The [Windows RFCOMM adapter](../../WINDOWS_ADAPTER.md) and `zink-windows-check`
are implemented. This milestone authorizes simulated jobs and read-only printer
checks, not physical printing.

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
printer remained unpaired. Discovery or authentication traffic can be observed
by the printer; no conclusion about its wake cause follows from that alone.

Raw identifiers, discovery logs and protocol traces remain private. Pairing
success and real-printer read-only results, if obtained, are recorded below.
Physical printing, bulk upload throughput and mid-print loss remain unvalidated.

## Software checks

Local macOS verification: **568 passed, 2 skipped**, plus lint and formatting.
The skips are the Linux-only and Windows-only native dependency checks. Surface
adds actual ARM64 Windows execution and native interface evidence. The CI matrix
runs the portable tests on macOS, Linux and Windows with Python 3.11 and 3.14;
Windows additionally executes the native DLL smoke test in the regular suite.

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
