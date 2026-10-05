"""Delete journal files older than the configured retention window."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib

_PRUNED_SUBDIRECTORIES = (
    "raw",
    "screenshots",
    "hourly",
    "daily",
    "llm-context",
    "queue/completed",
    "queue/failed",
    "queue-period/completed",
    "queue-period/failed",
)


def _queued_screenshots(journal_root: pathlib.Path) -> set[pathlib.Path]:
    """Screenshots that a live queue job still needs.

    A screenshot is created at capture time and analysed much later, so its job can sit in
    `pending` for days. Retention prunes by file mtime alone, which would happily delete a file
    whose analysis is still scheduled -- the job then fails forever and burns attempts on a file
    that no longer exists. Anything referenced by a pending or in-flight vision job is therefore
    off limits until the job has run.
    """
    queued: set[pathlib.Path] = set()
    for state in ("pending", "processing"):
        directory = journal_root / "queue" / state
        if not directory.is_dir():
            continue
        for path in directory.glob("*.json"):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(job, dict) or job.get("kind") != "vision":
                continue
            screenshot = (job.get("payload") or {}).get("screenshot")
            if screenshot:
                queued.add(pathlib.Path(screenshot))
    return queued


def run_retention(journal_root: pathlib.Path, retention_days: int) -> dict:
    cutoff = dt.datetime.now() - dt.timedelta(days=retention_days)
    queued = _queued_screenshots(journal_root)
    removed = 0
    kept_queued = 0
    for relative in _PRUNED_SUBDIRECTORIES:
        target = journal_root / relative
        if not target.exists():
            continue
        for path in target.rglob("*"):
            if not path.is_file() or dt.datetime.fromtimestamp(path.stat().st_mtime) >= cutoff:
                continue
            if path in queued:
                kept_queued += 1
                continue
            path.unlink()
            removed += 1
    return {
        "retentionDays": retention_days,
        "cutoff": cutoff.astimezone(dt.timezone.utc).isoformat(),
        "removedFiles": removed,
        "keptQueued": kept_queued,
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
