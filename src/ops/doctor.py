"""Local diagnostics for the Jarvis Activity Journal installation."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def _check(name: str, ok: bool, detail: str, required: bool = True) -> dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail, "required": required}


def run_local_checks(root: Path, minimum_free_bytes: int = 1_000_000_000) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    config_path = root / "config" / "settings.json"
    checks.append(_check("journal-root", root.exists(), str(root)))
    checks.append(_check("settings-file", config_path.is_file(), str(config_path)))

    if config_path.is_file():
        try:
            settings = json.loads(config_path.read_text(encoding="utf-8"))
            checks.append(_check("settings-json", isinstance(settings, dict), "valid JSON object"))
        except (OSError, json.JSONDecodeError) as error:
            checks.append(_check("settings-json", False, str(error)))

    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".doctor-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        checks.append(_check("journal-write", True, "write test passed"))
    except OSError as error:
        checks.append(_check("journal-write", False, str(error)))

    try:
        free_bytes = shutil.disk_usage(root).free
        checks.append(
            _check(
                "disk-space",
                free_bytes >= minimum_free_bytes,
                f"{free_bytes} free bytes",
            )
        )
    except OSError as error:
        checks.append(_check("disk-space", False, str(error)))

    checks.append(
        _check(
            "python-version",
            sys.version_info >= (3, 10),
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        )
    )
    failed_queue_dir = root / "queue" / "failed"
    failed_count = len(list(failed_queue_dir.glob("*.json"))) if failed_queue_dir.exists() else 0
    checks.append(
        _check(
            "queue-failed",
            failed_count == 0,
            f"{failed_count} screenshot(s) gave up after repeated failures" if failed_count else "no dead-lettered jobs",
            required=False,
        )
    )
    failed_period_queue_dir = root / "queue-period" / "failed"
    failed_period_count = len(list(failed_period_queue_dir.glob("*.json"))) if failed_period_queue_dir.exists() else 0
    checks.append(
        _check(
            "queue-period-failed",
            failed_period_count == 0,
            f"{failed_period_count} period synthesis job(s) gave up after repeated failures" if failed_period_count else "no dead-lettered jobs",
            required=False,
        )
    )
    return checks


def _scheduler_checks() -> list[dict[str, Any]]:
    system = platform.system()
    expected = ["activity", "content", "screenshot", "project-evidence", "vision-analysis", "hourly", "daily-summary", "startup"]
    if system == "Windows":
        if not shutil.which("schtasks"):
            return [_check("scheduler", False, "schtasks not found", required=False)]
        result = subprocess.run(["schtasks", "/Query", "/FO", "CSV"], capture_output=True, text=True)
        installed = result.stdout
        return [_check(f"scheduled-task:{name}", f"Jarvis Activity Journal - {name}" in installed, "Task Scheduler", required=False) for name in expected]
    if system == "Linux":
        if not shutil.which("systemctl"):
            return [_check("scheduler", False, "systemctl not found", required=False)]
        result = subprocess.run(["systemctl", "--user", "list-unit-files", "jarvis-*"], capture_output=True, text=True)
        installed = result.stdout
        return [_check(f"scheduled-task:{name}", f"jarvis-{name}" in installed, "systemd --user", required=False) for name in expected]
    return [_check("scheduler", False, f"no scheduler check implemented for {system!r}", required=False)]


def doctor_exit_code(checks: list[dict[str, Any]]) -> int:
    if any(not check["ok"] and check.get("required", True) for check in checks):
        return 1
    if any(not check["ok"] for check in checks):
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal-root", required=True, type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    checks = run_local_checks(args.journal_root)
    scheduler_checks = _scheduler_checks()
    if args.as_json:
        print(json.dumps({"checks": checks, "schedulerChecks": scheduler_checks, "exitCode": doctor_exit_code(checks)}))
    else:
        for check in checks + scheduler_checks:
            status = "PASS" if check["ok"] else ("FAIL" if check.get("required", True) else "WARN")
            print(f"[{status}] {check['name']}: {check['detail']}")
    return doctor_exit_code(checks)


if __name__ == "__main__":
    raise SystemExit(main())
