#!/usr/bin/env python3
"""Offline ARM/Python comparison of selected FS2105 tone/thermal arithmetic.

Reads one hash-pinned local package; no downloads, printer APIs, or MMIO mapping.
This is a neutral-calibration fixture, not a whole-firmware or physical model.
Requires Unicorn 2.1.4 only for verify(); synthetic reference tests do not.
"""

import argparse
import json
import random
import struct
from pathlib import Path

from inspect_rbn import inflate_main, partitions, sha256
from trace_lut import MAIN_SHA, RBN_SHA, RELOCATION, FirmwareArithmetic
from trace_lut import f32 as f


def signed32(value):
    return (value + 2**31) % 2**32 - 2**31


def clamp(value, limit):
    return min(limit, max(0, value))


def neutral_gamma(mmt, tone, thermal, channel):
    """256 four-coefficient records; preserves the firmware's float32 rounding.

    Calibration fetch is replaced by [1,0,0,0,0,0,0] for each Y/M/C channel.
    Other calibration fields are zero. Non-neutral calibration is not modeled.
    """
    mm = struct.unpack("<4096f", mmt)
    tones = struct.unpack("<768f", tone[:3072])
    rows = [[mm[channel*1024 + k*256 + 255-i] for k in range(4)]
            for i in range(256)]
    center = rows[128][0]
    for row in rows:
        row[0] = f(center + f(row[0] - center))
    a, b, d = struct.unpack_from("<3f", thermal, channel*88 + 0xC)
    scale = struct.unpack_from("<f", thermal, 0x110)[0]
    result = []
    for i in range(256):
        x = f((tones[i*3 + 2-channel] - .05) * f(255/2.45))
        if x < 0:
            j, fraction = 0, 0.
            energy = f(rows[0][0] + f(f(rows[1][0]-rows[0][0])*x))
        elif x > 255:
            j, fraction = 255, 0.
            energy = f(rows[255][0] + f(f(rows[255][0]-rows[254][0])*f(x-255)))
        else:
            j, fraction = int(x), f(x-int(x))
            energy = f(rows[j][0] + f(f(rows[min(j+1, 255)][0]-rows[j][0])*fraction))
        values = [energy] + [f(rows[j][k] + f(
            f(rows[min(j+1, 255)][k]-rows[j][k])*fraction)) for k in range(1, 4)]
        t = min(values[1], 0.)
        s = f(t/f(1+f(a*t)))
        gain = f(1-f(a*s))
        energy = f(gain*values[0])
        result.append((
            min(65535, int(f(f(64/scale)*max(energy, 0.))+.5)),
            min(65535, int(f(f(-4096/scale)*s)+.5)),
            clamp(int(f(f(f(values[2]-f(b*t))*-4096)*gain)+.5), 65535),
            clamp(int(f(f(f(values[3]-f(d*t))*-4096)*gain)+.5), 65535),
        ))
    return result


def thermal_pixel(coefficients, head_delta, history0, history1, previous, old, limit):
    a0, a1, a2, a3 = coefficients
    value = signed32((a0 << 14) - (head_delta+history0+history1)*a1
                     - previous*a2 - old*a3) >> 12
    return clamp(value, limit)


def spatial_row(raw, coefficient, limit, right_guard=0):
    return [clamp(signed32(value + (signed32(coefficient*(
        2*value-(raw[i-1] if i else 0)-
        (raw[i+1] if i+1 < len(raw) else right_guard))) >> 12)), limit)
        for i, value in enumerate(raw)]


def fast_history(old, output, prefix, drive, decay, spread):
    """Fast state update then lateral diffusion; guards receive only decay."""
    updated = [((decay*h + (drive*output[i-prefix]
                if prefix <= i < prefix+len(output) else 0)) & 0xFFFFFFFF) >> 16
               for i, h in enumerate(old)]
    return [(h + (((spread*((updated[i-1] if i else 0) +
             (updated[i+1] if i+1 < len(updated) else 0)-2*h)) & 0xFFFFFFFF) >> 16))
            & 0xFFFF for i, h in enumerate(updated)]


def pack_phases(phases, budget):
    """Valid caller domain; returns words before placement into the ring."""
    if not 0 < budget <= 4095 or not 0 <= len(phases) <= 5:
        raise ValueError("invalid phase budget/count")
    if any(not 0 <= pattern < 48 or not 0 < duration <= 4095
           for pattern, duration in phases) or sum(n for _, n in phases) > budget:
        raise ValueError("invalid phase or overcommitted budget")
    words = [(pattern << 16) | duration for pattern, duration in phases]
    remaining = budget-sum(n for _, n in phases)
    if remaining:
        words.append((37 << 16) | remaining)
    return words


def generated_pattern(duty):
    if not isinstance(duty, int) or duty < 1:
        raise ValueError("positive integer duty required")
    duty = min(duty, 31)
    return (sum(1 << bit for bit in range(duty-1, 32, duty)),
            (32//duty)*duty, duty, 1)


class ThermalArithmetic(FirmwareArithmetic):
    def __init__(self, main, maps):
        self.heap = 0x600000
        self.thermal_stub_counts = {}
        super().__init__(main, maps)

    def _block(self, uc, address, size, data):
        off, reg = address+RELOCATION, self.reg
        if off in (0x7F10C0, 0x7F11C0, 0x299F8, 0x37674, 0x39D00):
            self.thermal_stub_counts[hex(off)] = self.thermal_stub_counts.get(hex(off), 0)+1
            value = 0
            if off == 0x7F10C0:
                length = uc.reg_read(reg.UC_ARM_REG_R1)
                if not 0 < length < 0x10000 or self.heap+length >= 0x680000:
                    raise ValueError("unexpected allocation")
                value = self.heap
                self.heap += (length+63) & ~63
            elif off == 0x299F8:
                buf = bytearray(0xB0)
                for channel in range(3):
                    struct.pack_into("<f", buf, channel*28, 1.)
                uc.mem_write(uc.reg_read(reg.UC_ARM_REG_R2), bytes(buf))
            elif off == 0x39D00:
                quotient, remainder = divmod(uc.reg_read(reg.UC_ARM_REG_R0),
                                             uc.reg_read(reg.UC_ARM_REG_R1))
                value = quotient
                uc.reg_write(reg.UC_ARM_REG_R1, remainder)
            uc.reg_write(reg.UC_ARM_REG_R0, value)
            uc.reg_write(reg.UC_ARM_REG_PC, uc.reg_read(reg.UC_ARM_REG_LR))
            return
        allowed = ((0x2C2D8, 0x2C4A4), (0x2C564, 0x2D064),
                   (0x44AA8, 0x44D38), (0x4590C, 0x4599C),
                   (0x37440, 0x375AC), (0x36730, 0x36924),
                   (0x369EC, 0x369F4), (0x36D28, 0x36DC0), (0x37158, 0x37308))
        if any(lo <= off and off+size <= hi for lo, hi in allowed):
            return
        super()._block(uc, address, size, data)

    def gamma(self, parts):
        for name, address, obj in (("MMT", 0x480000, 0x155278),
                                   ("TONESCALE", 0x4A0000, 0x1552F0),
                                   ("ZINK_THC", 0x490000, None)):
            payload = parts[name][2]
            self.uc.mem_write(address, payload)
            if obj:
                self.write32(obj+0x2C, address)
                self.write32(obj+0x30, len(payload))
        self.write32(0x14DB20+0x68, 0x490000)
        self.write32(0x155368+0x2C, 0x4B0000)
        self.uc.mem_write(0x4C0000, struct.pack("<3I", 0x7F1000, 0x7F1100, 0))
        self.call(0x2C564, (0x4C0000,))
        return [list(struct.iter_unpack("<4H", self.uc.mem_read(0x4B0000+c*2048, 2048)))
                for c in range(3)]

    def thermal_slice(self, channel, values, gamma, histories, head, offset, limit, k, guard):
        """Execute the pixel and spatial loops, excluding history recurrence."""
        width = len(values)
        if not 1 <= width <= 4096:
            raise ValueError("invalid synthetic row width")
        state, params = 0x2A0810, 0x2A0780+channel*48
        self.write32(0x14E48C+4, channel)
        self.uc.mem_write(0x14DB98+channel*2, struct.pack("<H", head))
        self.write32(params, limit)
        self.write32(params+0x28, k)
        self.write32(params+0x2C, offset)
        for off, address, row in zip((4, 0x10, 0x34, 0x38),
                                    (0x550000, 0x560000, 0x570000, 0x580000), histories):
            self.write32(state+off, address)
            self.uc.mem_write(address, struct.pack(f"<{width+1}H", *row, guard))
        self.uc.mem_write(state+0x48, struct.pack("<H", width))
        self.uc.mem_write(state+0x5A, b"\0\0")
        self.write32(state+0x3C+channel*4, 0x590000)
        self.uc.mem_write(0x500000, bytes(values))
        self.uc.mem_write(0x510000, b"".join(struct.pack("<4H", *row) for row in gamma))
        reg = self.reg
        self.uc.reg_write(reg.UC_ARM_REG_SP, 0x700000)
        self.uc.reg_write(reg.UC_ARM_REG_R4, 0x500000)
        self.uc.reg_write(reg.UC_ARM_REG_R5, 0)
        self.write32(0x700000+0x40, 0x510000)
        stop = 0x375AC-RELOCATION
        self.uc.emu_start(0x37440-RELOCATION, stop, timeout=10_000_000, count=1_000_000)
        if self.uc.reg_read(reg.UC_ARM_REG_PC) != stop:
            raise RuntimeError("thermal slice did not reach its boundary")
        return tuple(list(struct.unpack(f"<{width}H", self.uc.mem_read(addr, width*2)))
                     for addr in (0x580000, 0x590000))

    def fast_history(self, channel, old, output, prefix, coefficients):
        state, params = 0x2A0810, 0x2A0780+channel*48
        self.write32(0x14E48C+4, channel)
        for off, value in zip((4, 0x10, 0x1C), coefficients):
            self.write32(params+off, value)
        self.write32(state+0x10, 0x550000)
        self.write32(state+0x3C+channel*4, 0x590000)
        for off, value in ((0x5A, prefix), (0x4E, len(output)), (0x54, len(old))):
            self.uc.mem_write(state+off, struct.pack("<H", value))
        self.uc.mem_write(0x550000, struct.pack(f"<{len(old)}H", *old))
        self.uc.mem_write(0x590000, struct.pack(f"<{len(output)}H", *output))
        self.call(0x37158, (0, channel))
        return list(struct.unpack(f"<{len(old)}H", self.uc.mem_read(0x550000, len(old)*2)))

    def phase_queue(self, phases, budget, start):
        # Two heater positions avoid the final-heater RTOS notification branch.
        ctx, queue, pairs = 0x4D0000, 0x4E0000, 0x4F0000
        self.uc.mem_write(ctx, bytes(0x200))
        self.uc.mem_write(queue, bytes(272))
        self.write32(ctx+0x18, 2)
        self.write32(ctx+0x1C, queue)
        self.write32(queue, start)
        self.write32(queue+4, start)
        self.uc.mem_write(0x14DB22, struct.pack("<H", budget))
        if phases:
            self.uc.mem_write(pairs, b"".join(struct.pack("<II", *p) for p in phases))
        if self.call(0x36730, (ctx, len(phases), pairs)):
            raise AssertionError("unexpected queue error")
        end = struct.unpack("<I", self.uc.mem_read(queue, 4))[0]
        words = [struct.unpack("<I", self.uc.mem_read(queue+12+4*(i % 31), 4))[0]
                 for i in range(start, end)]
        if struct.unpack("<I", self.uc.mem_read(ctx+0x20, 4))[0] != 1:
            raise AssertionError("heater position did not advance")
        return words


def verify(data):
    if sha256(data) != RBN_SHA:
        raise ValueError("requires the exact documented G1L1FS2105AR package")
    parts = partitions(data)
    main, _ = inflate_main(parts["FIRMWARE"][2])
    arm = ThermalArithmetic(main, [parts[f"LUT{i}_Z21"][2][:19652] for i in range(1, 7)])
    gamma = arm.gamma(parts)
    channel_params = [struct.unpack("<12I", arm.uc.mem_read(0x2A0780+c*48, 48))
                      for c in range(3)]
    expected = [neutral_gamma(parts["MMT"][2], parts["TONESCALE"][2],
                              parts["ZINK_THC"][2], c) for c in range(3)]
    if gamma != expected:
        raise AssertionError("neutral gamma coefficient mismatch")
    rng, rows, pixels = random.Random(2105), 0, 0
    limits = tuple(v << 8 for v in struct.unpack("<3I", arm.uc.mem_read(0x1088B8, 12)))
    ks = tuple(p[10] for p in channel_params)
    # Both resource-derived coefficients and full-uint16 stress fixtures.
    for c in range(3):
        for stress in (False, True):
            table = ([tuple(rng.randrange(65536) for _ in range(4)) for _ in range(256)]
                     if stress else gamma[c])
            for width in (1, 2, 3, 31, 768):
                values = [rng.randrange(256) for _ in range(width)]
                histories = [[rng.randrange(65536 if stress else 4096) for _ in values]
                             for _ in range(4)]
                head, offset, guard = rng.randrange(65536), 10240, rng.randrange(65536)
                actual = arm.thermal_slice(c, values, table, histories, head, offset,
                                           limits[c], ks[c], guard)
                raw = [thermal_pixel(table[v], head-offset, *(h[i] for h in histories), limits[c])
                       for i, v in enumerate(values)]
                out = spatial_row(raw, ks[c], limits[c], guard)
                if actual != (raw, out):
                    raise AssertionError(("thermal loop mismatch", c, stress, width))
                rows += 1
                pixels += width
    history_cases, history_values = 0, 0
    for c in range(3):
        for stress in (False, True):
            coefficients = (tuple(rng.randrange(65536) for _ in range(3)) if stress
                            else tuple(channel_params[c][i] for i in (1, 4, 7)))
            for width in (2, 31, 768):
                for prefix, suffix in ((0, 0), (2, 3)):
                    old = [rng.randrange(65536) for _ in range(width+prefix+suffix)]
                    output = [rng.randrange(65536) for _ in range(width)]
                    expected_history = fast_history(old, output, prefix, *coefficients)
                    if arm.fast_history(c, old, output, prefix, coefficients) != expected_history:
                        raise AssertionError(("fast history mismatch", c, stress, width, prefix))
                    history_cases += 1
                    history_values += len(old)
    cases = [([], 1024, 0), ([(38, 100), (18, 70), (37, 20), (40, 120)], 1024, 30),
             ([(38, 4095)], 4095, 62)]
    for _ in range(100):
        budget = rng.randrange(1, 4096)
        remaining, phases = budget, []
        for _ in range(rng.randrange(6)):
            if not remaining:
                break
            duration = rng.randrange(1, remaining+1)
            phases.append((rng.randrange(48), duration))
            remaining -= duration
        cases.append((phases, budget, rng.randrange(1000)))
    for phases, budget, start in cases:
        if arm.phase_queue(phases, budget, start) != pack_phases(phases, budget):
            raise AssertionError("phase queue mismatch")
    mdx = list(struct.iter_unpack("<IHBB", arm.uc.mem_read(0x14E2F0, 37*8)))
    for mask, repeat, numerator, denominator in mdx:
        if mask >> repeat or mask.bit_count()*numerator != repeat*denominator:
            raise AssertionError("MDX on-fraction relation failed")
    for duty in range(1, 34):
        arm.call(0x36D28, (duty, 47))
        actual = struct.unpack("<IHBB", arm.uc.mem_read(0x14E2F0+47*8, 8))
        if actual != generated_pattern(duty):
            raise AssertionError("generated duty-pattern mismatch")
    return {
        "firmware_sha256": RBN_SHA, "main_sha256": MAIN_SHA,
        "scope": "Neutral media calibration; selected ARM arithmetic and fast history update only; no complete multiscale history, full phase planner, hardware execution or printer access",
        "unicorn_version": __import__("unicorn").__version__,
        "stub_meanings": {"0x299f8": "neutral media calibration fetch",
                          "0x37674": "skip thermal-history buffer initialization",
                          "0x7f10c0": "synthetic allocator", "0x7f11c0": "synthetic free",
                          "0x39d00": "unsigned division quotient/remainder",
                          "0x8c54c": "log sink"},
        "stub_counts": arm.thermal_stub_counts | arm.stub_counts,
        "gamma_coefficients_compared": 3072, "gamma_mismatches": 0,
        "gamma_samples": {name: {str(i): gamma[c][i] for i in (0, 128, 255)}
                          for c, name in enumerate(("Y", "M", "C"))},
        "thermal_rows_compared": rows, "thermal_pixels_compared": pixels,
        "thermal_raw_and_spatial_mismatches": 0,
        "thermal_fixture_limits": limits, "thermal_fixture_neighbor_coefficients": ks,
        "fast_history_cases_compared": history_cases, "fast_history_values_compared": history_values,
        "fast_history_mismatches": 0,
        "nominal_fast_history_coefficients": {
            name: {"drive": channel_params[c][1], "decay": channel_params[c][4],
                   "spread": channel_params[c][7]}
            for c, name in enumerate(("Y", "M", "C"))},
        "phase_queue_cases_compared": len(cases), "phase_queue_mismatches": 0,
        "example_phase_words": [f"0x{v:08x}" for v in pack_phases(cases[1][0], 1024)],
        "fixed_mdx_patterns_checked": len(mdx),
        "generated_pattern_cases_compared": 33, "generated_pattern_mismatches": 0,
        "resource_fallback_M_interval": parts["ZINK_THC"][2][0x120],
        "resource_C_intervals": [parts["ZINK_THC"][2][0x121]-i for i in range(7)],
        "mdx_examples": {str(i): {"mask": f"0x{mdx[i][0]:08x}", "repeat": mdx[i][1],
                                  "numerator": mdx[i][2], "divider": mdx[i][3],
                                  "on_bits": mdx[i][0].bit_count()}
                         for i in (0, 17, 18, 36)},
        "configured_miniT_microseconds": struct.unpack_from("<f", main, 0x32194)[0],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rbn", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.rbn.read_bytes()), indent=2))
