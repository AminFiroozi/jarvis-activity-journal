"""Remove scheduled jobs installed by install.py."""

from __future__ import annotations

import argparse
import pathlib
import platform
import subprocess

from src.orchestration.install import DAILY_JOB, INTERVAL_JOBS, LOGON_JOB, TASK_PREFIX, VISION_SERVICE_JOB, _systemd_dir


def uninstall_windows() -> None:
    names = [f"{TASK_PREFIX} - {name}" for name, *_ in INTERVAL_JOBS] + [
        f"{TASK_PREFIX} - {DAILY_JOB[0]}",
        f"{TASK_PREFIX} - {LOGON_JOB[0]}",
        f"{TASK_PREFIX} - {VISION_SERVICE_JOB[0]}",
    ]
    for name in names:
        subprocess.run(["schtasks", "/Delete", "/TN", name, "/F"], capture_output=True)
    print("Removed scheduled tasks (where present).")


def uninstall_linux() -> None:
    job_names = [name for name, *_ in INTERVAL_JOBS] + [DAILY_JOB[0]]
    unit_dir = _systemd_dir()
    for name in job_names:
        subprocess.run(["systemctl", "--user", "disable", "--now", f"jarvis-{name}.timer"], capture_output=True)
        (unit_dir / f"jarvis-{name}.service").unlink(missing_ok=True)
        (unit_dir / f"jarvis-{name}.timer").unlink(missing_ok=True)
    for name, _module in (LOGON_JOB, VISION_SERVICE_JOB):
        subprocess.run(["systemctl", "--user", "disable", "--now", f"jarvis-{name}.service"], capture_output=True)
        (unit_dir / f"jarvis-{name}.service").unlink(missing_ok=True)
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    print("Removed systemd user units (where present).")


def main() -> int:
    argparse.ArgumentParser().parse_args()
    system = platform.system()
    if system == "Windows":
        uninstall_windows()
        return 0
    if system == "Linux":
        uninstall_linux()
        return 0
    print(f"Nothing to uninstall automatically on {system!r}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
