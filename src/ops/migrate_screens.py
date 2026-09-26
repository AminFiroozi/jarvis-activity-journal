"""One-shot migration helpers for the per-screenshot Markdown reports."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

from src.analysis.screen_markdown import screen_path, write_screen_markdown
from src.infra.processing_queue import FileJobQueue


def backfill(journal_root: pathlib.Path) -> int:
    written = 0
    for path in sorted((journal_root / "raw").glob("visual-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                image = pathlib.Path(record["screenshot"])
                analysis = record["analysis"]
            except (json.JSONDecodeError, KeyError):
                continue
            if not isinstance(analysis, dict) or screen_path(journal_root, image).exists():
                continue
            write_screen_markdown(journal_root, image, analysis)
            written += 1
    return written


def _screenshot_exists(job: dict) -> bool:
    screenshot = (job.get("payload") or {}).get("screenshot")
    return bool(screenshot) and pathlib.Path(screenshot).exists()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal-root", required=True, type=pathlib.Path)
    parser.add_argument("--backfill", action="store_true", help="write screen files for already-analysed screenshots")
    parser.add_argument("--requeue-failed", action="store_true", help="move dead-lettered vision jobs back to pending")
    parser.add_argument("--drop-missing", action="store_true", help="dead-letter pending vision jobs whose screenshot file no longer exists")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    summary: dict[str, int] = {}
    if args.backfill:
        summary["backfilled"] = backfill(args.journal_root)
    queue = FileJobQueue(args.journal_root / "queue")
    if args.drop_missing:
        summary["dropped"] = queue.dead_letter_pending(lambda job: not _screenshot_exists(job), "screenshot file missing", kind="vision")
    if args.requeue_failed:
        summary["requeued"] = queue.requeue_failed(kind="vision", should_requeue=_screenshot_exists)
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
