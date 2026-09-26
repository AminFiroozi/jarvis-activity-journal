"""Hourly job: build the hourly, daily and weekly reports (each compacting the level below), then refresh llm-context."""

from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal-root", required=True, type=pathlib.Path)
    parser.add_argument("--config", required=True, type=pathlib.Path)
    parser.add_argument("--date", default=dt.date.today().isoformat())
    args = parser.parse_args()

    steps = [
        [sys.executable, "-m", "src.analysis.synthesize_period", "--journal-root", str(args.journal_root), "--config", str(args.config), "--period", period, "--date", args.date]
        for period in ("hourly", "daily", "weekly")
    ] + [
        [sys.executable, "-m", "src.analysis.build_llm_context", "--journal-root", str(args.journal_root), "--date", args.date],
    ]
    exit_code = 0
    for step in steps:
        result = subprocess.run(step, cwd=pathlib.Path(__file__).parents[2])
        exit_code = exit_code or result.returncode
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
