"""Boundary tests use synthetic containers; no vendor files or device needed."""

import gzip
import struct
import unittest
from unittest.mock import patch

from inspect_rbn import DIRECTORY, ROM_BASE, inflate_main, partitions


def container():
    data = bytearray(DIRECTORY + 512)
    data[DIRECTORY:DIRECTORY + 4] = b"OART"
    struct.pack_into("<I", data, DIRECTORY + 12, 2)
    struct.pack_into("<I", data, DIRECTORY + 24, 0)
    names = b"STRTAB\0FIRMWARE\0"
    struct.pack_into("<III", data, DIRECTORY + 40, ROM_BASE + DIRECTORY + 64, len(names), 0)
    struct.pack_into("<III", data, DIRECTORY + 52, ROM_BASE + DIRECTORY + 128, 3, 1)
    data[DIRECTORY + 64:DIRECTORY + 64 + len(names)] = names
    data[DIRECTORY + 128:DIRECTORY + 131] = b"abc"
    return data


class Boundaries(unittest.TestCase):
    def test_named_payload(self):
        self.assertEqual(partitions(container())["FIRMWARE"][2], b"abc")

    def test_bad_header_and_truncation(self):
        for data in [b"", bytearray(DIRECTORY + 40)]:
            with self.assertRaises(ValueError):
                partitions(data)

    def test_out_of_bounds_entry(self):
        data = container()
        struct.pack_into("<I", data, DIRECTORY + 52, ROM_BASE + len(data) + 1)
        with self.assertRaises(ValueError):
            partitions(data)

    def test_bad_count(self):
        data = container()
        struct.pack_into("<I", data, DIRECTORY + 12, 0xFFFFFFFF)
        with self.assertRaises(ValueError):
            partitions(data)

    def test_gzip_and_suffix(self):
        self.assertEqual(inflate_main(gzip.compress(b"firmware") + b"tail"), (b"firmware", 4))

    def test_truncated_gzip(self):
        with self.assertRaises(ValueError):
            inflate_main(gzip.compress(b"firmware")[:-4])

    def test_decompression_bound(self):
        with patch("inspect_rbn.MAX_MAIN", 32):
            with self.assertRaises(ValueError):
                inflate_main(gzip.compress(b"x" * 33))


if __name__ == "__main__":
    unittest.main()
