"""Cross-platform full-desktop screenshot capture with perceptual-hash dedupe."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib

import mss
import mss.tools
from PIL import Image

try:
    from heartbeat import write_heartbeat
    from privacy_state import is_private_mode
    from screenshot_fingerprint import hamming_distance
except ImportError:
    from src.heartbeat import write_heartbeat
    from src.privacy_state import is_private_mode
    from src.screenshot_fingerprint import hamming_distance


def compute_hash(image: Image.Image) -> str:
    grayscale = image.convert("L").resize((16, 16))
    pixels = list(grayscale.getdata())
    average = sum(pixels) / len(pixels)
    return "".join("1" if pixel >= average else "0" for pixel in pixels)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal-root", required=True, type=pathlib.Path)
    parser.add_argument("--config", required=True, type=pathlib.Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    journal_root: pathlib.Path = args.journal_root
    config = json.loads(args.config.read_text(encoding="utf-8"))
    screenshot_config = (config.get("collectors") or {}).get("screenshot") or {}
    if not screenshot_config.get("enabled", True):
        return 0
    if is_private_mode(journal_root):
        return 0

    now = dt.datetime.now()
    directory = journal_root / "screenshots" / now.strftime("%Y-%m-%d")
    directory.mkdir(parents=True, exist_ok=True)

    with mss.mss() as capture:
        monitor = capture.monitors[0]
        raw = capture.grab(monitor)
        image = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

    thumbnail_hash = compute_hash(image)
    state_path = journal_root / "screenshots" / ".capture-state.json"
    previous_hash = None
    if state_path.exists():
        try:
            previous_hash = json.loads(state_path.read_text(encoding="utf-8")).get("hash")
        except (json.JSONDecodeError, OSError):
            previous_hash = None

    threshold = int(screenshot_config.get("dedupeHammingThreshold", 4))
    is_duplicate = (
        previous_hash is not None
        and len(previous_hash) == len(thumbnail_hash)
        and hamming_distance(thumbnail_hash, previous_hash) <= threshold
    )
    if is_duplicate:
        write_heartbeat(journal_root, "screen-capture", "success", items_processed=0)
        return 0

    quality = int(screenshot_config.get("jpegQuality", 60))
    path = directory / f"screen-{now.strftime('%H-%M-%S-%f')[:-3]}.jpg"
    image.save(path, "JPEG", quality=quality)
    state_path.write_text(
        json.dumps({"hash": thumbnail_hash, "updatedAt": dt.datetime.now(dt.timezone.utc).isoformat()}),
        encoding="utf-8",
    )
    write_heartbeat(journal_root, "screen-capture", "success", items_processed=1)
    print(str(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
