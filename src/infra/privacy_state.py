"""Read and set the manual private-mode flag that pauses all collectors."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib


def state_path(journal_root: pathlib.Path) -> pathlib.Path:
    return journal_root / "config" / "private-mode.json"


def is_private_mode(journal_root: pathlib.Path) -> bool:
    path = state_path(journal_root)
    if not path.exists():
        return False
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        return bool(state.get("enabled"))
    except (json.JSONDecodeError, OSError):
        return True


def set_private_mode(journal_root: pathlib.Path, enabled: bool, reason: str = "manual") -> pathlib.Path:
    path = state_path(journal_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {"enabled": enabled, "changedAt": dt.datetime.now(dt.timezone.utc).isoformat(), "reason": reason}
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal-root", required=True, type=pathlib.Path)
    parser.add_argument("--enabled", required=True, choices=("true", "false"))
    parser.add_argument("--reason", default="manual")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    path = set_private_mode(args.journal_root, args.enabled == "true", args.reason)
    print(str(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
