"""One-shot logon pass: run every collector once immediately."""

from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal-root", required=True, type=pathlib.Path)
    parser.add_argument("--config", required=True, type=pathlib.Path)
    args = parser.parse_args()

    repo_root = pathlib.Path(__file__).parents[2]
    for module in ("src.collectors.window_activity", "src.collectors.project_evidence", "src.collectors.active_content", "src.collectors.capture"):
        subprocess.run([sys.executable, "-m", module, "--journal-root", str(args.journal_root), "--config", str(args.config)], cwd=repo_root)
    subprocess.run([sys.executable, "-m", "src.analysis.build_llm_context", "--journal-root", str(args.journal_root)], cwd=repo_root)
    print("Activity journal collection completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
