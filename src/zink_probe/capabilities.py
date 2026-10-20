"""Read-only capability-table download and metrics dataset 1.

Wire definitions recovered from static inspection of an HP app artifact. The
implementation is independent; no vendor code or binaries are distributed.
"""

import json

from .protocol import ProtocolError, check_response

# tag: (wire field name, scalar byte width, array). Colors are 3 wire-order bytes.
FEATURE_FIELDS = {
    1: ("version", 2, False),
    2: ("proto_version", 2, False),
    3: ("requests", 1, True),
    4: ("sec_modes", 1, True),
    5: ("auth_modes", 1, True),
    6: ("key_schemas", 1, True),
    7: ("mime", 1, True),
    8: ("job_prop", 1, True),
    9: ("multi_key", 1, True),
    10: ("sys_cfg", 1, True),
    11: ("ifs", 1, True),
    12: ("sys_att", 1, True),
    13: ("status", 1, True),
    14: ("partial_reset", 1, False),
    15: ("color_palette", 3, True),
    16: ("color_palette_ux", 3, True),
    17: ("resource", 1, True),
    18: ("target_evt", 1, True),
    19: ("custom_name_max", 2, False),
    20: ("job_name_max", 2, False),
    21: ("trigger_actions", 2, True),
    22: ("auxiliary_url_max", 2, False),
    23: ("metrics_db", 1, True),
    24: ("update_type", 4, True),
    25: ("update_timing", 1, True),
}
METRIC_NAMES = {
    1: "printer_pages",
    2: "paper_jams",
    3: "printer_calibration_card_cycles",
    4: "out_of_paper",
    5: "long_power_presses",
    6: "sleep_events_manual",
    7: "usb_attach_events",
    8: "battery_level_precharge",
    9: "top_cover_open",
    10: "pages_increment_last_cover_open",
    11: "pages_increment_last_calibration",
    12: "power_on",
    13: "reset_presses",
    14: "incorrect_paper_type",
    18: "concurrent_devices",
    19: "sleep_events",
    20: "power_off_auto",
    22: "signal_strength",
}


def varuint(data, offset=0):
    number = 0
    for i in range(5):
        if offset + i >= len(data):
            raise ProtocolError("Truncated variable-length integer")
        value = data[offset + i]
        number |= (value & 0x7F) << (7 * i)
        if not value & 0x80:
            return number, offset + i + 1
    raise ProtocolError("Variable-length integer exceeds limit")


def decode_feature_table(data, encoding):
    if encoding == 1:
        return json.loads(data)
    if encoding != 2:
        raise ProtocolError(f"Unknown feature table encoding {encoding}")
    result, offset = {}, 0
    while offset < len(data):
        if len(data) - offset < 3:
            raise ProtocolError("Truncated feature TLV header")
        tag = data[offset]
        size = int.from_bytes(data[offset + 1 : offset + 3], "little")
        offset += 3
        raw = data[offset : offset + size]
        if len(raw) != size:
            raise ProtocolError("Truncated feature TLV value")
        offset += size
        if tag not in FEATURE_FIELDS:
            result[f"unknown_0x{tag:02X}"] = raw.hex()
            continue
        name, width, array = FEATURE_FIELDS[tag]
        count, start = varuint(raw) if array else (1, 0)
        if len(raw) - start != count * width:
            raise ProtocolError(f"Invalid feature value length for {name}")
        values = [
            raw[start + i * width : start + (i + 1) * width] for i in range(count)
        ]
        decoded = [
            "#" + item.hex() if width == 3 else int.from_bytes(item, "little")
            for item in values
        ]
        result[name] = decoded if array else decoded[0]
    return result


async def read_capabilities(connection):
    request = b"\x2a"
    response = await connection.exchange(request)
    if response[:2] == b"\x01\x2a":
        return {"error": response.hex()}
    check_response(request, response)
    if len(response) != 3:
        raise ProtocolError("Invalid feature-discovery reply")
    handle, encoding = response[1:]
    data = bytearray()
    connection.read_handles.add(handle)
    try:
        for _ in range(64):
            request = bytes([0x28, handle, 1])
            response = await connection.exchange(request)
            check_response(request, response)
            if len(response) < 6 or response[1] != handle:
                raise ProtocolError("Invalid capability file-read reply")
            remaining = int.from_bytes(response[2:6], "little")
            data.extend(response[6:])
            if len(data) > 65536:
                raise ProtocolError("Capability table exceeds 64 KiB bound")
            if remaining == 0:
                return {
                    "encoding": encoding,
                    "length": len(data),
                    "raw_hex": data.hex(),
                    "table": decode_feature_table(bytes(data), encoding),
                }
            if len(response) == 6:
                raise ProtocolError("Capability file read made no progress")
        raise ProtocolError("Capability download exceeded chunk bound")
    finally:
        connection.read_handles.discard(handle)


async def read_metrics(connection):
    iterator, seen, values, pages = 0, set(), {}, []
    for _ in range(16):
        if iterator in seen:
            raise ProtocolError("Repeated metrics iterator")
        seen.add(iterator)
        request = b"\x3a\x01" + iterator.to_bytes(2, "little")
        response = await connection.exchange(request)
        if response[:2] == b"\x01\x3a":
            return {"error": response.hex(), "values": values, "pages": pages}
        check_response(request, response)
        if len(response) < 4 or response[1] != 1 or (len(response) - 4) % 6:
            raise ProtocolError("Malformed metrics dataset 1 reply")
        pages.append(response.hex())
        for offset in range(4, len(response), 6):
            key = int.from_bytes(response[offset : offset + 2], "little")
            value = int.from_bytes(response[offset + 2 : offset + 6], "little")
            values[str(key)] = {
                "name": METRIC_NAMES.get(key, "unknown"),
                "value": value,
            }
        iterator = int.from_bytes(response[2:4], "little")
        if iterator == 0:
            return {"dataset": 1, "values": values, "pages": pages}
    raise ProtocolError("Metrics pagination exceeded 16-page bound")
