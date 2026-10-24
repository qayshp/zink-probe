"""Immutable input description and finite HPLPP upload plan."""

from __future__ import annotations

import hashlib
import struct
import uuid
from dataclasses import dataclass, field

from ..protocol import MAX_MESSAGE, ProtocolError


def require(condition, reason):
    if not condition:
        raise ProtocolError(reason)


def jpeg_info(data: bytes) -> dict:
    """Inspect baseline headers, not entropy validity or physical compatibility.

    A prepared Select image must be 768x1152, 8-bit, three-component baseline
    JPEG with the usual Y/Cb/Cr component IDs. No image library is required by
    the job core. Full decoding belongs to preparation, before submission.
    """
    require(isinstance(data, bytes), "JPEG input must be immutable bytes")
    require(4 <= len(data) <= 16 * 1024 * 1024, "JPEG exceeds the 16 MiB host bound")
    require(
        data[:2] == b"\xff\xd8" and data[-2:] == b"\xff\xd9", "Incomplete JPEG envelope"
    )
    offset, frame, quantization = 2, None, {}
    while offset < len(data) - 2:
        require(data[offset] == 255, "Invalid JPEG marker boundary")
        while offset < len(data) and data[offset] == 255:
            offset += 1
        require(offset + 3 <= len(data), "Truncated JPEG marker")
        marker = data[offset]
        size = int.from_bytes(data[offset + 1 : offset + 3], "big")
        require(
            size >= 2 and offset + 1 + size <= len(data), "Invalid JPEG segment size"
        )
        body = data[offset + 3 : offset + 1 + size]
        if marker == 0xC0:
            require(
                frame is None and len(body) == 15, "Expected one three-component frame"
            )
            precision, height, width, count = struct.unpack(">BHHB", body[:6])
            require(
                (width, height, precision, count) == (768, 1152, 8, 3),
                "Expected 768x1152 eight-bit RGB-prepared JPEG",
            )
            components = [tuple(body[i : i + 3]) for i in (6, 9, 12)]
            require(
                [c[0] for c in components] == [1, 2, 3],
                "Unsupported JPEG component IDs",
            )
            require(
                components[1][1] == components[2][1] == 0x11,
                "Unsupported chroma sampling",
            )
            sampling = {0x22: "4:2:0", 0x21: "4:2:2", 0x11: "4:4:4"}.get(
                components[0][1]
            )
            require(sampling is not None, "Unsupported luma sampling")
            frame = {
                "width": width,
                "height": height,
                "precision": precision,
                "sampling": sampling,
                "progressive": False,
                "quantization_ids": [c[2] for c in components],
            }
        elif 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            raise ProtocolError("Only baseline JPEG is enabled for job submission")
        elif marker == 0xDB:
            cursor = 0
            while cursor < len(body):
                selector = body[cursor]
                require(
                    selector < 4 and cursor + 65 <= len(body),
                    "Expected eight-bit quantization table",
                )
                table = body[cursor + 1 : cursor + 65]
                require(0 not in table, "Zero JPEG quantization value")
                quantization[selector] = table
                cursor += 65
        elif marker == 0xDA:
            require(frame is not None, "Scan precedes JPEG frame")
            require(
                all(i in quantization for i in frame["quantization_ids"]),
                "Missing quantization table",
            )
            require(
                len(body) == 10 and body[0] == 3 and body[-3:] == b"\x00\x3f\x00",
                "Unsupported baseline scan",
            )
            frame["quantization_all_ones"] = all(
                all(v == 1 for v in quantization[i])
                for i in frame.pop("quantization_ids")
            )
            return frame
        offset += 1 + size
    raise ProtocolError("JPEG scan header missing")


@dataclass(frozen=True)
class JobSpec:
    jpeg: bytes = field(repr=False)
    name: str = "Select photo"
    copies: int = 1
    local_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    allow_alternative_sampling: bool = False
    encoder_quality: int | None = None
    encoding: dict = field(init=False, repr=False, compare=False)
    sha256: str = field(init=False)

    def __post_init__(self):
        require(
            isinstance(self.name, str)
            and bool(self.name)
            and not any(ord(c) < 32 for c in self.name),
            "Invalid job name",
        )
        require(
            type(self.copies) is int and 1 <= self.copies <= 255,
            "Copies must be 1..255",
        )
        require(
            str(uuid.UUID(self.local_id)) == self.local_id, "Use a canonical local UUID"
        )
        require(
            self.encoder_quality is None
            or type(self.encoder_quality) is int
            and 1 <= self.encoder_quality <= 100,
            "Invalid declared encoder quality",
        )
        info = jpeg_info(self.jpeg)
        require(
            info["sampling"] == "4:2:0" or self.allow_alternative_sampling,
            "Alternative sampling requires explicit opt-in",
        )
        # This is encoder metadata, not inferred JPEG quality or engine quality.
        info["declared_encoder_quality"] = self.encoder_quality
        object.__setattr__(self, "encoding", info)
        object.__setattr__(self, "sha256", hashlib.sha256(self.jpeg).hexdigest())


def varuint(value):
    out = bytearray()
    while value >= 128:
        out.append((value & 127) | 128)
        value >>= 7
    out.append(value)
    return bytes(out)


class RemoteRejected(ProtocolError):
    def __init__(self, opcode, code):
        self.opcode, self.code = opcode, code
        super().__init__(f"Printer rejected opcode 0x{opcode:02x}, code 0x{code:02x}")


class UploadPlan:
    """One outstanding mutation. No retries, offset rewind, or reconnect/resume."""

    def __init__(self, spec: JobSpec, maximum: int, name_limit: int):
        self.spec = spec
        self.maximum = min(maximum, MAX_MESSAGE)
        name = spec.name.encode("utf-8")
        require(len(name) <= name_limit, "UTF-8 job name exceeds advertised byte limit")
        self.properties = (
            b"\x03" + bytes([spec.copies]) + b"\x01" + varuint(len(name)) + name
        )
        require(
            max(6, 3 + len(self.properties)) <= self.maximum,
            "Negotiated message limit too small",
        )
        self.phase = "start"
        self.offset = 0
        self.handle = self.job_id = self.pending = None
        self.empty_sent = False

    def next_message(self):
        require(self.pending is None, "Unacknowledged mutation; no resend")
        if self.phase == "start":
            message = b"\x0c\x01" + struct.pack("<I", len(self.spec.jpeg))
        elif self.phase == "properties":
            message = b"\x30" + struct.pack("<H", self.job_id) + self.properties
        elif self.phase == "upload":
            data = self.spec.jpeg[self.offset : self.offset + self.maximum - 2]
            require(data or not self.empty_sent, "Repeated empty final chunk refused")
            self.empty_sent |= not data
            message = b"\x0e" + bytes([self.handle]) + data
        else:
            raise ProtocolError("Upload plan is finished")
        self.pending = message
        return message

    def accept(self, reply):
        request = self.pending
        require(request is not None, "No outstanding mutation")
        if reply[:1] == b"\x01":
            require(
                len(reply) == 3 and reply[1] == request[0], "Uncorrelated error reply"
            )
            raise RemoteRejected(reply[1], reply[2])
        require(reply and reply[0] == request[0] + 1, "Unexpected mutation reply")
        if self.phase == "start":
            require(len(reply) == 4, "Malformed PrintStart response")
            self.handle, self.job_id = struct.unpack("<BH", reply[1:])
            require(self.job_id != 0, "Reserved zero job ID")
            self.phase = "properties"
        elif self.phase == "properties":
            require(reply == b"\x31", "Malformed job-property acknowledgement")
            self.phase = "upload"
        else:
            require(len(reply) == 11, "Malformed FileWrite response")
            handle, status, received, total = struct.unpack("<BBII", reply[1:])
            require(handle == self.handle, "Upload handle changed")
            require(total == len(self.spec.jpeg), "Upload total changed")
            require(
                received == self.offset + len(request) - 2,
                "Unexpected absolute upload offset",
            )
            require(status in (1, 2), f"Upload stopped with status {status}")
            require(status != 2 or received == total, "Premature upload completion")
            self.offset = received
            if status == 2:
                self.phase = "uploaded"
        self.pending = None
