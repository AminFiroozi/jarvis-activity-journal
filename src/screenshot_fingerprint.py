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


def deduplicate_images(images: list[Path], threshold: int = 4) -> list[Path]:
    selected: list[Path] = []
    fingerprints: list[Fingerprint] = []
    for image in images:
        current = fingerprint_image(image)
        if any(
            current.sha256 == previous.sha256
            or hamming_distance(current.perceptual_hash, previous.perceptual_hash) <= threshold
            for previous in fingerprints
        ):
            continue
        selected.append(image)
        fingerprints.append(current)
    return selected
