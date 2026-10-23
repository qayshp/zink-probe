#!/usr/bin/env python3
"""Offline, hash-pinned ARM/Python comparison of G1L1FS2105AR LUT routines.

Requires unicorn==2.1.4 in a separate research environment. Reads one local RBN;
emits numeric evidence, not firmware or LUT contents. No printer/network access.
Only selected arithmetic routines run, with synthetic state and service stubs.
This is not a whole-firmware emulator, host color correction, or update utility.
"""

import argparse
import itertools
import json
import math
from pathlib import Path
import random
import struct

from inspect_rbn import inflate_main, partitions, sha256


RBN_SHA = "68cc7a635342e1e882b1e552c9d1ee2803b1c5928d61a0612f69e689d9f08a60"
MAIN_SHA = "4cc83261d16ab8078db3a38ae694017c26e6c681e1eca1e9bb41a437704c24ce"
RECORD_BYTES = 17 ** 3 * 4
RELOCATION = 0xC0
STATE = 0x1578B4
KNOTS = 0x15786C
STOP = 0x7FF000
COLORS = {
    "black": (0, 0, 0), "white": (255, 255, 255),
    "cyan": (0, 255, 255), "magenta": (255, 0, 255),
    "yellow": (255, 255, 0), "gray128": (128, 128, 128),
}


def f32(value):
    return struct.unpack("<f", struct.pack("<f", value))[0]


def trunc_div(value, divisor):
    return value // divisor if value >= 0 else -((-value) // divisor)


def selection(temperature):
    """Initial selection, including its half-degree subtraction and quantization."""
    if not math.isfinite(temperature):
        raise ValueError("temperature must be finite")
    effective = min(70.0, max(20.0, f32(f32(temperature) - 0.5)))
    interval = min(4, int((effective - 20.0) / 10.0))
    low = 20.0 + interval * 10.0
    weight = int(f32(effective - low) * 25.6)
    return interval, weight, low + weight * (10.0 / 256)


def blend(lower, upper, weight):
    if len(lower) != RECORD_BYTES or len(upper) != RECORD_BYTES:
        raise ValueError("expected 4913 four-byte records")
    if not 0 <= weight <= 256:
        raise ValueError("weight outside initial-selection range")
    result = bytearray(RECORD_BYTES)
    for i, (base, following) in enumerate(zip(lower, upper)):
        delta = ((following - base + 128) % 256) - 128
        bias = 128 if i % 4 == 3 else 0
        result[i] = (base + trunc_div(delta * weight + bias, 256)) % 256
    return bytes(result)


def interpolate(table, rgb):
    """Four-lane trilinear interpolation on nodes 0,16,...,256 (input <=255)."""
    if len(table) != RECORD_BYTES or len(rgb) != 3 or any(
            not isinstance(x, int) or not 0 <= x <= 255 for x in rgb):
        raise ValueError("expected a complete map and three uint8 input values")
    base = [v >> 4 for v in rgb]
    frac = [v & 15 for v in rgb]
    total = [0] * 4
    for corner in itertools.product((0, 1), repeat=3):
        indices = [base[i] + corner[i] for i in range(3)]
        index = indices[0] * 289 + indices[1] * 17 + indices[2]
        weight = math.prod(frac[i] if corner[i] else 16-frac[i] for i in range(3))
        for lane in range(4):
            total[lane] += table[index * 4 + lane] * weight
    return tuple(value >> 12 for value in total)


class FirmwareArithmetic:
    """No hardware mapping, fixed call targets, bounded instructions and runtime."""

    def __init__(self, main, maps):
        import unicorn
        from unicorn import arm_const as reg
        if sha256(main) != MAIN_SHA:
            raise ValueError("unsupported firmware image; absolute addresses are hash-pinned")
        self.reg = reg
        self.uc = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
        self.uc.mem_map(0, 0x800000)
        self.scatter = []
        for offset in range(0x1B0, 0x280, 16):
            src, dst, length, handler = struct.unpack_from("<4I", main, offset)
            physical_dst = dst & ~0x40000000
            if physical_dst + length > 0x400000:
                raise ValueError("unexpected scatter destination")
            if handler == 0x100015C:
                start = src - 0x1000000
                payload = main[start:start+length]
                if start < 0 or len(payload) != length:
                    raise ValueError("invalid scatter source")
            elif handler == 0x1000184:
                payload = bytes(length)
            else:
                raise ValueError("unknown scatter handler")
            self.uc.mem_write(physical_dst, payload)
            self.scatter.append({"source": hex(src), "destination": hex(dst),
                                 "length": length, "operation": "copy" if handler == 0x100015C else "zero"})
        self.uc.reg_write(reg.UC_ARM_REG_C1_C0_2, 0xF << 20)
        self.uc.reg_write(reg.UC_ARM_REG_FPEXC, 0x40000000)
        for i, table in enumerate(maps):
            address = 0x400000 + i * 0x10000
            self.uc.mem_write(address, table)
            self.uc.mem_write(KNOTS + i * 12, struct.pack("<Iff", address, 20 + 10*i, 10.0))
        self.write32(STATE + 4, 0x460000)
        self.write32(0x155548 + 0x2C, 0x470000)
        self.write32(0x15523C + 0x2C, 0x530000)
        self.write32(0x14DB20 + 0x4C, 0)
        self.temperature = 20.5
        self.stub_counts = {}
        # Block hook restricts control flow without adding a Python callback per
        # instruction. Unmapped peripheral accesses fail; no device API exists.
        self.uc.hook_add(unicorn.UC_HOOK_BLOCK, self._block)

    def _block(self, uc, address, size, _):
        off = address + RELOCATION
        if off in (0x2A66C, 0x1C474, 0x4DDDC, 0x8C54C):
            self.stub_counts[hex(off)] = self.stub_counts.get(hex(off), 0) + 1
            if off == 0x2A66C:
                uc.reg_write(self.reg.UC_ARM_REG_S0, struct.unpack("<I", struct.pack("<f", self.temperature))[0])
            uc.reg_write(self.reg.UC_ARM_REG_R0, 0)
            uc.reg_write(self.reg.UC_ARM_REG_PC, uc.reg_read(self.reg.UC_ARM_REG_LR))
            return
        allowed = ((0x2A4A0, 0x2A5EC), (0x2A68C, 0x2AA54),
                   (0x2AAB0, 0x2ABA8), (0x31CEC, 0x31D70),
                   (0x36C94, 0x36CD4))
        if not any(lo <= off and off + size <= hi for lo, hi in allowed):
            raise RuntimeError(f"unexpected firmware execution at file offset {off:#x}, size {size}")

    def write32(self, address, value):
        self.uc.mem_write(address, struct.pack("<I", value))

    def call(self, file_offset, args=()):
        regs = (self.reg.UC_ARM_REG_R0, self.reg.UC_ARM_REG_R1,
                self.reg.UC_ARM_REG_R2, self.reg.UC_ARM_REG_R3)
        for register, value in zip(regs, args):
            self.uc.reg_write(register, value)
        self.uc.reg_write(self.reg.UC_ARM_REG_SP, 0x700000)
        self.uc.reg_write(self.reg.UC_ARM_REG_LR, STOP)
        self.uc.emu_start(file_offset-RELOCATION, STOP, timeout=10_000_000, count=5_000_000)
        if self.uc.reg_read(self.reg.UC_ARM_REG_PC) != STOP:
            raise RuntimeError("firmware routine did not return within limits")
        return self.uc.reg_read(self.reg.UC_ARM_REG_R0)

    def select(self, temperature):
        self.temperature = temperature
        if self.call(0x2A68C) != 0:
            raise RuntimeError("firmware map validator rejected supplied maps")
        pointer, _, interval, low, quantized, step = struct.unpack("<IIIfff", self.uc.mem_read(STATE, 24))
        return bytes(self.uc.mem_read(pointer, RECORD_BYTES)), {
            "interval_index": interval, "low_knot": low,
            "quantized_temperature": quantized, "step": step,
        }

    def pixels(self, table, colors):
        if not 1 <= len(colors) <= 4096:
            raise ValueError("pixel batch must contain 1..4096 pixels")
        self.uc.mem_write(0x470000, table)
        self.write32(STATE, 0x470000)
        for lane in range(3):
            self.uc.mem_write(0x500000+lane*0x10000, bytes(color[lane] for color in colors))
        self.call(0x2A780, (0x500000, 0x510000, 0x520000, len(colors)))
        planes = [self.uc.mem_read(0x500000+lane*0x10000, len(colors)) for lane in range(4)]
        return list(zip(*planes))

    def mdx_pairs(self):
        pairs = []
        for index in range(37):
            if self.call(0x36C94, (index, 0x540000, 0x540001)) != 0:
                raise RuntimeError("unexpected MDX lookup status")
            pair = list(self.uc.mem_read(0x540000, 2))
            raw = list(self.uc.mem_read(0x14E2F0 + index*8 + 6, 2))
            if pair != raw:
                raise AssertionError("MDX getter differs from initialized table")
            pairs.append(pair)
        return pairs


def verify(data):
    if sha256(data) != RBN_SHA:
        raise ValueError("requires the exact documented G1L1FS2105AR package")
    parts = partitions(data)
    main, _ = inflate_main(parts["FIRMWARE"][2])
    maps = [parts[f"LUT{i}_Z21"][2][:RECORD_BYTES] for i in range(1, 7)]
    arm = FirmwareArithmetic(main, maps)
    rng = random.Random(2105)
    grid = (0, 1, 15, 16, 17, 127, 128, 239, 240, 254, 255)
    colors = list(itertools.product(grid, repeat=3))
    colors += [tuple(rng.randrange(256) for _ in range(3)) for _ in range(512)]
    comparisons = 0
    for table in maps:
        actual = arm.pixels(table, colors)
        expected = [interpolate(table, color) for color in colors]
        if actual != expected:
            first = next(i for i, (a, b) in enumerate(zip(actual, expected)) if a != b)
            raise AssertionError(("pixel mismatch", colors[first], actual[first], expected[first]))
        comparisons += len(colors)
    temperatures = (0, 19.9, 20, 20.5, 20.51, 25, 30.49, 30.5, 30.51,
                    35, 40.5, 45, 50.5, 55, 60.5, 65, 70, 70.5, 80)
    cases = []
    for temperature in temperatures:
        table, state = arm.select(temperature)
        interval, weight, quantized = selection(temperature)
        expected = blend(maps[interval], maps[interval+1], weight)
        if table != expected or state != {
                "interval_index": interval, "low_knot": 20.0+interval*10,
                "quantized_temperature": quantized, "step": 10/256}:
            raise AssertionError(("selection/blend mismatch", temperature, state))
        actual = arm.pixels(table, list(COLORS.values()))
        if actual != [interpolate(expected, color) for color in COLORS.values()]:
            raise AssertionError("blended-map pixel mismatch")
        comparisons += len(actual)
        cases.append({"input_temperature": temperature, "weight_over_256": weight,
                      **state, "map_sha256": sha256(table),
                      "intermediate_rgb_and_mdx": dict(zip(COLORS, actual))})
    return {
        "firmware_sha256": RBN_SHA, "main_sha256": MAIN_SHA,
        "scope": "Unadjusted shipped LUTs; synthetic temperature state; no full boot/thermal pipeline or device access",
        "unicorn_version": __import__("unicorn").__version__,
        "scatter_entries": arm.scatter, "service_stub_counts": arm.stub_counts,
        "map_knots": [20, 30, 40, 50, 60, 70],
        "adjacent_unsigned_map_delta_range": [
            [min(b-a for a, b in zip(lower, upper)), max(b-a for a, b in zip(lower, upper))]
            for lower, upper in zip(maps, maps[1:])],
        "raw_maps_compared": 6, "pixels_per_raw_map": len(colors),
        "total_pixel_comparisons": comparisons, "pixel_mismatches": 0,
        "whole_blended_maps_compared": len(cases), "blend_byte_mismatches": 0,
        "selection_cases": cases, "mdx_duty_divider_pairs": arm.mdx_pairs(),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rbn", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.rbn.read_bytes()), indent=2))
