"""Windows RFCOMM channel 2 transport for the portable single-job engine.

No automatic discovery, pairing, settings changes, reconnect, or resend.
ReadOnlySession, rather than this raw stream, enforces diagnostic policy.
"""

from __future__ import annotations

import asyncio
import math
import re
import select
import socket
import threading

MAX_IO = 65536
_OPEN_STREAMS = set()
_LEASE_LOCK = threading.Lock()
_PENDING = (10035, 10036, 10037)  # WSAEWOULDBLOCK / INPROGRESS / ALREADY


def normalize_address(address):
    if not isinstance(address, str) or not re.fullmatch(
        r"[0-9a-fA-F]{2}(?P<sep>[:-])(?:[0-9a-fA-F]{2}(?P=sep)){4}[0-9a-fA-F]{2}",
        address,
    ):
        raise ValueError("A Classic Bluetooth MAC is required, not a BLE UUID")
    return address.replace("-", ":").upper()


def select_device(records, address, adapter=None):
    address = normalize_address(address)
    if adapter is not None:
        adapter = normalize_address(adapter)
    radios = [r for r in records if adapter is None or r["local_address"] == adapter]
    if not radios:
        raise ConnectionError(
            "No matching Windows Bluetooth radio is available; check Bluetooth power"
        )
    matches = [
        r
        for r in radios
        if r["known"] and r["address"] == address and r["authenticated"]
    ]
    if not matches:
        raise ConnectionError(
            "Printer is not paired on the selected radio; pair the exact Select in Windows Bluetooth settings"
        )
    if len(matches) != 1:
        raise ConnectionError(
            "Printer is paired on multiple radios; choose --adapter with the local radio MAC"
        )
    return dict(matches[0])


async def _cached_call(call):
    """Cancellable local metadata read; its worker never opens a printer socket.

    Cancellation discards late results. A daemon avoids making asyncio shutdown
    wait indefinitely on a stuck OS metadata API; native handles close in finally
    when that API returns. At most one worker per explicitly opened stream.
    """
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    def deliver(value, error):
        if not future.done():
            if error is None:
                future.set_result(value)
            else:
                future.set_exception(error)

    def worker():
        value = error = None
        try:
            value = call()
        except Exception as exc:
            error = exc
        try:
            loop.call_soon_threadsafe(deliver, value, error)
        except RuntimeError:
            pass  # The caller's loop has already closed.

    threading.Thread(target=worker, name="zink-windows-metadata", daemon=True).start()
    return await future


async def inspect_windows(address, adapter):
    from .windows_native import cached_devices

    return select_device(
        await _cached_call(lambda: cached_devices(address)), address, adapter
    )


def _new_socket():
    from .windows_native import NativeSocket

    return NativeSocket()


def _socket_error(code):
    hints = {
        10013: "Check Windows Bluetooth pairing and access permissions",
        10047: "Windows Bluetooth sockets are unavailable",
        10050: "Check Bluetooth radio power",
        10051: "Check radio availability and printer range",
        10060: "Printer connection timed out; check power, range and other connections",
        10061: "Printer refused the RFCOMM connection",
        10064: "Printer is unavailable or rejected the channel",
    }
    return OSError(
        code,
        "Windows RFCOMM: "
        + hints.get(code, "Connection failed; no retry was attempted"),
    )


class WindowsRfcommStream:
    """Single-use nonblocking socket, compatible with the default Proactor loop.

    Only one socket is passed to select() at once: Winsock prohibits mixing
    Bluetooth and TCP providers in an fd_set. Polling has a 10 ms cooperative delay
    when not ready, and never blocks the event loop or starts a socket I/O worker.
    """

    def __init__(
        self,
        address,
        *,
        adapter=None,
        timeout=15.0,
        trace=None,
        write_chunk_size=4096,
        _socket_factory=None,
        _inspect=None,
    ):
        self.address = normalize_address(address)
        self.adapter = normalize_address(adapter) if adapter is not None else None
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Positive finite I/O timeout required")
        if type(write_chunk_size) is not int or not 1 <= write_chunk_size <= MAX_IO:
            raise ValueError(f"Write chunk size must be in 1..{MAX_IO}")
        self.timeout, self.trace, self.write_chunk_size = (
            timeout,
            trace,
            write_chunk_size,
        )
        self._socket_factory = _socket_factory or _new_socket
        self._inspect = _inspect or inspect_windows
        self._socket = self._loop = None
        self._read_lock, self._write_lock = asyncio.Lock(), asyncio.Lock()
        self._leased = False
        self.state = "new"
        self.metadata = None
        self.close_error = self.mtu = None
        self.native_writes = self.tx_bytes = self.rx_bytes = 0

    def _context(self):
        loop = asyncio.get_running_loop()
        if self._loop is not None and loop is not self._loop:
            raise RuntimeError("RFCOMM stream belongs to another asyncio loop")
        return loop

    def _event(self, event, **values):
        if self.trace:
            self.trace.event(event, transport="windows-rfcomm-stream", **values)

    def _check_open(self):
        if self.state != "open":
            raise ConnectionError("RFCOMM stream is not open")

    async def _ready(self, writable):
        while True:
            await asyncio.sleep(0)  # Permit cancellation even on repeated readiness.
            if self.state not in ("opening", "open"):
                raise ConnectionError("RFCOMM stream closed during I/O")
            sock = self._socket
            r, w, x = select.select(
                [] if writable else [sock], [sock] if writable else [], [sock], 0
            )
            if x:
                code = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                raise (
                    _socket_error(code)
                    if code
                    else ConnectionError("Exceptional RFCOMM socket condition")
                )
            if r or w:
                return
            await asyncio.sleep(0.01)

    async def open(self):
        loop = self._context()
        if self.state != "new":
            raise RuntimeError("RFCOMM stream is single-use; create a new stream")
        self._loop, self.state = loop, "opening"
        try:
            with _LEASE_LOCK:
                if self.address in _OPEN_STREAMS:
                    raise ConnectionError(
                        "Printer already has an active Windows stream in this process"
                    )
                _OPEN_STREAMS.add(self.address)
                self._leased = True
            async with asyncio.timeout(self.timeout):
                self.metadata = await self._inspect(self.address, self.adapter)
                if self.state != "opening":
                    raise ConnectionError("RFCOMM stream closed during preflight")
                self._event("windows_preflight", **self.metadata)
                self._socket = self._socket_factory()
                self._socket.setblocking(False)
                self._socket.bind((self.metadata["local_address"], 0))
                code = self._socket.connect_ex((self.address, 2))
                if code in _PENDING:
                    await self._ready(True)
                    if self.state != "opening":
                        raise ConnectionError("RFCOMM stream closed during connect")
                    code = self._socket.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                if code not in (0, 10056):
                    raise _socket_error(code)
                self.state = "open"
                self._event("connected", channel=2)
                return self
        except BaseException:
            await self.close()
            raise

    async def write(self, data):
        self._context()
        if not isinstance(data, bytes) or not 1 <= len(data) <= MAX_IO:
            raise ValueError(f"Immutable bytes of length 1..{MAX_IO} required")
        self._check_open()
        try:
            async with asyncio.timeout(self.timeout), self._write_lock:
                offset = 0
                while offset < len(data):
                    self._check_open()
                    try:
                        self.native_writes += 1
                        sent = self._socket.send(
                            data[offset : offset + self.write_chunk_size]
                        )
                    except (BlockingIOError, InterruptedError):
                        await self._ready(True)
                        continue
                    if sent <= 0:
                        raise ConnectionError("RFCOMM send made no progress")
                    self.tx_bytes += sent
                    offset += sent
        except BaseException:
            await self.close()
            raise

    async def read(self, maximum):
        self._context()
        if type(maximum) is not int or not 1 <= maximum <= MAX_IO:
            raise ValueError(f"Read size must be in 1..{MAX_IO}")
        if self.state == "closed":
            return b""
        self._check_open()
        try:
            async with asyncio.timeout(self.timeout), self._read_lock:
                while True:
                    self._check_open()
                    try:
                        data = self._socket.recv(maximum)
                    except (BlockingIOError, InterruptedError):
                        await self._ready(False)
                        continue
                    self.rx_bytes += len(data)
                    if not data:
                        await self.close()
                    return data
        except BaseException:
            await self.close()
            raise

    async def close(self):
        self._context()
        if self.state == "closed":
            return
        self.state = "closed"
        sock, self._socket = self._socket, None
        if sock is not None:
            try:
                sock.close()
            except OSError as exc:
                self.close_error = f"Cannot close RFCOMM socket: {exc}"
        if self._leased:
            with _LEASE_LOCK:
                _OPEN_STREAMS.discard(self.address)
            self._leased = False
        self._event("disconnected", channel=2, close_error=self.close_error)
