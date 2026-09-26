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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal-root", required=True, type=pathlib.Path)
    parser.add_argument("--backfill", action="store_true", help="write screen files for already-analysed screenshots")
    parser.add_argument("--requeue-failed", action="store_true", help="move dead-lettered vision jobs back to pending")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    summary: dict[str, int] = {}
    if args.backfill:
        summary["backfilled"] = backfill(args.journal_root)
    if args.requeue_failed:
        summary["requeued"] = FileJobQueue(args.journal_root / "queue").requeue_failed(kind="vision")
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
