"""Bounded HP+ framing over an injected asynchronous byte stream.

This explicit job channel is separate from the diagnostic transport allowlist.
It has no Bluetooth implementation or automatic reconnect. A supplied stream
must implement cancellation-safe async write/read/close methods; write may have
sent bytes before raising. The engine treats that outcome as uncertain.
"""

import asyncio
import math
from collections import deque
from typing import Protocol

from ..protocol import MAX_MESSAGE, ProtocolError, RfcommParser


class ByteStream(Protocol):
    async def write(self, data: bytes) -> None: ...
    async def read(self, maximum: int) -> bytes: ...
    async def close(self) -> None: ...


def frame(message):
    if not isinstance(message, bytes) or not 1 <= len(message) <= MAX_MESSAGE:
        raise ProtocolError("Invalid application message size")
    width = 1 if len(message) <= 255 else 2
    return b"HP+" + bytes([width]) + len(message).to_bytes(width, "little") + message


class FramedSession:
    def __init__(self, stream: ByteStream, timeout=15.0, trace=None):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Positive finite request timeout required")
        self.stream, self.timeout, self.trace = stream, timeout, trace
        self.parser = RfcommParser()
        self.events = deque(maxlen=64)
        self.read_handles = set()
        self.failed = False
        self.closed = False
        self.lock = asyncio.Lock()

    async def exchange(self, message):
        wire = frame(message)
        async with self.lock:
            if self.failed or self.closed:
                raise ConnectionError("Session unusable; no reconnect or resend")
            try:
                async with asyncio.timeout(self.timeout):
                    if self.trace:
                        self.trace.frame("job-stream", "tx", wire)
                    await self.stream.write(wire)
                    events = 0
                    while True:
                        data = await self.stream.read(MAX_MESSAGE + 6)
                        if not data:
                            raise ConnectionError(
                                "Stream disconnected while awaiting reply"
                            )
                        if len(data) > MAX_MESSAGE + 6:
                            raise ProtocolError("Stream exceeded requested read size")
                        if self.trace:
                            self.trace.frame(
                                "job-stream", "rx", data, layer="stream_chunk"
                            )
                        replies = []
                        for item in self.parser.feed(data):
                            if item[:1] == b"\x03":
                                self.events.append(item)
                                events += 1
                            else:
                                replies.append(item)
                        if events > 128:
                            raise ProtocolError(
                                "Target-event flood while awaiting reply"
                            )
                        if len(replies) > 1:
                            raise ProtocolError("Multiple replies to one request")
                        if replies:
                            reply = replies[0]
                            if reply[0] == 1:
                                if len(reply) != 3 or reply[1] != message[0]:
                                    raise ProtocolError("Uncorrelated error reply")
                            elif reply[0] != message[0] + 1:
                                raise ProtocolError("Unexpected response opcode")
                            return reply
            except BaseException:
                self.failed = True
                raise

    async def close(self):
        if not self.closed:
            self.closed = True
            await self.stream.close()
