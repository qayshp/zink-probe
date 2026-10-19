"""macOS IOBluetooth RFCOMM, pumped on the main thread alongside asyncio."""

import asyncio
import time

from .protocol import ProtocolError, RfcommParser, encode_rfcomm


def _make_delegate(sink):
    import objc
    from Foundation import NSObject

    # PyObjC registers classes globally, so define this class just once.
    global _Delegate
    if "_Delegate" not in globals():

        class _Delegate(NSObject):
            def initWithSink_(self, callback):
                self = objc.super(_Delegate, self).init()
                if self is not None:
                    self.sink = callback
                    self.closed = False
                return self

            def rfcommChannelData_data_length_(self, channel, data, length):
                self.sink(bytes(data[:length]))

            def rfcommChannelClosed_(self, channel):
                self.closed = True

    return _Delegate.alloc().initWithSink_(sink)


class RfcommConnection:
    def __init__(self, address, timeout, trace):
        self.address = address
        self.timeout = timeout
        self.trace = trace
        self.channel = None
        self.delegate = None
        self.device = None
        self.parser = RfcommParser()
        self.queue = asyncio.Queue()

    async def open(self):
        import IOBluetooth

        self.device = IOBluetooth.IOBluetoothDevice.deviceWithAddressString_(
            self.address.replace(":", "-").lower()
        )
        if self.device is None or not self.device.isPaired():
            raise ConnectionError(
                "Select is not paired for Classic Bluetooth. Pair it in macOS "
                "System Settings > Bluetooth, then rerun the probe."
            )
        self.delegate = _make_delegate(self._receive)
        # Synchronous native open has an OS-controlled timeout. Read deadlines below
        # are ours; do not claim asyncio can interrupt this native call.
        rc, channel = self.device.openRFCOMMChannelSync_withChannelID_delegate_(
            None, 2, self.delegate
        )
        self.channel = channel
        if rc != 0 or channel is None:
            raise ConnectionError(f"RFCOMM channel 2 open failed: IOReturn {rc}")
        self.trace.event("connected", transport="rfcomm", channel=2)

    def _receive(self, data):
        self.trace.frame("rfcomm", "rx", data, layer="stream_chunk")
        try:
            for message in self.parser.feed(data):
                self.trace.frame("rfcomm", "rx", message, layer="message")
                self.queue.put_nowait(message)
        except Exception as exc:
            self.queue.put_nowait(exc)

    async def exchange(self, message):
        wire = encode_rfcomm(message)  # Also enforces the read-only allowlist.
        if not self.queue.empty():
            raise ProtocolError("Unsolicited RFCOMM message; refusing ambiguous reply")
        self.trace.frame("rfcomm", "tx", wire)
        rc = self.channel.writeSync_length_(wire, len(wire))
        if rc != 0:
            raise ConnectionError(f"RFCOMM write failed: IOReturn {rc}")
        end = time.monotonic() + self.timeout
        while self.queue.empty():
            if self.delegate.closed:
                raise ConnectionError("RFCOMM closed while waiting for reply")
            if time.monotonic() >= end:
                raise TimeoutError(
                    "RFCOMM response timeout (probe will stop, no resend)"
                )
            from Foundation import NSDate, NSRunLoop

            NSRunLoop.currentRunLoop().runUntilDate_(
                NSDate.dateWithTimeIntervalSinceNow_(0.005)
            )
            await asyncio.sleep(0.005)
        response = self.queue.get_nowait()
        if isinstance(response, Exception):
            raise response
        return response

    async def close(self):
        if self.channel is not None:
            self.channel.closeChannel()
            self.channel = None
        # Close only the RFCOMM channel owned here; do not unpair or close other links.
        self.trace.event("disconnected", transport="rfcomm")
