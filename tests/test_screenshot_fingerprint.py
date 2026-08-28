import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from src.analysis.screenshot_fingerprint import deduplicate_images, fingerprint_image, hamming_distance


class ScreenshotFingerprintTests(unittest.TestCase):
    def test_identical_images_have_zero_distance(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "one.jpg"
            Image.new("RGB", (100, 100), "black").save(path)

            first = fingerprint_image(path)
            second = fingerprint_image(path)

            self.assertEqual(first.sha256, second.sha256)
            self.assertEqual(hamming_distance(first.perceptual_hash, second.perceptual_hash), 0)

    def test_deduplication_keeps_meaningful_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "one.jpg"
            second = Path(directory) / "two.jpg"
            Image.new("RGB", (100, 100), "black").save(first)
            image = Image.new("RGB", (100, 100), "black")
            ImageDraw.Draw(image).rectangle((0, 0, 50, 50), fill="white")
            image.save(second)

            selected = deduplicate_images([first, second], threshold=4)

            self.assertEqual(selected, [first, second])


if __name__ == "__main__":
    unittest.main()
