#!/usr/bin/env python3
"""Hash-pinned, offline checks of BLE -> shared printer dispatch in FS2105.

Requires capstone and the private inflated main image. Reuses the established
HCD reconstruction; emits numeric evidence only. Does not execute firmware or
access any device. Function names are research interpretations, not symbols.
"""

import argparse
import hashlib
import json
import struct
from pathlib import Path

from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
from trace_ios_transport import MAIN_SHA, reconstruct


def inspect(data):
    memory, end = reconstruct(data)
    decoder = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

    def word(address):
        return struct.unpack_from("<I", memory, address)[0]

    def expect(actual, expected):
        if actual != expected:
            raise ValueError(f"Evidence mismatch: {actual!r} != {expected!r}")

    instruction_checks = []

    def instruction(address, mnemonic, operands):
        item = next(decoder.disasm(memory[address : address + 4], address, count=1))
        expect((item.mnemonic, item.op_str), (mnemonic, operands))
        instruction_checks.append(
            {
                "address": hex(address),
                "mnemonic": mnemonic,
                "operands": operands,
            }
        )

    configurations = {}
    for name, address, framing in (
        ("BLE", 0x224308, 0x221134),
        ("SPP", 0x224354, 0x221118),
        ("iAP", 0x224384, 0x221118),
    ):
        expect(word(address), 0x221150)
        expect(word(address + 4), framing)
        expect(word(address + 12), 0x2245E4)
        configurations[name] = {
            "address": hex(address),
            "framing_table": hex(framing),
            "message_callbacks": hex(word(address)),
            "printer_handlers": hex(word(address + 12)),
        }
    expect(word(0x217D04), 0x224308)  # BLE initializer's PC-relative literal.
    expect(word(0x221134 + 12), 0x21CD9D)  # Thumb BLE receiver.
    expect(word(0x221150 + 8), 0x21DE4F)  # Complete-message callback.
    expect(word(0x2245E4 + 0x14), 0x21A875)  # Print-start handler.
    expect(word(0x2245E4 + 0x18), 0x21BD85)  # Empty file write.
    expect(word(0x2245E4 + 0x1C), 0x21BDC9)  # Nonempty file write.

    for args in (
        (0x217CE0, "bl", "#0x21b7f0"),
        (0x217D94, "cmp", "r1, #0x62"),  # Firmware ATT value handle.
        (0x217DBA, "bl", "#0x217d60"),
        (0x217D74, "bl", "#0x21de98"),
        (0x21DE98, "ldr", "r3, [r0, #0x6c]"),
        (0x21DE9A, "ldr", "r3, [r3, #4]"),
        (0x21DE9C, "ldr", "r3, [r3, #0xc]"),
        (0x21CE44, "ldr", "r3, [r6, #0x6c]"),
        (0x21CE48, "ldr", "r3, [r3]"),
        (0x21CE4A, "ldr", "r3, [r3, #8]"),
        (0x21DE64, "bl", "#0x21cfe4"),
        (0x21D034, "ldrb.w", "r8, [r5, #0x18]"),
        (0x21D038, "bl", "#0x21eac0"),
        (0x21D03C, "cmp", "r8, r0"),
        (0x21D03E, "blo.w", "#0x21ddea"),
        (0x21D052, "tbh", "[pc, r4, lsl #1]"),
        (0x21D2DC, "ldr", "r3, [r3, #0xc]"),
        (0x21D2E0, "ldr", "r3, [r3, #0x14]"),
        (0x21D31E, "ldr", "r3, [r3, #0xc]"),
        (0x21D322, "ldr", "r3, [r3, #0x1c]"),
    ):
        instruction(*args)
    cases = {}
    for opcode, expected in ((12, 0x21D2CE), (14, 0x21D304), (36, 0x21D358)):
        offset = struct.unpack_from("<H", memory, 0x21D056 + (opcode - 4) * 2)[0]
        target = 0x21D056 + 2 * offset
        expect(target, expected)
        cases[str(opcode)] = hex(target)
    return {
        "main_sha256": MAIN_SHA,
        "hcd_end": hex(end),
        "reconstructed_memory_sha256": hashlib.sha256(memory).hexdigest(),
        "configurations": configurations,
        "dispatch_cases_decimal_opcode": cases,
        "instruction_checks": instruction_checks,
        "security_functions": ["0x21ea60", "0x21eab0", "0x21eac0"],
        "limitation": "Static FS image only; no execution or physical FA print acceptance test",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("main", type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect(args.main.read_bytes()), indent=2))
