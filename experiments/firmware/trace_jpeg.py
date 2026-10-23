#!/usr/bin/env python3
"""Hash-pinned, offline execution of FS2105 JPEG header parsing and sampling setup.

No entropy decoding, image hardware, printer access, or network access. Actual ARM
parses the supplied bytes; only stream refill, division, and logging are stubbed.
"""

import argparse
import json
import struct
from pathlib import Path

from inspect_rbn import inflate_main, partitions, sha256
from trace_lut import MAIN_SHA, RBN_SHA, RELOCATION, FirmwareArithmetic

BASE = 0x400000
CONTEXT = BASE + 0x47A8
INPUT = 0x500000
MAX_INPUT = 0x100000


class JpegHeaders(FirmwareArithmetic):
    def __init__(self, data):
        if sha256(data) != RBN_SHA:
            raise ValueError("requires the exact documented G1L1FS2105AR package")
        parts = partitions(data)
        main, _ = inflate_main(parts["FIRMWARE"][2])
        self.loaded = False
        self.data = b""
        self.stream_exhausted = False
        self.log_messages = []
        super().__init__(main, [])

    def _block(self, uc, address, size, data):
        off, reg = address + RELOCATION, self.reg
        if off in (0xAC2C0, 0x38D7C, 0x8C54C):
            value = 0
            if off == 0xAC2C0:
                ctx = uc.reg_read(reg.UC_ARM_REG_R0)
                if ctx != CONTEXT:
                    raise RuntimeError("unexpected stream context")
                if not self.loaded:
                    self.loaded = True
                    self.write32(ctx + 0x6B8, len(self.data))
                    self.write32(ctx + 0x6C0, INPUT)
                    value = 1
                else:
                    self.stream_exhausted = True
                    # Synthetic transport EOF, not a recovered vendor EOF code.
                    self.write32(ctx + 0x684, self.read32(ctx + 0x684) | 0x40)
            elif off == 0x38D7C:
                value, remainder = divmod(
                    uc.reg_read(reg.UC_ARM_REG_R0), uc.reg_read(reg.UC_ARM_REG_R1)
                )
                uc.reg_write(reg.UC_ARM_REG_R1, remainder)
            else:
                pointer = uc.reg_read(reg.UC_ARM_REG_R0)
                if 0 < pointer < 0x3FFF00:
                    msg = bytes(uc.mem_read(pointer, 180)).split(b"\0", 1)[0]
                    self.log_messages.append(
                        msg.decode("ascii", errors="replace").lstrip("\x11\x14")
                    )
            uc.reg_write(reg.UC_ARM_REG_R0, value)
            uc.reg_write(reg.UC_ARM_REG_PC, uc.reg_read(reg.UC_ARM_REG_LR))
            return
        allowed = (
            (0xAB62C, 0xAB64C),
            (0xAB8C8, 0xAB934),
            (0xAB96C, 0xAB9E0),
            (0xAB9F8, 0xABC28),
            (0xABC28, 0xABD18),
            (0xABDD0, 0xABED0),
            (0xABF2C, 0xAC064),
            (0xAC0EC, 0xAC1E8),
            (0xAC7FC, 0xACAA8),
            (0xAD224, 0xAD3C0),
            (0xAD4BC, 0xAD628),
            (0x64438, 0x646F8),
        )
        if any(lo <= off and off + size <= hi for lo, hi in allowed):
            return
        raise RuntimeError(f"unexpected firmware execution at {off:#x}, size {size}")

    def read32(self, address):
        return struct.unpack("<I", self.uc.mem_read(address, 4))[0]

    def parse(self, data, progressive_enabled=True):
        if not 2 <= len(data) <= MAX_INPUT:
            raise ValueError("fixture must have 2..1048576 bytes")
        self.loaded, self.stream_exhausted, self.log_messages = False, False, []
        self.data = data
        self.uc.mem_write(BASE, bytes(0x8000))
        self.uc.mem_write(INPUT, data)
        self.write32(CONTEXT + 0x6DC, BASE)
        # Both branches of the normal app's decoder setup pass enable=1.
        # Allocation callbacks and later progressive execution are not modeled.
        self.write32(BASE + 0x3A8, int(progressive_enabled))
        status = self.call(0xABDD0, (BASE,))
        frame = bytes(self.uc.mem_read(CONTEXT + 0x37C, 28))
        components = [
            list(self.uc.mem_read(CONTEXT + 0x398 + i * 12, 5))
            for i in range(min(frame[15], 3))
        ]
        progressive = bool(self.read32(BASE + 0x55C4))
        table_ids = sorted({c[4] for c in components})
        tables = [
            bytes(self.uc.mem_read(CONTEXT + 0x56C + 64 * i, 64)) for i in table_ids
        ]
        return {
            "input_bytes": len(data),
            "input_sha256": sha256(data),
            "status": status,
            "error_flags_hex": hex(self.read32(CONTEXT + 0x684)),
            "synthetic_stream_eof": self.stream_exhausted,
            "width": struct.unpack_from("<H", frame)[0],
            "height": struct.unpack_from("<H", frame, 2)[0],
            "precision": frame[14],
            "components": frame[15],
            "component_id_index_h_v_q": components,
            "progressive_recognized": progressive,
            "sampling_setup_executed": status == 0 and not progressive,
            "sampling_mode": self.read32(BASE + 0x3D4)
            if status == 0 and not progressive
            else None,
            "mcu_blocks": frame[19] if status == 0 and not progressive else None,
            "quantization_range": [min(b"".join(tables)), max(b"".join(tables))]
            if tables
            else None,
            "diagnostics": [
                m
                for m in self.log_messages
                if any(
                    word in m.lower()
                    for word in ("error", "unsupported", "not support", "zero", "wrong")
                )
            ],
        }


def run(rbn, inputs, progressive_enabled=True):
    arm = JpegHeaders(rbn)
    return {
        "firmware_sha256": RBN_SHA,
        "main_sha256": MAIN_SHA,
        "scope": "Header parser and baseline sampling setup only; no entropy decode, RGB reconstruction, hardware, or physical print",
        "unicorn_version": __import__("unicorn").__version__,
        "stubs": {
            "0xac2c0": "bounded in-memory stream refill; synthetic EOF",
            "0x38d7c": "positive integer division quotient/remainder",
            "0x8c54c": "log sink",
        },
        "progressive_enabled_fixture": progressive_enabled,
        "cases": {
            name: arm.parse(data, progressive_enabled) for name, data in inputs.items()
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rbn", type=Path)
    parser.add_argument("images", type=Path, nargs="+")
    parser.add_argument("--disable-progressive", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.rbn.read_bytes(),
                {str(p): p.read_bytes() for p in args.images},
                not args.disable_progressive,
            ),
            indent=2,
        )
    )
