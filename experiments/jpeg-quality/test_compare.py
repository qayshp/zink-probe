"""Synthetic host-codec checks; no firmware or printer access."""

import io
import unittest

import numpy as np
from compare import encode, mutate_header, sof_offset
from PIL import Image


class JpegVariantTests(unittest.TestCase):
    def test_huffman_optimization_preserves_pixels(self):
        pixels = np.random.default_rng(2105).integers(
            0, 256, (32, 32, 3), dtype=np.uint8
        )
        image = Image.fromarray(pixels)
        plain = encode(image, 95, 0, optimize=False)
        optimized = encode(image, 95, 0, optimize=True)
        self.assertNotEqual(plain, optimized)
        self.assertEqual(
            Image.open(io.BytesIO(plain)).tobytes(),
            Image.open(io.BytesIO(optimized)).tobytes(),
        )

    def test_sampling_matters_even_at_quality_100(self):
        pixels = np.full((32, 32, 3), 255, dtype=np.uint8)
        pixels[:, ::2, 0] = 0
        image = Image.fromarray(pixels)
        errors = []
        for sampling in (2, 0):
            decoded = np.asarray(
                Image.open(io.BytesIO(encode(image, 100, sampling))), dtype=int
            )
            errors.append(np.abs(decoded - pixels).mean())
        self.assertGreater(errors[0], 20)
        self.assertLess(errors[1], 1)

    def test_marker_walk_skips_payload_not_marker_like_bytes(self):
        payload = b"\xff\xd8\xff\xe0\x00\x06\xff\xc0xx\xff\xc0\x00\x02"
        self.assertEqual(sof_offset(payload), 10)
        changed = mutate_header(payload, 1, 0xC1)
        self.assertEqual(changed[11], 0xC1)
        self.assertEqual(changed[7], 0xC0)

    def test_invalid_header_bounds(self):
        for payload in (
            b"PNG",
            b"\xff\xd8\xff\xe0\x00\x01",
            b"\xff\xd8\xff\xe0\xff\xff",
            b"\xff\xd8\xff\xda\x00\x02",
        ):
            with self.assertRaises(ValueError):
                sof_offset(payload)
