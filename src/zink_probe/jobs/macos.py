"""IOBluetooth RFCOMM byte stream for the portable engine.

Native imports are lazy. Open/read/write/close belong to the main thread and one
asyncio loop. An independent task pumps the Cocoa run loop while awaiting native
open/write callbacks. This is a raw transport, not a read-only policy boundary;
use ReadOnlySession for diagnostics. There is no automatic reconnect or resend.
"""

from __future__ import annotations

import asyncio
import math
import re
import sys
import threading

_OPEN_STREAMS = set()  # Access is confined to the main thread, within this process.


def normalize_address(address):
    if not isinstance(address, str) or not re.fullmatch(
        r"[0-9a-fA-F]{2}(?P<sep>[:-])(?:[0-9a-fA-F]{2}(?P=sep)){4}[0-9a-fA-F]{2}",
        address,
    ):
        raise ValueError("A Classic Bluetooth MAC address is required, not a BLE UUID")
    return address.replace(":", "-").lower()


class _NativeBackend:
    def __init__(self):
        if sys.platform != "darwin":
            raise RuntimeError("The IOBluetooth adapter requires macOS")
        try:
            import IOBluetooth
            import objc
            from Foundation import NSDate, NSObject, NSRunLoop
        except ImportError as exc:
            raise RuntimeError(
                "Install zink-probe[macos] for Bluetooth support"
            ) from exc

        self.device_class = IOBluetooth.IOBluetoothDevice
        self.date, self.run_loop = NSDate, NSRunLoop.currentRunLoop()
        # Objective-C class names are process-global; register this one only once.
        global _ZinkStreamDelegate
        if "_ZinkStreamDelegate" not in globals():
            # PyObjC's framework metadata supplies the length-qualified input
            # buffer for this informal delegate. Explicit formal-protocol
            # conformance overrides it with bare void*, delivered as an integer.
            class _ZinkStreamDelegate(NSObject):
                def initWithOwner_(self, owner):
                    self = objc.super(_ZinkStreamDelegate, self).init()
                    if self is not None:
                        self.owner = owner
                    return self

                def rfcommChannelOpenComplete_status_(self, channel, status):
                    if self.owner is not None:
                        self.owner._opened(int(status))

                def rfcommChannelData_data_length_(self, channel, data, length):
                    if self.owner is not None:
                        try:
                            self.owner._received(bytes(data[:length]))
                        except Exception as exc:
                            # Never let a Python conversion error unwind into
                            # Cocoa's callback and abort the process.
                            self.owner._failure = ConnectionError(
                                f"RFCOMM callback decoding failed: {exc}"
                            )
                            self.owner._wake()

                def rfcommChannelWriteComplete_refcon_status_(
                    self, channel, refcon, status
                ):
                    if self.owner is not None:
                        self.owner._written(int(status))

                def rfcommChannelClosed_(self, channel):
                    if self.owner is not None:
                        self.owner._disconnected()

        self.delegate_class = _ZinkStreamDelegate

    def device(self, address):
        return self.device_class.deviceWithAddressString_(address)

    def delegate(self, owner):
        return self.delegate_class.alloc().initWithOwner_(owner)

    def pump(self):
        self.run_loop.runUntilDate_(self.date.dateWithTimeIntervalSinceNow_(0.001))


class MacOSRfcommStream:
    """Single-use, bounded RFCOMM channel 2 stream, with MTU-sized native writes.

    A successful native write callback means handed to the Bluetooth hardware,
    not acknowledged by the printer. FramedSession/JobEngine own that distinction.
    A failed/cancelled operation closes this stream; never reuse its channel.
    Native API entry/close calls are brief synchronous calls: Python deadlines
    cover callback waits, not a hung OS call. Only this channel is closed.
    """

    def __init__(
        self, address, *, timeout=15.0, trace=None, receive_limit=65536, _backend=None
    ):
        self.address = normalize_address(address)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Positive finite I/O timeout required")
        if type(receive_limit) is not int or receive_limit < 4096 + 6:
            raise ValueError("Receive limit must hold at least one maximum HP+ frame")
        self.timeout, self.trace, self.receive_limit = timeout, trace, receive_limit
        self._backend = _backend
        self._loop = None
        self._pump_task = None
        self._channel = self._delegate = self._device = None
        self._buffer = bytearray()
        self._rx_ready, self._open_ready, self._write_ready = (
            asyncio.Event(),
            asyncio.Event(),
            asyncio.Event(),
        )
        self._write_lock, self._read_lock = asyncio.Lock(), asyncio.Lock()
        self._close_lock = asyncio.Lock()
        self._close_ready = asyncio.Event()
        self._open_status = self._write_status = None
        self._write_data = None
        self._peer_closed = False
        self._leased = False
        self._failure = None
        self.state = "new"
        self.mtu = None
        self.close_error = None
        self.native_writes = self.tx_bytes = self.rx_bytes = 0

    def _context(self):
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("IOBluetooth stream must run on the main thread")
        loop = asyncio.get_running_loop()
        if self._loop is not None and loop is not self._loop:
            raise RuntimeError("IOBluetooth stream belongs to another asyncio loop")
        return loop

    def _event(self, event, **values):
        if self.trace:
            self.trace.event(event, transport="macos-rfcomm-stream", **values)

    def _wake(self):
        for event in (self._rx_ready, self._open_ready, self._write_ready):
            event.set()

    def _opened(self, status):
        if self.state == "opening":
            self._open_status = status
            self._open_ready.set()

    def _received(self, data):
        if self.state not in ("opening", "open"):
            return
        if len(self._buffer) + len(data) > self.receive_limit:
            self._failure = ConnectionError("RFCOMM receive buffer exceeded its bound")
            self._wake()
            return
        self.rx_bytes += len(data)
        self._buffer.extend(data)
        self._rx_ready.set()

    def _written(self, status):
        if self.state == "open" and self._write_data is not None:
            self._write_status = status
            self._write_ready.set()

    def _disconnected(self):
        self._peer_closed = True
        self._close_ready.set()
        self._wake()

    def _check(self):
        if self._failure:
            raise self._failure
        if self.state == "closed" or self._peer_closed:
            raise ConnectionError("RFCOMM channel closed; no reconnect or resend")

    async def _pump(self):
        try:
            while self.state != "closed":
                self._backend.pump()
                await asyncio.sleep(0.005)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._failure = ConnectionError(f"Cocoa run-loop failure: {exc}")
            self._wake()

    async def open(self):
        self._loop = self._context()
        if self.state != "new":
            raise RuntimeError("Stream instances are single-use; create a new stream")
        self.state = "opening"
        try:
            if self.address in _OPEN_STREAMS:
                raise ConnectionError(
                    "Another adapter stream owns this printer in this process"
                )
            _OPEN_STREAMS.add(self.address)
            self._leased = True
            self._backend = self._backend or _NativeBackend()
            self._device = self._backend.device(self.address)
            if self._device is None or not self._device.isPaired():
                raise ConnectionError(
                    "Select is not paired for Classic Bluetooth. Pair it in "
                    "System Settings > Bluetooth; this adapter does not change pairing."
                )
            self._delegate = self._backend.delegate(self)
            rc, self._channel = (
                self._device.openRFCOMMChannelAsync_withChannelID_delegate_(
                    None, 2, self._delegate
                )
            )
            if rc or self._channel is None:
                raise ConnectionError(f"RFCOMM open could not start: IOReturn {rc}")
            self._event("open_started", already_open=bool(self._channel.isOpen()))
            self._pump_task = asyncio.create_task(self._pump(), name="zink-rfcomm-pump")
            try:
                async with asyncio.timeout(self.timeout):
                    await self._open_ready.wait()
            except TimeoutError as exc:
                raise TimeoutError(
                    f"RFCOMM open callback not received within {self.timeout:g}s"
                ) from exc
            self._check()
            if self._open_status != 0 or not self._channel.isOpen():
                raise ConnectionError(
                    f"RFCOMM open failed: IOReturn {self._open_status}"
                )
            self.mtu = int(self._channel.getMTU())
            if not 1 <= self.mtu <= 65535:
                raise ConnectionError("Invalid RFCOMM MTU")
            self.state = "open"
            self._event("connected", channel=2, mtu=self.mtu)
            return self
        except BaseException:
            await self.close()
            raise

    async def write(self, data):
        self._context()
        if not isinstance(data, bytes) or not data:
            raise ValueError("Nonempty immutable bytes required")
        if self.state != "open":
            raise ConnectionError("RFCOMM stream is not open")
        try:
            async with asyncio.timeout(self.timeout), self._write_lock:
                for offset in range(0, len(data), self.mtu):
                    self._check()
                    # Keep the immutable buffer alive through the native completion.
                    self._write_data = data[offset : offset + self.mtu]
                    self._write_status = None
                    self._write_ready.clear()
                    rc = self._channel.writeAsync_length_refcon_(
                        self._write_data, len(self._write_data), None
                    )
                    self.native_writes += 1
                    if rc:
                        raise ConnectionError(f"RFCOMM write failed: IOReturn {rc}")
                    await self._write_ready.wait()
                    self._check()
                    if self._write_status != 0:
                        raise ConnectionError(
                            f"RFCOMM write completion failed: IOReturn {self._write_status}"
                        )
                    self.tx_bytes += len(self._write_data)
                    self._write_data = None
        except BaseException:
            await self.close()
            raise

    async def read(self, maximum):
        self._context()
        if type(maximum) is not int or maximum <= 0:
            raise ValueError("Positive read size required")
        if self.state == "new":
            raise ConnectionError("RFCOMM stream is not open")
        try:
            async with asyncio.timeout(self.timeout), self._read_lock:
                while True:
                    if self._failure:
                        raise self._failure
                    if self._buffer:
                        data = bytes(self._buffer[:maximum])
                        del self._buffer[:maximum]
                        return data
                    if self._peer_closed or self.state == "closed":
                        return b""
                    self._rx_ready.clear()
                    await self._rx_ready.wait()
        except BaseException:
            await self.close()
            raise

    async def close(self):
        self._context()
        async with self._close_lock:
            if self.state == "closed":
                return
            self.state = "closing"
            self._wake()
            channel = self._channel
            try:
                if channel is not None:
                    # closeChannel starts asynchronous teardown. Keep pumping
                    # until its callback: immediate reopen can otherwise reuse
                    # the old native channel and inherit its close notification.
                    if self._pump_task is None:
                        self._pump_task = asyncio.create_task(self._pump())
                    rc = channel.closeChannel()
                    if rc:
                        self.close_error = f"RFCOMM close failed: IOReturn {rc}"
                    elif not self._peer_closed:
                        try:
                            async with asyncio.timeout(min(self.timeout, 2.0)):
                                await self._close_ready.wait()
                        except TimeoutError:
                            self.close_error = (
                                "RFCOMM close callback not observed before deadline"
                            )
            except Exception as exc:
                self.close_error = f"Cannot close RFCOMM channel: {exc}"
            finally:
                self.state = "closed"
                self._wake()
                task, self._pump_task = self._pump_task, None
                if task is not None:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                if channel is not None:
                    try:
                        channel.setDelegate_(None)
                    except Exception as exc:
                        self.close_error = f"Cannot detach RFCOMM delegate: {exc}"
                if self._delegate is not None:
                    self._delegate.owner = None
                self._channel = self._delegate = self._device = self._write_data = None
                self._buffer.clear()
                if self._leased:
                    _OPEN_STREAMS.discard(self.address)
                    self._leased = False
                self._event("disconnected", channel=2, close_error=self.close_error)
