"""Exact and perceptual fingerprints for screenshot change detection."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

from PIL import Image


@dataclass(frozen=True)
class Fingerprint:
    sha256: str
    perceptual_hash: str


def fingerprint_image(path: Path) -> Fingerprint:
    data = path.read_bytes()
    with Image.open(path) as image:
        grayscale = image.convert("L").resize((16, 16))
        pixels = list(grayscale.getdata())
    average = sum(pixels) / len(pixels)
    perceptual_hash = "".join("1" if pixel >= average else "0" for pixel in pixels)
    return Fingerprint(hashlib.sha256(data).hexdigest(), perceptual_hash)


def hamming_distance(first: str, second: str) -> int:
    if len(first) != len(second):
        raise ValueError("perceptual hashes must have equal length")
    return sum(left != right for left, right in zip(first, second))


def deduplicate_with_matches(
    images: list[Path],
    threshold: int = 4,
    against: list[Path] | None = None,
) -> tuple[list[Path], dict[Path, Path]]:
    """Keep one image per visually distinct screen.

    `against` holds images from earlier runs (typically the ones already analysed). Comparing
    candidates against them is what stops an unchanged screen costing another vision call: without
    it each run only sees its own candidates and re-analyses the same screen every time.
    """
    selected: list[Path] = []
    fingerprints: list[Fingerprint] = []
    matches: dict[Path, Path] = {}

    earlier: list[tuple[Path, Fingerprint]] = [(path, fingerprint_image(path)) for path in (against or [])]

    for image in images:
        current = fingerprint_image(image)
        matched_previous = next(
            (
                path
                for path, previous in earlier
                if current.sha256 == previous.sha256
                or hamming_distance(current.perceptual_hash, previous.perceptual_hash) <= threshold
            ),
            None,
        )
        if matched_previous is not None:
            matches[image] = matched_previous
            continue
        matched_index = next(
            (
                index
                for index, previous in enumerate(fingerprints)
                if current.sha256 == previous.sha256
                or hamming_distance(current.perceptual_hash, previous.perceptual_hash) <= threshold
            ),
            None,
        )
        if matched_index is not None:
            matches[image] = selected[matched_index]
            continue
        selected.append(image)
        fingerprints.append(current)
        earlier.append((image, current))
    return selected, matches


def deduplicate_images(images: list[Path], threshold: int = 4) -> list[Path]:
    return deduplicate_with_matches(images, threshold)[0]
