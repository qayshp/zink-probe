"""Synthetic checks; vendor resources and Unicorn are not required."""

import unittest

from trace_thermal import (
    fast_history,
    generated_pattern,
    pack_phases,
    spatial_row,
    thermal_pixel,
    verify,
)


class ThermalReferenceTests(unittest.TestCase):
    def test_heat_history_reduces_requested_drive(self):
        coefficients = (100, 4096, 2048, 1024)
        self.assertEqual(thermal_pixel(coefficients, 0, 0, 0, 0, 0, 1000), 400)
        self.assertEqual(thermal_pixel(coefficients, 20, 10, 10, 40, 40, 1000), 330)

    def test_thermal_saturation_and_signed_wrap(self):
        self.assertEqual(thermal_pixel((100, 0, 0, 0), 0, 0, 0, 0, 0, 99), 99)
        self.assertEqual(thermal_pixel((0, 4096, 0, 0), 1, 0, 0, 0, 0, 100), 0)
        # uint32 subtraction wraps before the signed shift, not an unbounded int.
        self.assertEqual(thermal_pixel((0, 65535, 0, 0), 65536, 0, 0, 0, 0, 100), 16)

    def test_neighbor_correction_and_boundary(self):
        self.assertEqual(spatial_row([100, 100, 100], 4096, 1000), [200, 100, 200])
        self.assertEqual(spatial_row([100], 4096, 1000, right_guard=50), [250])
        self.assertEqual(spatial_row([0, 100, 0], 4096, 200), [0, 200, 0])

    def test_history_decay_then_diffusion(self):
        # Half of the old heat survives; half of new drive is added.
        self.assertEqual(fast_history([100, 200, 300], [100, 100, 100], 0,
                                      32768, 32768, 0), [100, 150, 200])
        # Diffusion uses the old neighbors within that pass, including negatives.
        self.assertEqual(fast_history([0, 0, 0], [0, 200, 0], 0,
                                      32768, 0, 16384), [25, 50, 25])

    def test_history_guards_do_not_receive_drive(self):
        self.assertEqual(fast_history([100]*4, [200, 200], 1,
                                      32768, 32768, 0), [50, 150, 150, 50])

    def test_pattern_is_inverse_occupancy(self):
        mask, repeat, numerator, denominator = generated_pattern(7)
        self.assertEqual((mask, repeat, numerator, denominator), (0x08102040, 28, 7, 1))
        self.assertEqual(mask.bit_count()*numerator, repeat*denominator)
        self.assertEqual(generated_pattern(33), generated_pattern(31))
        with self.assertRaises(ValueError):
            generated_pattern(0)

    def test_phase_word_layout_and_off_fill(self):
        self.assertEqual(pack_phases([(38, 100), (18, 70)], 1024),
                         [0x00260064, 0x00120046, 0x00250356])
        self.assertEqual(pack_phases([(38, 4095)], 4095), [0x00260FFF])
        self.assertEqual(pack_phases([], 1024), [0x00250400])

    def test_invalid_phase_fixtures(self):
        for phases, budget in (([(38, 1025)], 1024), ([(48, 1)], 20),
                               ([(37, 0)], 20), ([], 4096)):
            with self.assertRaises(ValueError):
                pack_phases(phases, budget)

    def test_unknown_firmware_rejected_before_execution(self):
        with self.assertRaisesRegex(ValueError, "exact documented"):
            verify(b"not firmware")


if __name__ == "__main__":
    unittest.main()
