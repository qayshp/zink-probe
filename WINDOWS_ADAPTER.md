# Windows Bluetooth adapter

`WindowsRfcommStream` connects the portable single-job engine to the Select's
Classic Bluetooth RFCOMM channel 2. `zink-windows-check` exposes only read-only
printer inspection. This does not install an OS print queue.

## Installation and read-only use

Use 64-bit desktop Windows Python 3.11+ (x64 or ARM64), a working Classic
Bluetooth radio, and an already paired Select:

```powershell
python -m pip install -e .
zink-windows-check --address AA:BB:CC:DD:EE:FF --device-id YOUR_32_HEX_DIGIT_DEVICE_ID
```

No optional Python package, vendor SDK, PyBluez build, virtual COM port or
administrator account is needed by the adapter. The implementation uses the
Windows system Bluetooth/Winsock DLLs and Python's socket module. The optional
`.[images]` and `.[dev]` extras are needed only for image preparation and testing.

Use the **Classic address reported by the printer protocol** and its trusted
fixed 16-byte protocol device ID, not a BLE UUID or a name match. The command
verifies the expected identity and Select model after connecting. `--adapter`
accepts a local radio MAC; it is required if the target is paired on multiple
radios. Windows radio identifiers are not Linux `hci0` names.

The default is two fresh read-only connections, separated by two seconds.
`--sessions 1` or `3` is also supported. A failure stops the sequence; it does
not trigger a reconnect/retry. `--timeout` defaults to 15 seconds for individual
I/O/requests, and `--session-timeout` defaults to 90 seconds per inspection.

## Preflight and evidence boundaries

The adapter enumerates local radios and queries the exact device's cached
information with `BluetoothGetDeviceInfo`. It requires `fAuthenticated=true`.
It does not initiate inquiry, pairing, authentication UI, power changes, trust
changes, removal of bonds, or a device-wide disconnect. An earlier pairing is
not proof that a printer is awake or reachable; the socket and subsequent
protocol checks must still succeed. A native metadata error retains its numeric
Win32/HRESULT code. Surface returned `0x80070057` before the device had been
discovered; after discovery the same API returned its unpaired cached record.

Metadata reads execute on a daemon worker so local OS calls do not block the
event loop. Cancellation discards their results and cannot subsequently open a
printer socket. Windows does not expose cancellation of these synchronous
metadata calls: if one stalls, its handles close when the call returns. No
socket I/O runs on that worker and no automatic retry creates another worker.

The shared diagnostic runner uses `ReadOnlySession`, which validates each
application request before I/O. It reads identity, firmware, message limits,
capabilities, battery/status, job/queue state, configuration, and page/calibration
counters. Capability-file reads use only handles granted by that connection.
Counters and configuration must remain unchanged within and between sessions.
The CLI has no image, print, settings, reset, resume, cancel or raw-command option.

Raw traces are created exclusively under ignored `logs/` (or a new `--log` path).
Keep that directory in a user-private location on Windows; access also depends
on its inherited NTFS permissions. Standard output omits the address, fixed ID
and custom printer name. The raw stream itself is not a read-only policy:
applications choose `ReadOnlySession` for diagnostics, or deliberately use the
job engine for a separately authorized submission.

## Socket behavior

- The adapter creates an `AF_BTH / SOCK_STREAM / BTHPROTO_RFCOMM` socket, binds
  to the selected local radio, and opens only the known Select channel 2.
  There is no channel scan or dynamic SDP selection. Generalizing other printer
  profiles requires separate service/channel validation.
- Windows `SOCKADDR_BTH` is **30 bytes with one-byte packing**. Fixed-width
  ctypes definitions supply bind/connect addresses; Python owns the socket
  handle, Winsock initialization, nonblocking mode, send/recv and closure.
  It does not depend on Python exposing a named `AF_BTH` constant or supporting
  Bluetooth address tuples.
- Readiness uses zero-timeout `select` on the one Bluetooth socket, followed by
  a cooperative 10 ms delay while not ready. Microsoft prohibits mixing socket
  providers in a single `fd_set`; this avoids combining Bluetooth with an event
  loop's TCP wake-up socket. It works with Windows' default Proactor loop and
  does not require changing the application's loop policy.
- Exceptional connect readiness is checked explicitly. Windows can report a
  failed nonblocking connection in `exceptfds`, rather than `writefds`.
- Writes advance by the exact number of bytes accepted. Partial-write errors,
  EOF, deadlines and cancellation close the owned socket without reconnecting
  or resending. Kernel acceptance is not a printer acknowledgement.
- Open/read/write/close belong to one event loop. A process-local lease prevents
  two active streams to the same address. It does not lock out other programs
  or other computers. A closed stream is single-use.
- Input/output calls are bounded to 64 KiB, with a default 4 KiB host write chunk.
  This is not the Bluetooth MTU; diagnostics report `mtu=null`. `native_writes`
  counts send attempts, including would-block attempts, and `tx_bytes` counts
  bytes accepted by the socket. Readiness polling may add latency; actual bulk
  throughput needs separately authorized hardware measurement.

## Library and tests

Use `WindowsRfcommStream(address, adapter=optional_radio_mac)` with the existing
`ReadOnlySession` and `inspect_printer`, or use the CLI for complete before/after
and reconnect validation. The adapter implements the same byte-stream contract
as macOS and Linux; it contains no duplicated print protocol or JPEG preparation.

`tests/test_windows_stream.py` uses actual local sockets with the Windows
adapter's read/write/readiness logic and the default event loop. Only Bluetooth
bind/connect and cached pairing records are substituted. Tests cover full
CAL-02 and quality-100/4:4:4 CAL-03 jobs, byte-exact payload reconstruction,
partial writes, fragmented reads, backpressure, timeouts/cancellation, EOF,
lost PrintStart replies, duplicate owners, identity mismatch and read-only
allowlisting. Native-boundary tests verify ABI layouts, address bytes, cached
metadata queries/handle cleanup, and socket ownership. On Windows, a smoke test
loads the actual DLL bindings and uses a local socket without accessing a radio.

Simulated uploads consume no paper and do not establish real Bluetooth upload
speed or physical printing. See the [validation report](experiments/windows-adapter/README.md)
for current hardware and CI evidence.

## Troubleshooting

- **Not paired / no cached device:** discover and pair the exact Select in
  Windows Bluetooth settings, then retry the diagnostic explicitly.
- **No matching radio:** check radio availability and Windows Bluetooth power.
- **Error 10013:** authentication/access failed; inspect the existing pairing.
- **Timeout / refused / unavailable:** inspect printer power, proximity and
  competing connections. The CLI does not alter other devices' pairings.
- **Unsupported platform:** use 64-bit Windows Python for native Bluetooth.
  Portable simulation remains available on all three operating systems.

Primary interfaces: [Microsoft Bluetooth Winsock overview](https://learn.microsoft.com/en-us/windows/win32/bluetooth/bluetooth-programming-with-windows-sockets),
[SOCKADDR_BTH](https://learn.microsoft.com/en-us/windows/win32/api/ws2bth/ns-ws2bth-sockaddr_bth),
[SDK structure packing/constants](https://github.com/microsoft/win32metadata/blob/main/generation/WinSDK/RecompiledIdlHeaders/um/ws2bth.h),
[cached device information](https://learn.microsoft.com/en-us/windows/win32/api/bluetoothapis/nf-bluetoothapis-bluetoothgetdeviceinfo),
and [Winsock select semantics](https://learn.microsoft.com/en-us/windows/win32/api/winsock2/nf-winsock2-select).
