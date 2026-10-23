#!/usr/bin/env python3
"""Offline inspector for the four observed GrandBahama-G1L1FS RBN packages.

Reads local files and emits metadata, hashes and small numeric summaries only.
No network, Bluetooth, firmware execution, flashing or vendor-binary extraction.
This is an observed-format research tool, not a general RBN/signature validator.
"""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import zlib


ROM_BASE = 0x80000000
DIRECTORY = 0x100000
MAX_MAIN = 16 * 1024 * 1024


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def string_offsets(data, text):
    offsets = []
    start = 0
    while (offset := data.find(text.encode(), start)) >= 0:
        offsets.append(hex(offset))
        start = offset + 1
    return offsets


def checked_slice(data, offset, size):
    if offset < 0 or size < 0 or offset + size > len(data):
        raise ValueError("region outside input file")
    return data[offset:offset + size]


def partitions(data):
    header = checked_slice(data, DIRECTORY, 40)
    if header[:4] != b"OART":
        raise ValueError("not the observed OART directory")
    count = struct.unpack_from("<I", header, 12)[0]
    strings_index = struct.unpack_from("<I", header, 24)[0]
    if not 1 <= count <= 256 or strings_index >= count:
        raise ValueError("invalid directory count/string-table index")
    raw = checked_slice(data, DIRECTORY + 40, count * 12)
    entries = list(struct.iter_unpack("<III", raw))
    address, size, _ = entries[strings_index]
    names = checked_slice(data, address - ROM_BASE, size).split(b"\0")
    if len(names) <= count or any(not name for name in names[:count]):
        raise ValueError("incomplete partition names")
    result = {}
    for name, (address, size, flags) in zip(names, entries):
        name = name.decode("ascii")
        if name in result:
            raise ValueError("duplicate partition name")
        offset = address - ROM_BASE
        payload = checked_slice(data, offset, size)
        result[name] = (offset, flags, payload)
    return result


def inflate_main(payload):
    decoder = zlib.decompressobj(31)
    main = decoder.decompress(payload, MAX_MAIN + 1)
    if len(main) > MAX_MAIN:
        raise ValueError("decompressed firmware exceeds research limit")
    if not decoder.eof:
        raise ValueError("incomplete gzip firmware stream")
    return main, len(decoder.unused_data)


def inspect(data, filename):
    parts = partitions(data)
    result = {
        "file": filename,
        "size": len(data),
        "sha256": sha256(data),
        "signature_verified": False,
        "partitions": {},
    }
    for name, (offset, flags, payload) in parts.items():
        result["partitions"][name] = {
            "offset": hex(offset), "size": len(payload), "flags": flags,
            "sha256": sha256(payload), "all_ff": bool(payload) and set(payload) == {255},
        }
    main, unused = inflate_main(parts["FIRMWARE"][2])
    result["main"] = {
        "size": len(main), "sha256": sha256(main),
        "unused_bytes_in_partition": unused,
        "diagnostic_string_offsets": {
            text: string_offsets(main, text)
            for text in ["JFIFFINIT", "__FACTORY_MODE__", "TPH Test Mode",
                         "Test Pattern Type Set", "Set MCal mode", "ZINK_THC"]
        },
    }
    tone = parts["TONESCALE"][2]
    values = struct.unpack("<768f", checked_slice(tone, 0, 3072))
    result["tone"] = {
        "float_count": len(values),
        "max_error_vs_triplicated_255_minus_i_over_100": max(
            abs(value - (255 - i // 3) / 100) for i, value in enumerate(values)),
        "remaining_bytes_all_ff": set(tone[3072:]) == {255},
        "duplicate_TONESCALEb": tone == parts["TONESCALEb"][2],
        "duplicate_MMT_and_MMT2": parts["MMT"][2] == parts["MMT2"][2],
    }
    result["luts"] = {}
    for i in range(1, 7):
        name = f"LUT{i}_Z21"
        payload = parts[name][2]
        records = checked_slice(payload, 0, 17 ** 3 * 4)
        result["luts"][name] = {
            "records": 17 ** 3, "record_bytes": 4,
            "remaining_bytes_all_ff": set(payload[len(records):]) == {255},
            "fourth_byte_range": [min(records[3::4]), max(records[3::4])],
            # Raw array indices only: this does not name RGB axes or dye amounts.
            "raw_corner_records": {
                str(index): list(records[index * 4:index * 4 + 4])
                for index in [0, 16, 272, 288, 4624, 4640, 4896, 4912]
            },
        }
    thermal = parts["ZINK_THC"][2]
    if thermal[:4] != b"zTHC" or struct.unpack_from("<I", thermal, 4)[0] != 2:
        raise ValueError("unrecognized zTHC layout")
    scaler, watts, ips, dpi, lpi = struct.unpack_from("<fffHH", thermal, 0x110)
    result["thermal"] = {
        "layout_version": 2,
        "scaler_at_0x110": scaler,
        "parameter_logged_W_at_0x114": watts,
        "parameter_logged_ips_at_0x118": ips,
        "parameter_logged_DPI_at_0x11c": dpi,
        "parameter_logged_LPI_at_0x11e": lpi,
        "date_string_at_0x128": thermal[0x128:0x148].split(b"\0")[0].decode("ascii"),
        "interpretation": "Configured values in downloaded FS firmware, not live FA measurements",
    }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()
    reports = [inspect(path.read_bytes(), path.name) for path in args.files]
    print(json.dumps(reports, indent=2))


if __name__ == "__main__":
    main()
