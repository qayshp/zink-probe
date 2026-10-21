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
                    self.sdp_status = None
                return self

            def rfcommChannelData_data_length_(self, channel, data, length):
                self.sink(bytes(data[:length]))

            def rfcommChannelClosed_(self, channel):
                self.closed = True

            def sdpQueryComplete_status_(self, device, status):
                self.sdp_status = int(status)

    return _Delegate.alloc().initWithSink_(sink)


class RfcommConnection:
    def __init__(self, address, timeout, trace, channel_id=2):
        if channel_id not in (1, 2):
            raise ValueError("Only discovered Select channels 1 and 2 are supported")
        self.channel_id = channel_id
        self.passive_chunks = []
        self.address = address
        self.timeout = timeout
        self.trace = trace
        self.channel = None
        self.delegate = None
        self.device = None
        self.parser = RfcommParser()
        self.queue = asyncio.Queue()
        self.unsolicited = []
        self.read_handles = set()
        self.config_writes = set()

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
            None, self.channel_id, self.delegate
        )
        self.channel = channel
        if rc != 0 or channel is None:
            raise ConnectionError(
                f"RFCOMM channel {self.channel_id} open failed: IOReturn {rc}"
            )
        self.trace.event("connected", transport="rfcomm", channel=self.channel_id)

    def _receive(self, data):
        if getattr(self, "channel_id", 2) == 1:
            self.passive_chunks.append(bytes(data).hex())
            self.trace.event("passive_channel_rx", channel=1, hex=bytes(data).hex())
            return
        self.trace.frame("rfcomm", "rx", data, layer="stream_chunk")
        try:
            for message in self.parser.feed(data):
                self.trace.frame("rfcomm", "rx", message, layer="message")
                if message[:1] == b"\x03":
                    self.unsolicited.append(message.hex())
                    self.trace.event(
                        "target_event", transport="rfcomm", hex=message.hex()
                    )
                else:
                    self.queue.put_nowait(message)
        except Exception as exc:
            self.queue.put_nowait(exc)

    async def exchange(self, message):
        if getattr(self, "channel_id", 2) != 2:
            raise ProtocolError("Channel 1 is receive-only; no writes permitted")
        wire = encode_rfcomm(
            message, self.read_handles, self.config_writes
        )  # Enforces default read-only policy and any exact scoped config grants.
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
        self.trace.event("disconnected", transport="rfcomm", channel=self.channel_id)

    async def listen(self, seconds=5):
        from Foundation import NSDate, NSRunLoop

        end = time.monotonic() + seconds
        while time.monotonic() < end and not self.delegate.closed:
            NSRunLoop.currentRunLoop().runUntilDate_(
                NSDate.dateWithTimeIntervalSinceNow_(0.005)
            )
            await asyncio.sleep(0.01)
        return {
            "channel": self.channel_id,
            "seconds": seconds,
            "chunks": list(self.passive_chunks),
            "transmitted_bytes": 0,
        }

    async def inventory(self):
        from Foundation import NSDate, NSRunLoop

        self.delegate.sdp_status = None
        rc = self.device.performSDPQuery_(self.delegate)
        if rc != 0:
            return {"fresh": False, "error": f"SDP query start IOReturn {rc}"}
        end = time.monotonic() + self.timeout
        while self.delegate.sdp_status is None:
            if time.monotonic() >= end:
                return {"fresh": False, "error": "SDP query timeout"}
            NSRunLoop.currentRunLoop().runUntilDate_(
                NSDate.dateWithTimeIntervalSinceNow_(0.005)
            )
            await asyncio.sleep(0.005)
        if self.delegate.sdp_status != 0:
            return {
                "fresh": False,
                "error": f"SDP query IOReturn {self.delegate.sdp_status}",
            }
        services = []
        for record in self.device.services() or []:
            rc, channel = record.getRFCOMMChannelID_(None)
            services.append(
                {
                    "name": str(record.getServiceName() or ""),
                    "rfcomm_channel": int(channel) if rc == 0 else None,
                    "attributes": {
                        f"0x{int(key):04X}": sdp_element(value)
                        for key, value in record.getAttributes().items()
                    },
                }
            )
        self.trace.event("sdp_inventory", services=services)
        return {"fresh": True, "services": services}


def sdp_element(element):
    kind = int(element.getTypeDescriptor())
    size = int(element.getSize())
    if kind in (6, 7):
        value = [sdp_element(item) for item in element.getArrayValue() or []]
    elif kind in (1, 2, 5):
        number = element.getNumberValue()
        value = (
            int(number) if number is not None else bytes(element.getDataValue()).hex()
        )
    elif kind == 3:
        value = bytes(element.getUUIDValue()).hex()
    elif kind in (4, 8):
        value = str(element.getStringValue())
    else:
        value = None
    return {"type": kind, "size": size, "value": value}
