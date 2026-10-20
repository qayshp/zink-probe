"""Independent implementation of the documented HP+ read-only subset.

System attributes are typed tag/value fields, NOT generic length/value records.
Unknown/truncated fields must stop decoding, rather than guessing their lengths.
"""

SERVICE = "6822d239-7b61-4718-bdc1-189221946209"
TX = "6822d239-7b61-4718-bdc1-de55b3f9051e"
RX = "6822d239-7b61-4718-bdc1-772fa9983658"
SELECT = 0x48D3
MAX_MESSAGE = 4096

ATTRIBUTES = {
    1: ("firmware", "string"),
    3: ("immutable_name", "string"),
    4: ("custom_name", "string"),
    5: ("serial_number", "string"),
    6: ("device_id", "bytes16"),
    8: ("feature_set_version", 2),
    9: ("super_model", 2),
    10: ("sub_model", 2),
    11: ("bluetooth_mac", "mac"),
    12: ("hardware_version", "string"),
}
STATUS = {
    1: ("system_flags", 4),
    2: ("print_status_code", 1),
    3: ("battery_percent", 1),
    4: ("print_progress_percent", 1),
    5: ("current_job_id", 2),
    6: ("battery_status_code", 1),
    7: ("queue_status_code", 1),
    8: ("copy_progress_percent", 1),
    9: ("number_of_hosts", 1),
}
STATES = {
    1: "idle",
    2: "preparing",
    3: "out_of_paper",
    4: "paper_jam",
    5: "calibrating",
    6: "tray_open",
    7: "printing",
    8: "overheating",
    9: "feed_path_obstructed",
    10: "out_of_supplies",
    11: "no_supplies_detected",
    12: "no_tray",
    13: "tray_misaligned",
    14: "unrecoverable_error",
    15: "battery_critical",
    16: "paper_pick",
    17: "multi_page_pick",
}


class ProtocolError(RuntimeError):
    pass


def validate_request(message: bytes) -> None:
    """Fail closed at each transport boundary; there is no arbitrary-command CLI."""
    if message in (b"\x0a\x01\x00", b"\x0a\x02", b"\x24\x00\x10"):
        return
    if len(message) >= 2 and message[0] == 4:
        if all(tag in ATTRIBUTES for tag in message[1:]):
            return
    if len(message) >= 2 and message[0] == 8:
        if all(tag in STATUS for tag in message[1:]):
            return
    raise ProtocolError(f"Request outside read-only allowlist: {message.hex()}")


def check_response(request: bytes, response: bytes) -> bytes:
    if response[:1] == b"\x01":
        raise ProtocolError(f"Printer rejected {request.hex()}: {response.hex()}")
    if not response or response[0] != request[0] + 1:
        raise ProtocolError(f"Unexpected reply to {request.hex()}: {response.hex()}")
    return response


def decode_fields(message: bytes, identity: bool = False) -> dict:
    expected = 5 if identity else 9
    if not message or message[0] != expected:
        raise ProtocolError(f"Expected response 0x{expected:02x}: {message.hex()}")
    fields = ATTRIBUTES if identity else STATUS
    result = {}
    offset = 1
    while offset < len(message):
        tag = message[offset]
        offset += 1
        if tag not in fields:
            raise ProtocolError(f"Unknown field 0x{tag:02x} at offset {offset - 1}")
        name, kind = fields[tag]
        if kind == "string":
            if offset >= len(message):
                raise ProtocolError(f"Missing length for {name}")
            size = message[offset]
            offset += 1
        else:
            size = {"mac": 6, "bytes16": 16}.get(kind, kind)
        if offset + size > len(message):
            raise ProtocolError(f"Truncated field {name}")
        value = message[offset : offset + size]
        offset += size
        if kind == "string":
            result[name] = value.rstrip(b"\x00").decode("utf-8", errors="replace")
        elif kind == "mac":
            result[name] = ":".join(f"{b:02X}" for b in reversed(value))
        elif kind == "bytes16":
            # Select returns a fixed 16-byte ID, not a length-prefixed string.
            # Preserve wire order without assuming UUID field endianness.
            result[name] = value.hex()
        else:
            result[name] = int.from_bytes(value, "little")
    if "print_status_code" in result:
        result["print_status"] = STATES.get(result["print_status_code"], "unknown")
    return result


def encode_rfcomm(message: bytes) -> bytes:
    validate_request(message)
    return b"HP+\x01" + bytes([len(message)]) + message


class RfcommParser:
    """Length-based stream parser: preserves partial frames and coalesced replies."""

    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data: bytes) -> list[bytes]:
        self.buffer.extend(data)
        messages = []
        while len(self.buffer) >= 4:
            if self.buffer[:3] != b"HP+":
                raise ProtocolError(f"Invalid RFCOMM magic: {self.buffer[:16].hex()}")
            flag = self.buffer[3]
            if flag not in (1, 2):
                raise ProtocolError(f"Invalid RFCOMM length flag {flag}")
            start = 5 if flag == 1 else 6
            if len(self.buffer) < start:
                break
            size = int.from_bytes(self.buffer[4:start], "little")
            if not 1 <= size <= MAX_MESSAGE:
                raise ProtocolError(f"Invalid RFCOMM message length {size}")
            if len(self.buffer) < start + size:
                break
            messages.append(bytes(self.buffer[start : start + size]))
            del self.buffer[: start + size]
        return messages


class BleAssembler:
    def __init__(self):
        self.reset()

    def reset(self):
        self.buffer = bytearray()
        self.sequence = 0

    def feed(self, frame: bytes, ack_period: int) -> tuple[bytes | None, bool]:
        if frame == b"\x00":
            return None, False
        if len(frame) < 2:
            raise ProtocolError("Empty or header-only BLE data frame")
        header = frame[0]
        sequence = header & 0x7F
        if sequence != self.sequence + 1:
            self.reset()
            raise ProtocolError(f"Unexpected BLE sequence {sequence}")
        self.sequence = sequence
        self.buffer.extend(frame[1:])
        if len(self.buffer) > MAX_MESSAGE:
            self.reset()
            raise ProtocolError("BLE message exceeds host receive limit")
        if header & 0x80:
            result = bytes(self.buffer)
            self.reset()
            return result, False
        return None, bool(ack_period and sequence % ack_period == 0)
