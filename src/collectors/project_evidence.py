"""Record lightweight git evidence (branch, dirty count, latest commit) for configured project paths."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import subprocess

from src.infra.heartbeat import write_heartbeat
from src.infra.privacy_state import is_private_mode


def run_git(*args: str, cwd: pathlib.Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        timeout=15,
    )
    return result.stdout.strip()


def collect_project_event(project_path: pathlib.Path) -> dict | None:
    if not (project_path / ".git").exists():
        return None
    branch = run_git("branch", "--show-current", cwd=project_path)
    status_lines = [line for line in run_git("status", "--porcelain", cwd=project_path).splitlines() if line.strip()]
    latest = run_git("log", "-1", "--format=%h|%s|%aI", cwd=project_path)
    parts = latest.split("|", 2)
    return {
        "source": "git-project",
        "projectPath": str(project_path.resolve()),
        "branch": branch or None,
        "changedFileCount": len(status_lines),
        "latestCommit": parts[0] if len(parts) > 0 and parts[0] else None,
        "latestCommitMessage": parts[1] if len(parts) > 1 else None,
        "latestCommitTimestamp": parts[2] if len(parts) > 2 else None,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal-root", required=True, type=pathlib.Path)
    parser.add_argument("--config", required=True, type=pathlib.Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    journal_root: pathlib.Path = args.journal_root
    if is_private_mode(journal_root):
        return 0
    config = json.loads(args.config.read_text(encoding="utf-8"))
    now = dt.datetime.now()
    output_path = journal_root / "raw" / f"activity-{now.strftime('%Y-%m-%d')}.jsonl"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    processed = 0
    with output_path.open("a", encoding="utf-8") as handle:
        for raw_path in config.get("projectPaths") or []:
            project_path = pathlib.Path(raw_path)
            if not project_path.is_dir():
                continue
            try:
                event = collect_project_event(project_path)
            except (subprocess.SubprocessError, OSError):
                continue
            if event is None:
                continue
            event["timestamp"] = now.astimezone(dt.timezone.utc).isoformat()
            event["localTimestamp"] = now.astimezone().isoformat()
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            processed += 1
    write_heartbeat(journal_root, "project-evidence", "success", items_processed=processed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
