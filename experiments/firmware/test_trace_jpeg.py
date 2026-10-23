"""Fail-closed fixture boundaries; no vendor binary or Unicorn required."""

import unittest

from trace_jpeg import MAX_INPUT, JpegHeaders


class JpegBoundaryTests(unittest.TestCase):
    def test_unknown_firmware_rejected(self):
        with self.assertRaisesRegex(ValueError, "exact documented"):
            JpegHeaders(b"not firmware")

    def test_short_input_rejected_before_execution(self):
        decoder = JpegHeaders.__new__(JpegHeaders)
        with self.assertRaises(ValueError):
            decoder.parse(b"\xff")

    def test_large_input_rejected_before_execution(self):
        decoder = JpegHeaders.__new__(JpegHeaders)
        with self.assertRaises(ValueError):
            decoder.parse(bytes(MAX_INPUT + 1))
