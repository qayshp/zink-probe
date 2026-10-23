"""Synthetic checks of the independent math and fail-closed package boundary."""

import itertools
import unittest

from trace_lut import RECORD_BYTES, blend, interpolate, selection, verify


class LutReferenceTests(unittest.TestCase):
    def test_axis_order_and_last_cell(self):
        table = bytes(v for r, g, b in itertools.product(range(17), repeat=3)
                      for v in (r*15, g*15, b*15, r+g+b))
        self.assertEqual(interpolate(table, (16, 32, 48)), (15, 30, 45, 6))
        # The final node represents 256; input 255 remains inside the last cell.
        self.assertEqual(interpolate(table, (255, 255, 255)), (239, 239, 239, 47))

    def test_constant_map(self):
        table = bytes((31, 79, 222, 18)) * 4913
        self.assertEqual(interpolate(table, (127, 15, 239)), (31, 79, 222, 18))

    def test_half_degree_selection_and_clamps(self):
        self.assertEqual(selection(0), (0, 0, 20.0))
        self.assertEqual(selection(20.5), (0, 0, 20.0))
        self.assertEqual(selection(30.5), (1, 0, 30.0))
        self.assertEqual(selection(35), (1, 115, 34.4921875))
        self.assertEqual(selection(80), (4, 256, 70.0))
        with self.assertRaises(ValueError):
            selection(float("nan"))

    def test_signed_delta_and_fourth_lane_rounding(self):
        base = bytes((10, 10, 10, 10)) * 4913
        following = bytes((13, 7, 10, 7)) * 4913
        self.assertEqual(blend(base, following, 128)[:4], bytes((11, 9, 10, 9)))
        # Bias is added before division toward zero, also for negative deltas.
        self.assertEqual(blend(base, following, 256)[:4], bytes((13, 7, 10, 8)))

    def test_signed_byte_wrap(self):
        base = bytes(RECORD_BYTES)
        following = bytes((200, 0, 0, 0)) * 4913
        self.assertEqual(blend(base, following, 128)[:4], bytes((228, 0, 0, 0)))

    def test_invalid_table_and_input(self):
        with self.assertRaises(ValueError):
            interpolate(b"", (0, 0, 0))
        with self.assertRaises(ValueError):
            interpolate(bytes(RECORD_BYTES), (256, 0, 0))
        with self.assertRaises(ValueError):
            blend(bytes(RECORD_BYTES), bytes(RECORD_BYTES), 257)

    def test_unknown_firmware_rejected_before_execution(self):
        with self.assertRaisesRegex(ValueError, "exact documented"):
            verify(b"not firmware")


if __name__ == "__main__":
    unittest.main()
