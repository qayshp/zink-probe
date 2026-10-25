"""Lazy CLI transport selection; simulation can never open a native adapter."""

import sys

from .simulator import SimulatedPrinter


class SimulatedStream(SimulatedPrinter):
    """Adapter lifecycle/counters around the same deterministic job simulator."""

    def __init__(self, address=None, *, timeout=15, trace=None):
        super().__init__(read_size=37, write_fragment=13)
        self.state = "new"
        self.mtu = self.close_error = None
        self.native_writes = self.tx_bytes = self.rx_bytes = 0

    async def open(self):
        self.state = "open"

    async def write(self, data):
        self.native_writes += 1
        self.tx_bytes += len(data)
        return await super().write(data)

    async def read(self, maximum):
        data = await super().read(maximum)
        self.rx_bytes += len(data)
        return data

    async def close(self):
        await super().close()
        self.state = "closed"


def resolve_transport(requested, *, simulated=False):
    if simulated:
        if requested not in ("auto", "simulated"):
            raise ValueError("A simulated plan cannot use a Bluetooth adapter")
        return "simulated"
    if requested == "simulated":
        raise ValueError(
            "A real-printer plan cannot be submitted to the simulator; create a simulated plan"
        )
    native = {"darwin": "macos", "linux": "linux", "win32": "windows"}.get(sys.platform)
    if native is None or requested not in ("auto", native):
        raise ValueError(
            "Select the native adapter for this operating system, or use a simulated plan"
        )
    return native


def stream_factory(transport, adapter=None):
    if transport in ("simulated", "macos") and adapter is not None:
        raise ValueError("--adapter is only supported on Linux and Windows")
    if transport == "simulated":
        return SimulatedStream
    if transport == "macos":
        from .macos import MacOSRfcommStream

        return MacOSRfcommStream
    if transport == "linux":
        from .linux import LinuxRfcommStream

        cls = LinuxRfcommStream
    elif transport == "windows":
        from .windows import WindowsRfcommStream

        cls = WindowsRfcommStream
    else:
        raise ValueError("Unsupported transport")
    return lambda address, **kwargs: cls(address, adapter=adapter, **kwargs)
