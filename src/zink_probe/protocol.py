"""Independent implementation of the documented HP+ read-only subset.

System attributes are typed tag/value fields, NOT generic length/value records.
Unknown/truncated fields must stop decoding, rather than guessing their lengths.
"""

SERVICE = "6822d239-7b61-4718-bdc1-189221946209"
TX = "6822d239-7b61-4718-bdc1-de55b3f9051e"
RX = "6822d239-7b61-4718-bdc1-772fa9983658"
SELECT = 0x48D3
MAX_MESSAGE = 4096
SYSTEM_FLAG_NAMES = {
    0: "time_invalid",
    1: "battery_critical",
    2: "print_busy",
    3: "out_of_paper",
    4: "low_on_supplies",
}
BATTERY_NAMES = {1: "in_use", 2: "charging", 3: "overheat", 4: "error"}
QUEUE_NAMES = {1: "empty", 2: "full", 3: "paused", 4: "populated"}
ERROR_NAMES = {
    1: "unspecified",
    2: "transport",
    3: "unauthorized",
    4: "command_not_supported",
    5: "not_found",
    6: "invalid_arguments",
    7: "invalid_length",
    8: "illegal_state",
    9: "insufficient_resources",
    10: "interface_mismatch",
    11: "check_failed",
    12: "not_allowed",
    13: "timeout",
    14: "malformed_message",
    15: "operation_not_supported",
    16: "operation_failed",
    17: "battery_low",
    18: "retry",
}
# Bounded read-only experiments. No arbitrary command/field sweep is exposed.
RESEARCH_REQUESTS = (
    b"\x04\x02",
    b"\x04\x07",
    b"\x04\x0d",
    b"\x1a\x06",
    b"\x1a\x07",
    b"\x1a\x08",
    b"\x2c",
    b"\x04\x0f",
    b"\x04\x10",
    b"\x04\x11",
    b"\x04\x12",
    b"\x08\x0f",
    b"\x08\x10",
    b"\x08\x11",
    b"\x08\x12",
)

ATTRIBUTES = {
    1: ("firmware", "string"),
    2: ("protocol_version", 2),
    3: ("immutable_name", "string"),
    4: ("custom_name", "string"),
    5: ("serial_number", "string"),
    6: ("device_id", "bytes16"),
    7: ("security_mode_raw", 1),
    8: ("feature_set_version", 2),
    9: ("super_model", 2),
    10: ("sub_model", 2),
    11: ("bluetooth_mac", "mac"),
    12: ("hardware_version", "string"),
    13: ("setup_raw", 1),
    14: ("born_on_timestamp", 4),
}
CONFIG = {
    1: ("sleep_timer_minutes", 2),
    2: ("auto_off_minutes", 2),
    3: ("led_rgb", "rgb"),
    4: ("pause_printing_raw", 1),
    5: ("hosts_threshold_raw", 1),
}
# Reported by a cross-device PrintMaker HPLPP implementation, not Select-verified.
# Read individually and preserve entire replies; do not assume value widths.
EXTRA_STATUS_HINTS = {
    10: "supply_type",
    11: "supply_level",
    12: "supply_version",
    13: "supply_selectability",
    14: "cap_status",
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


def validate_request(message: bytes, read_handles=()) -> None:
    """Fail closed at each transport boundary; there is no arbitrary-command CLI."""
    if message in (b"\x0a\x01\x00", b"\x0a\x02", b"\x24\x00\x10"):
        return
    if message == b"\x2a":  # FEATURE_DISCOVERY_REQ, proven by HP app definitions.
        return
    if (
        len(message) == 3
        and message[0] == 0x28
        and message[2] == 1
        and message[1] in read_handles
    ):
        return
    if len(message) == 4 and message[:2] == b"\x3a\x01":  # Dataset 1, iterator LE.
        return
    if message in RESEARCH_REQUESTS:
        return
    if len(message) >= 2 and message[0] == 4:
        if all(tag in ATTRIBUTES for tag in message[1:]):
            return
    if len(message) >= 2 and message[0] == 8:
        if all(tag in STATUS for tag in message[1:]):
            return
        if len(message) == 2 and message[1] in EXTRA_STATUS_HINTS:
            return
    if len(message) == 2 and message[0] == 0x1A and message[1] in CONFIG:
        return
    raise ProtocolError(f"Request outside read-only allowlist: {message.hex()}")


def check_response(request: bytes, response: bytes) -> bytes:
    if response[:1] == b"\x01":
        name = (
            ERROR_NAMES.get(response[2], "unknown")
            if len(response) >= 3
            else "truncated_error"
        )
        raise ProtocolError(
            f"Printer rejected {request.hex()}: {response.hex()} ({name})"
        )
    if not response or response[0] != request[0] + 1:
        raise ProtocolError(f"Unexpected reply to {request.hex()}: {response.hex()}")
    return response


def read_varuint(data, offset):
    value = 0
    for i in range(5):
        if offset + i >= len(data):
            raise ProtocolError("Truncated string length")
        byte = data[offset + i]
        value |= (byte & 0x7F) << (7 * i)
        if not byte & 0x80:
            return value, offset + i + 1
    raise ProtocolError("String length exceeds variable-integer limit")


def decode_fields(message: bytes, identity: bool = False, config: bool = False) -> dict:
    expected = 0x1B if config else (5 if identity else 9)
    if not message or message[0] != expected:
        raise ProtocolError(f"Expected response 0x{expected:02x}: {message.hex()}")
    fields = CONFIG if config else (ATTRIBUTES if identity else STATUS)
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
            size, offset = read_varuint(message, offset)
        else:
            size = {"mac": 6, "bytes16": 16, "rgb": 3}.get(kind, kind)
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
        elif kind == "rgb":
            result[name] = list(value)
        else:
            result[name] = int.from_bytes(value, "little")
    if "print_status_code" in result:
        result["print_status"] = STATES.get(result["print_status_code"], "unknown")
    if "battery_status_code" in result:
        result["battery_status"] = BATTERY_NAMES.get(
            result["battery_status_code"], "unknown"
        )
    if "queue_status_code" in result:
        result["queue_status"] = QUEUE_NAMES.get(result["queue_status_code"], "unknown")
    if "system_flags" in result:
        result["system_flag_labels"] = [
            name
            for bit, name in SYSTEM_FLAG_NAMES.items()
            if result["system_flags"] & (1 << bit)
        ]
        result["system_flags_unknown_mask"] = result["system_flags"] & ~0x1F
    return result


def bit_view(value: int, width: int) -> dict:
    """An observation, not a declaration that this field actually is a bitmask."""
    return {
        "raw": value,
        "hex": f"0x{value:0{width // 4}X}",
        "binary": f"{value:0{width}b}",
        "set_bit_positions": [i for i in range(width) if value & (1 << i)],
        "meaning": "undecoded; may be an enum rather than independent flags",
    }


def encode_rfcomm(message: bytes, read_handles=()) -> bytes:
    validate_request(message, read_handles)
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
