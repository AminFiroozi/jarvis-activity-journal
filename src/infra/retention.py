"""Delete journal files older than the configured retention window."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib

_PRUNED_SUBDIRECTORIES = ("raw", "screenshots", "hourly", "daily", "llm-context", "queue/completed", "queue/failed")


def run_retention(journal_root: pathlib.Path, retention_days: int) -> dict:
    cutoff = dt.datetime.now() - dt.timedelta(days=retention_days)
    removed = 0
    for relative in _PRUNED_SUBDIRECTORIES:
        target = journal_root / relative
        if not target.exists():
            continue
        for path in target.rglob("*"):
            if path.is_file() and dt.datetime.fromtimestamp(path.stat().st_mtime) < cutoff:
                path.unlink()
                removed += 1
    return {
        "retentionDays": retention_days,
        "cutoff": cutoff.astimezone(dt.timezone.utc).isoformat(),
        "removedFiles": removed,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal-root", required=True, type=pathlib.Path)
    parser.add_argument("--config", required=True, type=pathlib.Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    privacy = config.get("privacy") or {}
    retention_days = int(privacy.get("retentionDays", config.get("retentionDays", 90)))
    result = run_retention(args.journal_root, retention_days)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
