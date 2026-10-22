"""Synthetic geometry/encoding contract tests; no captures or device needed."""

import io
import unittest

from PIL import Image, JpegImagePlugin
from prepare import editor_transform, jpeg_bytes, prepare


class PreparationTests(unittest.TestCase):
    def test_target_identity(self):
        image = Image.new("RGB", (768, 1152), (21, 78, 163))
        self.assertEqual(prepare(image).tobytes(), image.tobytes())

    def test_small_image_scales_without_border(self):
        result = prepare(Image.new("RGB", (96, 144), "red"))
        self.assertEqual(result.size, (768, 1152))
        self.assertEqual(result.getextrema(), ((255, 255), (0, 0), (0, 0)))

    def test_center_crop_removes_sides(self):
        source = Image.new("RGB", (300, 150), "blue")
        source.paste("red", (100, 0, 200, 150))
        result = prepare(source)
        self.assertEqual(result.getpixel((384, 576)), (255, 0, 0))
        self.assertEqual(result.getpixel((10, 576)), (255, 0, 0))

    def test_half_scale_has_white_border(self):
        result = editor_transform(
            Image.new("RGB", (100, 150), "red"), [0.5, 0, 25, 0, 0.5, 37.5, 0, 0, 1]
        )
        self.assertEqual(result.getpixel((50, 75)), (255, 0, 0))
        self.assertEqual(result.getpixel((10, 75)), (255, 255, 255))
        self.assertEqual(result.getpixel((50, 10)), (255, 255, 255))

    def test_rotation_direction_and_fixed_canvas(self):
        image = Image.new("RGB", (100, 100), "blue")
        image.paste("red", (0, 0, 50, 50))
        result = editor_transform(image, [0, -1, 100, 1, 0, 0, 0, 0, 1])
        self.assertEqual(result.getpixel((75, 25)), (255, 0, 0))
        self.assertEqual(result.getpixel((25, 25)), (0, 0, 255))

    def test_reject_invalid_matrix(self):
        for matrix in ([0] * 9, [1, 0, 0, 0, 0, 0, 0, 0, 1]):
            with self.assertRaises(ValueError):
                editor_transform(Image.new("RGB", (2, 2)), matrix)

    def test_transparency_composites_white(self):
        result = prepare(Image.new("RGBA", (2, 3), (0, 0, 0, 0)))
        self.assertEqual(result.getpixel((0, 0)), (255, 255, 255))

    def test_jpeg_contract(self):
        result = Image.open(io.BytesIO(jpeg_bytes(prepare(Image.new("RGB", (2, 3))))))
        self.assertEqual(result.size, (768, 1152))
        self.assertEqual(JpegImagePlugin.get_sampling(result), 2)
        self.assertFalse(result.info.get("progressive"))
        self.assertFalse(result.getexif())
        self.assertNotIn("icc_profile", result.info)
        self.assertEqual(result.quantization[0][:8], [3, 2, 2, 3, 5, 8, 10, 12])


if __name__ == "__main__":
    unittest.main()
