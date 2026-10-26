#!/usr/bin/env python3
"""Offline numeric evidence for the embedded FS2105 Bluetooth HCD image.

No device access, execution, flashing or vendor binary output. Input is the
private inflated main image from inspect_rbn. Addresses are hash-specific.
"""

import argparse
import hashlib
import json
import struct
from pathlib import Path

MAIN_SHA = "4cc83261d16ab8078db3a38ae694017c26e6c681e1eca1e9bb41a437704c24ce"
START, COUNT = 0x12583A, 452


def reconstruct(data):
    if hashlib.sha256(data).hexdigest() != MAIN_SHA:
        raise ValueError("unsupported main image")
    memory = bytearray(0x400000)
    offset, count = START, 0
    while data[offset : offset + 2] == b"\x4c\xfc":
        size = data[offset + 2]
        if size < 4 or offset + 3 + size > len(data):
            raise ValueError("invalid HCD record")
        address = struct.unpack_from("<I", data, offset + 3)[0]
        body = data[offset + 7 : offset + 3 + size]
        if address + len(body) > len(memory):
            raise ValueError("HCD address outside bound")
        memory[address : address + len(body)] = body
        offset += 3 + size
        count += 1
    if count != COUNT:
        raise ValueError("unexpected HCD record count")
    return memory, offset


def inspect(data):
    memory, end = reconstruct(data)

    def word(address):
        return struct.unpack_from("<I", memory, address)[0]

    # iAP-specific connection configuration -> shared framing vtable.
    assert word(0x218880) == 0x224384
    assert word(0x224384 + 4) == 0x221118
    assert word(0x221118 + 8) == 0x21C93D  # Thumb send callback
    assert word(0x221118 + 12) == 0x21CA0D  # Thumb receive callback
    assert word(0x2243AC) == 0x2188F5  # iAP output adapter
    assert word(0x224384 + 36) == 0x2186CD  # iAP receive callback
    assert memory[0x221110:0x221117] == b"\x01\x02\x04HP+\x00"
    assert (
        memory[0x224337 : 0x224337 + len(b"com.hp.protocol.lifestyle\x00")]
        == b"com.hp.protocol.lifestyle\x00"
    )
    return {
        "main_sha256": MAIN_SHA,
        "hcd_start": hex(START),
        "hcd_end": hex(end),
        "records": COUNT,
        "reconstructed_memory_sha256": hashlib.sha256(memory).hexdigest(),
        "protocol_address": "0x224337",
        "iap_connection_initializer": "0x2187c8",
        "iap_transport_configuration": "0x224384",
        "framing_vtable": "0x221118",
        "iap_receive_callback": "0x2186cc",
        "receive_dispatch": "0x21de98",
        "hp_frame_receiver": "0x21ca0c",
        "hp_frame_sender": "0x21c93c",
        "iap_output_adapter": "0x2188f4",
        "magic": "48502b",
        "length_width_table": [1, 2, 4],
        "limitation": "Related FS firmware; not a dump of the physical FA firmware",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("main", type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect(args.main.read_bytes()), indent=2))
