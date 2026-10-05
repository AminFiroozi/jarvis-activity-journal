import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from src.analysis.screenshot_fingerprint import deduplicate_images, deduplicate_with_matches, fingerprint_image, hamming_distance


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

    def test_deduplication_reports_which_kept_image_each_duplicate_matched(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "one.jpg"
            duplicate = Path(directory) / "two.jpg"
            different = Path(directory) / "three.jpg"
            Image.new("RGB", (100, 100), "black").save(first)
            Image.new("RGB", (100, 100), "black").save(duplicate)
            image = Image.new("RGB", (100, 100), "black")
            ImageDraw.Draw(image).rectangle((0, 0, 50, 50), fill="white")
            image.save(different)

            kept, matches = deduplicate_with_matches([first, duplicate, different], threshold=4)

            self.assertEqual(kept, [first, different])
            self.assertEqual(matches, {duplicate: first})


class CrossRunDedupeTests(unittest.TestCase):
    """Screens are captured every minute but analysed in later runs, so a run must compare its
    candidates against what was already analysed -- otherwise an unchanged screen costs a vision
    call every single run and the queue can never drain."""

    def _image(self, directory: Path, name: str, text: str) -> Path:
        path = Path(directory) / name
        image = Image.new("RGB", (64, 64), color="white")
        ImageDraw.Draw(image).text((5, 5), text, fill="black")
        image.save(path, "PNG")
        return path

    def test_candidate_matching_an_already_analysed_image_is_deduplicated_against_it(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = self._image(directory, "previous.png", "same")
            candidate = self._image(directory, "candidate.png", "same")

            kept, matches = deduplicate_with_matches([candidate], threshold=4, against=[previous])

            self.assertEqual(kept, [])
            self.assertEqual(matches[candidate], previous)

    def test_meaningful_change_against_previous_is_still_analysed(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = self._image(directory, "previous.png", "a")
            candidate = self._image(directory, "candidate.png", "completely different content here")

            kept, matches = deduplicate_with_matches([candidate], threshold=0, against=[previous])

            self.assertEqual(kept, [candidate])
            self.assertEqual(matches, {})

    def test_candidates_are_still_deduplicated_among_themselves(self):
        with tempfile.TemporaryDirectory() as directory:
            first = self._image(directory, "first.png", "same")
            second = self._image(directory, "second.png", "same")

            kept, matches = deduplicate_with_matches([first, second], threshold=4)

            self.assertEqual(kept, [first])
            self.assertEqual(matches[second], first)


if __name__ == "__main__":
    unittest.main()
