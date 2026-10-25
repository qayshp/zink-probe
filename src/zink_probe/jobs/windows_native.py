"""Small desktop Windows Bluetooth ABI boundary; no discovery or pairing.

Fixed-width definitions follow Microsoft's bluetoothapis.h and ws2bth.h.
DLLs are loaded only on explicit native use. Importing this file is portable.
"""

import ctypes as C
import socket
import sys

AF_BTH = 32
BTHPROTO_RFCOMM = 3
ERROR_NO_MORE_ITEMS = 259
ERROR_NOT_FOUND = 1168


class SockaddrBth(C.Structure):
    # ws2bth.h includes pshpack1.h: this structure is 30 bytes, not 40.
    _layout_ = "ms"
    _pack_ = 1
    _fields_ = [
        ("family", C.c_uint16),
        ("address", C.c_uint64),
        ("service", C.c_ubyte * 16),
        ("port", C.c_uint32),
    ]


class RadioParams(C.Structure):
    _fields_ = [("size", C.c_uint32)]


class RadioInfo(C.Structure):
    _fields_ = [
        ("size", C.c_uint32),
        ("address", C.c_uint64),
        ("name", C.c_uint16 * 248),
        ("device_class", C.c_uint32),
        ("subversion", C.c_uint16),
        ("manufacturer", C.c_uint16),
    ]


class DeviceInfo(C.Structure):
    _fields_ = [
        ("size", C.c_uint32),
        ("address", C.c_uint64),
        ("device_class", C.c_uint32),
        ("connected", C.c_int32),
        ("remembered", C.c_int32),
        ("authenticated", C.c_int32),
        ("last_seen", C.c_uint16 * 8),
        ("last_used", C.c_uint16 * 8),
        ("name", C.c_uint16 * 248),
    ]


def address_number(address):
    return int(address.replace(":", ""), 16)


def address_text(number):
    return ":".join(f"{number:012X}"[i : i + 2] for i in range(0, 12, 2))


def sockaddr(address, port):
    return SockaddrBth(AF_BTH, address_number(address), (C.c_ubyte * 16)(), port)


def _function(dll, name, restype, *argtypes):
    fn = getattr(dll, name)
    fn.restype, fn.argtypes = restype, argtypes
    return fn


def _require_windows():
    if sys.platform != "win32" or C.sizeof(C.c_void_p) != 8:
        raise RuntimeError("The native Windows adapter requires 64-bit Windows Python")


class BluetoothApi:
    def __init__(self):
        _require_windows()
        # Explicit system32-only loading; do not search the working directory.
        bt = C.WinDLL("bthprops.cpl", use_last_error=True, winmode=0x800)
        kernel = C.WinDLL("kernel32.dll", use_last_error=True, winmode=0x800)
        ptr, boolean, dword = C.c_void_p, C.c_int32, C.c_uint32
        self.first = _function(
            bt, "BluetoothFindFirstRadio", ptr, C.POINTER(RadioParams), C.POINTER(ptr)
        )
        self.next = _function(
            bt, "BluetoothFindNextRadio", boolean, ptr, C.POINTER(ptr)
        )
        self.close_find = _function(bt, "BluetoothFindRadioClose", boolean, ptr)
        self.close_radio = _function(kernel, "CloseHandle", boolean, ptr)
        self.radio_info = _function(
            bt, "BluetoothGetRadioInfo", dword, ptr, C.POINTER(RadioInfo)
        )
        self.device_info = _function(
            bt, "BluetoothGetDeviceInfo", dword, ptr, C.POINTER(DeviceInfo)
        )
        self.last_error = C.get_last_error


def cached_devices(address, *, _api=None):
    """Read one exact device's cached state on each local radio; close all handles."""
    api = _api or BluetoothApi()
    params = RadioParams(C.sizeof(RadioParams))
    radio = C.c_void_p()
    finder = api.first(C.byref(params), C.byref(radio))
    if not finder:
        code = api.last_error()
        if code == ERROR_NO_MORE_ITEMS:
            return []
        raise OSError(code, "Cannot enumerate Windows Bluetooth radios")
    results = []
    try:
        while True:
            try:
                info = RadioInfo(size=C.sizeof(RadioInfo))
                code = api.radio_info(radio, C.byref(info))
                if code:
                    raise OSError(code, "Cannot read Windows Bluetooth radio")
                device = DeviceInfo(
                    size=C.sizeof(DeviceInfo), address=address_number(address)
                )
                code = api.device_info(radio, C.byref(device))
                if code not in (0, ERROR_NOT_FOUND):
                    raise OSError(
                        code,
                        "Cannot read Windows cached Bluetooth device; ensure the exact printer "
                        "has been discovered and paired in Windows Bluetooth settings",
                    )
                results.append(
                    {
                        "local_address": address_text(info.address),
                        "address": address,
                        "known": code == 0,
                        "authenticated": code == 0 and bool(device.authenticated),
                        "remembered": code == 0 and bool(device.remembered),
                        "connected": code == 0 and bool(device.connected),
                    }
                )
            finally:
                api.close_radio(radio)
            radio = C.c_void_p()
            if not api.next(finder, C.byref(radio)):
                code = api.last_error()
                if code != ERROR_NO_MORE_ITEMS:
                    raise OSError(code, "Cannot finish Windows radio enumeration")
                break
    finally:
        api.close_find(finder)
    return results


class WinsockApi:
    def __init__(self):
        _require_windows()
        dll = C.WinDLL("ws2_32.dll", use_last_error=True, winmode=0x800)
        self.bind = _function(dll, "bind", C.c_int, C.c_size_t, C.c_void_p, C.c_int)
        self.connect = _function(
            dll, "connect", C.c_int, C.c_size_t, C.c_void_p, C.c_int
        )
        self.last_error = _function(dll, "WSAGetLastError", C.c_int)


class NativeSocket:
    """Python owns the SOCKET; only Bluetooth sockaddr encoding needs ctypes."""

    def __init__(self, *, _api=None, _socket=None):
        self.api = _api or WinsockApi()
        # Python initializes Winsock and owns/cleans up the handle. Explicit
        # integer family works even when its socket module exports no AF_BTH.
        self.sock = (
            _socket
            if _socket is not None
            else socket.socket(AF_BTH, socket.SOCK_STREAM, BTHPROTO_RFCOMM)
        )

    def bind(self, address):
        value = sockaddr(*address)
        if self.api.bind(self.sock.fileno(), C.byref(value), C.sizeof(value)) == -1:
            raise OSError(self.api.last_error(), "Cannot bind Windows RFCOMM radio")

    def connect_ex(self, address):
        value = sockaddr(*address)
        result = self.api.connect(self.sock.fileno(), C.byref(value), C.sizeof(value))
        return self.api.last_error() if result == -1 else 0

    def setblocking(self, value):
        self.sock.setblocking(value)

    def fileno(self):
        return self.sock.fileno()

    def getsockopt(self, level, option):
        return self.sock.getsockopt(level, option)

    def send(self, data):
        return self.sock.send(data)

    def recv(self, maximum):
        return self.sock.recv(maximum)

    def close(self):
        self.sock.close()
