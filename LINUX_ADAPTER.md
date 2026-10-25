# Linux Bluetooth adapter

2026-10-24. `LinuxRfcommStream` connects the portable engine to an HP Sprocket
Select through a Linux RFCOMM socket. `zink-linux-check` exposes only read-only
printer inspection. This is a transport milestone, not an installed OS print
queue or a claim of physical printing through the portable engine.

## Install and check

Use Python 3.11+ on Linux, a Bluetooth controller that supports BR/EDR (Classic),
BlueZ, and a printer already paired on that controller:

```sh
python -m pip install -e '.[linux]'
zink-linux-check --address AA:BB:CC:DD:EE:FF --device-id YOUR_32_HEX_DIGIT_DEVICE_ID --adapter hci0
```

Replace the placeholders with the **Classic MAC reported by the printer protocol**
and its fixed 16-byte protocol device ID from a trusted earlier probe. Do not use
a macOS CoreBluetooth UUID, identify a printer solely by name, or substitute the
simulator's ID. The command verifies the Select model and expected identity again
after connecting, before proceeding to capabilities/configuration/status.

The default is two fresh connections with a two-second gap. `--sessions 1` or `3`
is also supported. A connection failure ends the sequence; the gap is not an
automatic retry. Individual open/read/write/request deadlines default to 15
seconds, and each full inspection has a 90-second deadline. Both are configurable
through `--timeout` and `--session-timeout` (positive, at most 300 seconds).

The Linux optional dependency is `dbus-fast>=5,<6`; it is imported only during
native opening. The core package and simulator still require neither D-Bus nor
Bluetooth. No PyBluez extension, raw HCI socket, serial-device binding, `sudo`,
system service, or Bluetooth configuration edit is performed by the adapter.
Kernel/distribution policy can still deny access and is reported as an error.

## Read-only preflight and inspection

The adapter reads BlueZ's cached objects through one
`org.freedesktop.DBus.ObjectManager.GetManagedObjects` call. It selects the exact
public address, requires `Paired=true`, `Blocked=false`, and a powered parent
controller, then binds the RFCOMM socket to that controller's address. If the
printer is known on several controllers, `--adapter hciN` is required rather than
silently selecting one. The temporary D-Bus connection is closed after inspection.

It does not invoke `Pair`, `Connect`, `Disconnect`, `StartDiscovery`, `Set`, or
change `Trusted`, `Pairable`, controller power, or rfkill state. Initial discovery
and pairing belong to the user's Linux Bluetooth manager. A cached `Paired`
property is a prerequisite, not a guarantee that the stored key still works or
that the printer is reachable; the native connection and protocol identity check
must also succeed.

The diagnostic command uses `ReadOnlySession`, which validates every application
request against the existing allowlist **before socket I/O**. Capability-file
reads are scoped to handles returned by the printer. It reads negotiated message
limits, identity/firmware, capabilities, status/battery, job/queue state,
configuration and page/calibration counters. Configuration/counters are compared
within and between connections. It has no image, print, settings-write, reset,
resume, cancel or arbitrary-command option.

Raw frames and identities go to an exclusive, private JSONL file under ignored
`logs/`, or a new path specified with `--log`. Standard output omits the printer
MAC, device ID and custom name. The raw stream itself is an I/O implementation,
not a policy boundary: applications must deliberately choose `ReadOnlySession`
for diagnostics or `FramedSession` plus `JobEngine` for a separately authorized
job. No real-printer submission CLI is introduced here.

## Socket and lifecycle behavior

- A nonblocking `AF_BLUETOOTH / SOCK_STREAM / BTPROTO_RFCOMM` socket opens the
  known Select HP+ channel **2**. Channel 1 is not used and no channel scan occurs.
- The selected asyncio loop supplies readable/writable notifications. The
  adapter belongs to one loop, rejects reuse after close, and allows one active
  stream per target address **within this process**. This is not a lock against
  other programs, controllers or computers.
- Partial sends advance by the exact accepted byte count. `EAGAIN`/interrupted
  I/O waits for readiness; it does not restart the application frame. Arbitrary
  read fragmentation and coalesced frames are handled by `FramedSession`.
- A successful send means accepted by the local kernel, not acknowledged by the
  printer. The engine retains its matching-reply and durable-intent rules.
- Failed, timed-out or cancelled operations close the owned socket without
  reconnecting or resending. EOF also closes it. Close removes selector watchers
  before releasing the descriptor so late callbacks cannot target a reused fd.
  No device-wide BlueZ disconnect is sent; other connections are not deliberately
  closed.
- Calls accept at most 64 KiB. The default host-side write chunk is 4 KiB; Linux
  RFCOMM handles link segmentation. `mtu=null` in diagnostics is intentional: this
  implementation does not measure the radio MTU. `native_writes` counts send
  attempts, including would-block attempts; `tx_bytes` counts bytes accepted by
  the socket. Neither count is a physical-print receipt.

The default Linux selector loop is supported. A custom event loop must implement
`add_reader`/`add_writer`. The Windows selector used in tests is a local-socket
test harness, not a Windows Bluetooth implementation.

## Library use for read-only diagnostics

```python
import asyncio
from zink_probe.jobs.diagnostics import ReadOnlySession, inspect_printer
from zink_probe.jobs.linux import LinuxRfcommStream
from zink_probe.trace import Trace

async def check(address, expected_device_id):
    trace = Trace("logs/new-linux-check.jsonl")
    stream = LinuxRfcommStream(address, adapter="hci0", trace=trace)
    session = ReadOnlySession(stream, trace=trace)
    try:
        async with asyncio.timeout(90):
            await stream.open()
            return await inspect_printer(session, expected_device_id, trace)
    finally:
        await session.close()
        trace.close()
```

For complete before/after and inter-session validation, prefer the CLI's shared
`adapter_checks` runner. The macOS CLI now uses that same runner with its original
behavior and tests preserved.

## Simulation and platform tests

`tests/test_linux_stream.py` connects the actual adapter's readiness/read/write
logic to real local sockets. Only Bluetooth bind/connect and BlueZ metadata are
substituted. A peer drives the existing simulated printer across those sockets.
It covers partial writes, would-block/backpressure, fragmented reads, events,
deferred connection errors, timeouts/cancellation, EOF, descriptor/lease cleanup,
ambiguous/unpaired/blocked/powered-off devices, wrong printer identity, read-only
allowlisting and two fresh inspections. BlueZ tests assert the sole metadata
method and cleanup after failures/cancellation.

Both CAL-02 and quality-100/4:4:4 CAL-03 complete simulated jobs with exact JPEG
reconstruction. Losing a PrintStart reply leaves an uncertain job with one
allocation attempt and no replay. These fixtures consume no paper.

The [CI matrix](.github/workflows/ci.yml) runs the socket-facade tests on macOS,
Linux and Windows with Python 3.11 and 3.14. Ubuntu additionally installs the
Linux extra and checks native socket constants and D-Bus message construction,
without a bus connection or Bluetooth hardware. Linux hardware validation and
its limits are recorded in [the experiment report](experiments/linux-adapter/README.md).

## Troubleshooting and remaining scope

- **Not known / not paired:** discover and pair the exact Select in the Linux
  Bluetooth manager. Unpaired discovery entries can disappear when scanning
  ends; keep discovery active while pairing if necessary.
- **Powered off / network down:** inspect controller power and rfkill. This CLI
  reports the condition rather than changing it.
- **Permission denied:** check distribution Bluetooth policy and pairing. The
  adapter does not suggest running an entire driver as root.
- **Timeout / refused / unreachable:** check printer power, range and whether
  another app holds the connection. A failed job is not automatically replayed.
- **No Bluetooth/RFCOMM support:** check the Linux kernel, controller, and Python
  socket build. Successful simulation cannot supply missing radio hardware.

BLE discovery, automatic pairing, dynamic SDP channel selection, Windows native
transport, OS queues and IPP/PAPPL integration remain separate work. Physical
bulk-upload throughput, printing and mid-print radio-loss behavior through this
Linux adapter require separately authorized hardware acceptance tests.

Primary interfaces: [Python RFCOMM address format](https://docs.python.org/3.11/library/socket.html),
[BlueZ RFCOMM protocol](https://github.com/bluez/bluez/blob/master/doc/rfcomm-protocol.rst),
[BlueZ device properties](https://github.com/bluez/bluez/blob/master/doc/org.bluez.Device.rst),
and [dbus-fast's asyncio lifecycle](https://dbus-fast.readthedocs.io/en/latest/message-bus/aio-message-bus.html).
