"""Hourly job: build the hourly, daily and weekly reports (each compacting the level below), then refresh llm-context.

A finished day keeps gaining evidence for a while: screenshots taken at 23:55 are only analysed
after midnight, and their vision results are filed under the day they belong to. So every run also
revisits the previous day. Unchanged reports cost nothing — the input stamp makes the rebuild a
no-op — and only the hours that actually gained screenshots reach the model.
"""

from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import subprocess
import sys

PERIODS = ("hourly", "daily", "weekly")


def catch_up_dates(date: str, days: int) -> list[str]:
    """The given date plus the `days` calendar days before it, oldest last."""
    if days <= 0:
        return [date]
    parsed = dt.date.fromisoformat(date)
    return [(parsed - dt.timedelta(days=offset)).isoformat() for offset in range(days, -1, -1)]


def steps_for(journal_root: pathlib.Path, config: pathlib.Path, date: str) -> list[list[str]]:
    return [
        [
            sys.executable, "-m", "src.analysis.synthesize_period",
            "--journal-root", str(journal_root), "--config", str(config),
            "--period", period, "--date", date,
        ]
        for period in PERIODS
    ] + [
        [sys.executable, "-m", "src.analysis.build_llm_context", "--journal-root", str(journal_root), "--date", date],
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal-root", required=True, type=pathlib.Path)
    parser.add_argument("--config", required=True, type=pathlib.Path)
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument(
        "--catch-up-days",
        type=int,
        default=1,
        help="Also rebuild this many previous days (default 1); 0 disables catch-up.",
    )
    args = parser.parse_args()

    repository_root = pathlib.Path(__file__).parents[2]
    exit_code = 0
    for date in catch_up_dates(args.date, args.catch_up_days):
        for step in steps_for(args.journal_root, args.config, date):
            result = subprocess.run(step, cwd=repository_root)
            exit_code = exit_code or result.returncode
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())