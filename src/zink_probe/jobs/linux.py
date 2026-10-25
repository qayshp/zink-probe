"""Linux RFCOMM channel 2 over nonblocking sockets and read-only BlueZ metadata.

No automatic pairing, power/trust changes, discovery, reconnect or resend. The
raw stream can carry job messages; ReadOnlySession supplies diagnostic policy.
Native Bluetooth and D-Bus are touched only when opening the stream on Linux.
"""

from __future__ import annotations

import asyncio
import errno
import math
import os
import re
import socket
import sys
import threading

_OPEN_STREAMS = set()
_LEASE_LOCK = threading.Lock()
MAX_IO = 65536


def normalize_address(address):
    if not isinstance(address, str) or not re.fullmatch(
        r"[0-9a-fA-F]{2}(?P<sep>[:-])(?:[0-9a-fA-F]{2}(?P=sep)){4}[0-9a-fA-F]{2}",
        address,
    ):
        raise ValueError("A Classic Bluetooth MAC is required, not a BLE UUID")
    return address.replace("-", ":").upper()


def adapter_name(value):
    if not isinstance(value, str) or not re.fullmatch(r"hci[0-9]+", value):
        raise ValueError("Adapter must be a Linux name such as hci0")
    return value


async def managed_objects():
    """Read BlueZ's cached objects; never call Pair/Connect/Set/StartDiscovery."""
    if sys.platform != "linux":
        raise RuntimeError("The Linux Bluetooth adapter requires Linux")
    try:
        from dbus_fast import BusType, Message, MessageType
        from dbus_fast.aio import MessageBus
    except ImportError as exc:
        raise RuntimeError("Install zink-probe[linux] for BlueZ support") from exc
    bus = MessageBus(bus_type=BusType.SYSTEM)
    try:
        await bus.connect()
        reply = await bus.call(
            Message(
                destination="org.bluez",
                path="/",
                interface="org.freedesktop.DBus.ObjectManager",
                member="GetManagedObjects",
            )
        )
        if reply.message_type == MessageType.ERROR:
            raise ConnectionError(f"BlueZ metadata unavailable: {reply.error_name}")
        if reply.signature != "a{oa{sa{sv}}}" or len(reply.body) != 1:
            raise ConnectionError("Unexpected BlueZ object-manager response")
        return {
            path: {
                interface: {key: value.value for key, value in props.items()}
                for interface, props in interfaces.items()
            }
            for path, interfaces in reply.body[0].items()
        }
    finally:
        bus.disconnect()
        # dbus-fast 5 creates/connects its socket asynchronously. Always give
        # disconnect a bounded chance to finish, including on cancellation.
        try:
            async with asyncio.timeout(1):
                await bus.wait_for_disconnect()
        except Exception:
            pass


def select_device(objects, address, adapter=None):
    """Select the exact paired public-address device on a powered adapter."""
    address = normalize_address(address)
    if adapter is not None:
        adapter_name(adapter)
    matches = []
    for path, interfaces in objects.items():
        device = interfaces.get("org.bluez.Device1", {})
        if str(device.get("Address", "")).upper() != address:
            continue
        parent = device.get("Adapter")
        if not isinstance(parent, str) or not re.fullmatch(
            r"/org/bluez/hci[0-9]+", parent
        ):
            raise ConnectionError("Invalid BlueZ device adapter reference")
        if adapter is not None and parent != f"/org/bluez/{adapter}":
            continue
        local = objects.get(parent, {}).get("org.bluez.Adapter1", {})
        matches.append((path, parent, device, local))
    if not matches:
        raise ConnectionError(
            "Printer is not known to BlueZ on the selected adapter; pair it first using the Linux Bluetooth settings"
        )
    if len(matches) != 1:
        raise ConnectionError(
            "Printer is known on multiple adapters; choose --adapter hciN"
        )
    path, parent, device, local = matches[0]
    if device.get("AddressType") != "public":
        raise ConnectionError(
            "BlueZ target must have a public Classic Bluetooth address"
        )
    if device.get("Paired") is not True:
        raise ConnectionError(
            "Printer is not paired; pair it using the Linux Bluetooth settings"
        )
    if device.get("Blocked") is not False:
        raise ConnectionError(
            "Printer is blocked or BlueZ did not report its blocked state"
        )
    if local.get("Powered") is not True:
        raise ConnectionError("Selected Linux Bluetooth adapter is not powered")
    return {
        "device_path": path,
        "adapter": parent.rsplit("/", 1)[-1],
        "local_address": normalize_address(local.get("Address")),
        "address": address,
        "paired": True,
        "blocked": False,
        "powered": True,
    }


async def inspect_bluez(address, adapter):
    return select_device(await managed_objects(), address, adapter)


def _new_socket():
    if sys.platform != "linux":
        raise RuntimeError("The Linux RFCOMM socket adapter requires Linux")
    if not all(hasattr(socket, key) for key in ("AF_BLUETOOTH", "BTPROTO_RFCOMM")):
        raise RuntimeError(
            "This Python build has no Linux RFCOMM socket support; use a Python "
            "build with Bluetooth support (such as your distribution's Python)"
        )
    return socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)


def _socket_error(code, operation):
    hints = {
        errno.EACCES: "Check Bluetooth permissions and the existing pairing",
        errno.EPERM: "Check Bluetooth permissions and the existing pairing",
        errno.EAFNOSUPPORT: "The Linux kernel has no Bluetooth socket support",
        errno.EPROTONOSUPPORT: "The Linux kernel has no RFCOMM support",
        errno.ENETDOWN: "Check adapter power and rfkill state",
        errno.EHOSTDOWN: "Check that the paired printer is powered and nearby",
        errno.EHOSTUNREACH: "Check that the paired printer is powered and nearby",
        errno.ECONNREFUSED: "Check printer availability and Classic RFCOMM channel 2",
        errno.ETIMEDOUT: "Check printer range, availability and existing pairing",
    }
    detail = hints.get(code, "No automatic retry was attempted")
    return OSError(code, f"RFCOMM {operation}: {os.strerror(code)}. {detail}")


class LinuxRfcommStream:
    """Single-use channel 2 byte stream, owned by one asyncio selector loop.

    Successful send() means accepted by the local kernel, not a printer ACK.
    Failed/cancelled I/O closes this socket and must be considered possibly sent.
    Kernel RFCOMM handles link MTU segmentation; write_chunk_size is a host bound,
    not a measured radio MTU. No raw-HCI socket or /dev/rfcomm binding is needed.
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
        self.adapter = adapter_name(adapter) if adapter is not None else None
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Positive finite I/O timeout required")
        if type(write_chunk_size) is not int or not 1 <= write_chunk_size <= MAX_IO:
            raise ValueError(f"Write chunk size must be in 1..{MAX_IO}")
        self.timeout, self.trace = timeout, trace
        self.write_chunk_size = write_chunk_size
        self._socket_factory = _socket_factory or _new_socket
        self._inspect = _inspect or inspect_bluez
        self._socket = self._loop = None
        self._waiters = {}
        self._read_lock, self._write_lock = asyncio.Lock(), asyncio.Lock()
        self._leased = False
        self.state = "new"
        self.bluez = None
        self.close_error = None
        self.mtu = None  # Do not report an invented RF MTU.
        self.native_writes = self.tx_bytes = self.rx_bytes = 0

    def _context(self):
        loop = asyncio.get_running_loop()
        if self._loop is not None and loop is not self._loop:
            raise RuntimeError("RFCOMM stream belongs to another asyncio loop")
        return loop

    def _event(self, event, **values):
        if self.trace:
            self.trace.event(event, transport="linux-rfcomm-stream", **values)

    def _check_open(self):
        if self.state != "open":
            raise ConnectionError("RFCOMM stream is not open")

    async def _ready(self, writable):
        if self.state not in ("opening", "open"):
            raise ConnectionError("RFCOMM stream closed during I/O")
        fd = self._socket.fileno()
        future = self._loop.create_future()
        add = self._loop.add_writer if writable else self._loop.add_reader
        remove = self._loop.remove_writer if writable else self._loop.remove_reader

        def wake():
            if not future.done():
                future.set_result(None)

        self._waiters[writable] = (fd, future)
        try:
            add(fd, wake)
            await future
        finally:
            # close() removes watchers before closing the descriptor. Do not
            # remove a watcher on a descriptor that might have been reused.
            if self._waiters.get(writable) == (fd, future):
                remove(fd)
                del self._waiters[writable]

    async def open(self):
        loop = self._context()
        if self.state != "new":
            raise RuntimeError("RFCOMM stream is single-use; create a new stream")
        self._loop, self.state = loop, "opening"
        try:
            with _LEASE_LOCK:
                if self.address in _OPEN_STREAMS:
                    raise ConnectionError(
                        "Printer already has an active Linux stream in this process"
                    )
                _OPEN_STREAMS.add(self.address)
                self._leased = True
            async with asyncio.timeout(self.timeout):
                self.bluez = await self._inspect(self.address, self.adapter)
                if self.state != "opening":
                    raise ConnectionError("RFCOMM stream closed during preflight")
                self._event("bluez_preflight", **self.bluez)
                self._socket = self._socket_factory()
                self._socket.setblocking(False)
                self._socket.bind((self.bluez["local_address"], 0))
                code = self._socket.connect_ex((self.address, 2))
                if code in (
                    errno.EINPROGRESS,
                    errno.EWOULDBLOCK,
                    errno.EALREADY,
                    errno.EINTR,
                ):
                    await self._ready(True)
                    if self.state != "opening":
                        raise ConnectionError("RFCOMM stream closed during connect")
                    code = self._socket.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                if code not in (0, errno.EISCONN):
                    raise _socket_error(code, "connect")
                self.state = "open"
                self._event("connected", channel=2, adapter=self.bluez["adapter"])
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
        # No await inside cleanup: cancellation cannot strand an owned fd/lease.
        for writable, (fd, future) in list(self._waiters.items()):
            remove = self._loop.remove_writer if writable else self._loop.remove_reader
            remove(fd)
            if not future.done():
                future.set_exception(ConnectionError("RFCOMM stream closed during I/O"))
        self._waiters.clear()
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
