"""Deterministic in-memory printer, not firmware emulation or Bluetooth support.

Implements the subset exercised by JobEngine; deliberately rejects unexpected
requests. Wire replies can be fragmented/coalesced, and faults occur after the
simulated printer has processed a request to model ambiguous transport failure.
"""

import asyncio
import json
import struct
from collections import deque

from ..protocol import ATTRIBUTES, CONFIG, SELECT, STATUS, RfcommParser, read_varuint
from .transport import frame

DEVICE_ID = bytes(range(16)).hex()


class SimulatedPrinter:
    def __init__(
        self,
        *,
        maximum=1000,
        name_limit=16,
        copies_expected=None,
        read_size=4096,
        write_fragment=4096,
        events=True,
        fault=None,
    ):
        self.maximum, self.name_limit = maximum, name_limit
        self.read_size, self.write_fragment = read_size, write_fragment
        self.events_enabled, self.fault = events, fault
        self.copies_expected = copies_expected
        self.device_id, self.model = DEVICE_ID, SELECT
        self.pages, self.calibrations = 11, 2
        self.battery, self.paused = 100, False
        self.job_id, self.handle = 0x1234, 7
        self.expected_bytes = None
        self.uploaded = bytearray()
        self.copies, self.name = None, None
        self.finished_upload = False
        self.printed = False
        self.polls = 0
        self.requests, self.mutations = [], []
        self.response_bytes = bytearray()
        self.rx_parser = RfcommParser()
        self.closed, self.hang = False, False
        self.pending_error = None
        self.snapshot = self._status(False)
        self.extra_jobs = []
        self.never_complete = False
        self.disappear_without_print = False
        self.require_empty_final = False
        self.status_overrides = {}
        self.features = {
            "version": 9,
            "proto_version": 1,
            "requests": [4, 8, 10, 12, 14, 26, 36, 40, 42, 44, 48, 58],
            "mime": [1],
            "job_prop": [1, 3],
            "job_name_max": name_limit,
        }

    def _status(self, printing):
        return {
            "system_flags": 4 if printing else 0,
            "print_status_code": 7 if printing else 1,
            "battery_percent": self.battery,
            "print_progress_percent": 0,
            "current_job_id": self.job_id if printing else 0,
            "battery_status_code": 2,
            "queue_status_code": 4 if printing else 1,
            "number_of_hosts": 1,
        }

    def _next_status(self):
        printing = False
        if self.finished_upload and not self.disappear_without_print:
            self.polls += 1
            printing = self.never_complete or self.polls <= 2
            if not printing and not self.printed:
                self.pages += self.copies
                self.printed = True
        self.snapshot = self._status(printing) | self.status_overrides
        return self.snapshot

    def _respond(self, request):
        opcode = request[0]
        if request == b"\x0a\x02":
            return b"\x0b\x00"
        if request == b"\x24\x00\x10":
            return b"\x25" + struct.pack("<HB", self.maximum, 33)
        if opcode == 4 and len(request) == 2:
            tag = request[1]
            kind = ATTRIBUTES[tag][1]
            if tag == 6:
                value = bytes.fromhex(self.device_id)
            elif tag == 9:
                value = self.model.to_bytes(2, "little")
            elif kind == "string":
                value = b"\x03SIM"
            else:
                value = bytes({"mac": 6, "bytes16": 16}.get(kind, kind))
            return bytes([5, tag]) + value
        if request == b"\x2a":
            return b"\x2b\x09\x01"
        if request == b"\x28\x09\x01":
            return b"\x29\x09\x00\x00\x00\x00" + json.dumps(self.features).encode()
        if opcode == 26 and len(request) == 2:
            tag = request[1]
            _, width = CONFIG[tag]
            value = (
                b"\xff\xff\xff"
                if width == "rgb"
                else (int(self.paused) if tag == 4 else 0).to_bytes(width, "little")
            )
            return bytes([27, tag]) + value
        if opcode == 8:
            status = self._next_status()
            return b"\x09" + b"".join(
                bytes([tag]) + status[STATUS[tag][0]].to_bytes(STATUS[tag][1], "little")
                for tag in request[1:]
            )
        if request == b"\x2c":
            jobs = (
                [self.job_id] if self.snapshot["current_job_id"] else []
            ) + self.extra_jobs
            return b"\x2d" + b"".join(j.to_bytes(2, "little") for j in jobs)
        if request == b"\x3a\x01\x00\x00":
            return b"\x3b\x01\x00\x00" + struct.pack(
                "<HIHI", 1, self.pages, 3, self.calibrations
            )
        if opcode in (12, 48, 14):
            self.mutations.append(request)
        if opcode == 12:
            if self.expected_bytes is not None:
                return b"\x01\x0c\x08"
            assert len(request) == 6 and request[1] == 1
            self.expected_bytes = int.from_bytes(request[2:], "little")
            return b"\x0d" + struct.pack("<BH", self.handle, self.job_id)
        if opcode == 48:
            assert request[1:3] == self.job_id.to_bytes(2, "little")
            assert request[3] == 3 and request[5] == 1
            size, start = read_varuint(request, 6)
            if size > self.name_limit or len(request) != start + size:
                return b"\x01\x30\x07"
            self.copies, self.name = request[4], request[start:].decode("utf-8")
            if self.copies_expected is not None:
                assert self.copies == self.copies_expected
            return b"\x31"
        if opcode == 14:
            assert request[1] == self.handle and self.copies is not None
            assert len(request) <= self.maximum and not self.finished_upload
            self.uploaded.extend(request[2:])
            assert len(self.uploaded) <= self.expected_bytes
            complete = len(self.uploaded) == self.expected_bytes
            if self.require_empty_final and len(request) > 2:
                complete = False
            self.finished_upload = complete
            return b"\x0f" + struct.pack(
                "<BBII",
                self.handle,
                2 if complete else 1,
                len(self.uploaded),
                self.expected_bytes,
            )
        raise AssertionError(f"Unexpected simulated request opcode {opcode:#x}")

    async def write(self, data):
        if self.closed:
            raise ConnectionError("Simulated stream closed")
        messages = []
        for offset in range(0, len(data), self.write_fragment):
            messages.extend(
                self.rx_parser.feed(data[offset : offset + self.write_fragment])
            )
        for request in messages:
            self.requests.append(request)
            response = self._respond(request)
            action = self.fault(request, response, self) if self.fault else response
            if isinstance(action, BaseException):
                # write may fail even after the remote accepted all bytes.
                raise action
            if action is None:
                self.hang = True
                continue
            if self.events_enabled:
                self.response_bytes.extend(frame(b"\x03\x01\x00\x01"))
            self.response_bytes.extend(frame(action))

    async def read(self, maximum):
        if self.hang:
            await asyncio.Event().wait()
        if self.pending_error:
            raise self.pending_error
        size = min(maximum, self.read_size, len(self.response_bytes))
        data = bytes(self.response_bytes[:size])
        del self.response_bytes[:size]
        return data

    async def close(self):
        self.closed = True


class ScriptedStream:
    """Small stream fixture for framing faults without a simulated protocol."""

    def __init__(self, chunks):
        self.chunks, self.writes = deque(chunks), []
        self.closed = False

    async def write(self, data):
        self.writes.append(data)

    async def read(self, maximum):
        return self.chunks.popleft() if self.chunks else b""

    async def close(self):
        self.closed = True
