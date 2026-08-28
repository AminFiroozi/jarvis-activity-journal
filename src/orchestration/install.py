"""Cross-platform scheduler installer: Windows Task Scheduler, Linux systemd user timers."""

from __future__ import annotations

import argparse
import datetime as dt
import getpass
import json
import pathlib
import platform
import shutil
import subprocess
import sys
from xml.sax.saxutils import escape

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

INTERVAL_JOBS = [
    ("activity", "src.collectors.window_activity", ("collectors", "activity", "intervalSeconds"), 60, 2),
    ("content", "src.collectors.active_content", ("collectors", "content", "intervalSeconds"), 60, 2),
    ("screenshot", "src.collectors.capture", ("collectors", "screenshot", "intervalSeconds"), 60, 2),
    ("project-evidence", "src.collectors.project_evidence", ("collectors", "projectEvidence", "intervalSeconds"), 900, 5),
    ("vision-analysis", "src.analysis.analyze_screenshots", ("screenshotAnalyzer", "intervalSeconds"), 900, 40),
    ("hourly", "src.orchestration.run_hourly", ("hourlyBuild", "intervalSeconds"), 3600, 40),
]
DAILY_JOB = ("daily-summary", "src.orchestration.daily_summary", ("dailySummary", "time"), "23:55", 40)
LOGON_JOB = ("startup", "src.orchestration.run_now")
VISION_SERVICE_JOB = ("vision-service", "src.orchestration.start_vision_service")

TASK_PREFIX = "Jarvis Activity Journal"


def _get(config: dict, path: tuple[str, ...], default):
    node = config
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def _pythonw() -> str:
    candidate = pathlib.Path(sys.executable).with_name("pythonw.exe")
    return str(candidate) if candidate.exists() else sys.executable


def _current_user_id() -> str:
    domain = __import__("os").environ.get("USERDOMAIN", platform.node())
    return f"{domain}\\{getpass.getuser()}"


def _module_args(journal_root: pathlib.Path, config_path: pathlib.Path, module: str) -> str:
    return f'-m {module} --journal-root "{journal_root}" --config "{config_path}"'


def _windows_task_xml(command: str, arguments: str, trigger_xml: str, time_limit_minutes: int) -> str:
    user = _current_user_id()
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    {trigger_xml}
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{escape(user)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <ExecutionTimeLimit>PT{time_limit_minutes}M</ExecutionTimeLimit>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(command)}</Command>
      <Arguments>{escape(arguments)}</Arguments>
      <WorkingDirectory>{escape(str(REPO_ROOT))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>"""


def _register_windows_task(task_name: str, command: str, arguments: str, trigger_xml: str, time_limit_minutes: int) -> bool:
    xml_text = _windows_task_xml(command, arguments, trigger_xml, time_limit_minutes)
    tmp_path = pathlib.Path(__import__("tempfile").gettempdir()) / f"{task_name.replace(' ', '_')}.xml"
    tmp_path.write_text(xml_text, encoding="utf-16")
    result = subprocess.run(["schtasks", "/Create", "/TN", task_name, "/XML", str(tmp_path), "/F"], capture_output=True, text=True)
    tmp_path.unlink(missing_ok=True)
    if result.returncode != 0:
        print(f"Failed to register {task_name!r}: {result.stdout.strip()} {result.stderr.strip()}")
        return False
    return True


def install_windows(journal_root: pathlib.Path, config_path: pathlib.Path, config: dict) -> bool:
    pythonw = _pythonw()
    first_run = (dt.datetime.now() + dt.timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%S")
    all_ok = True

    for name, module, path, default, time_limit in INTERVAL_JOBS:
        seconds = int(_get(config, path, default))
        minutes = max(1, round(seconds / 60))
        trigger = f"""<TimeTrigger>
      <StartBoundary>{first_run}</StartBoundary>
      <Repetition>
        <Interval>PT{minutes}M</Interval>
      </Repetition>
      <Enabled>true</Enabled>
    </TimeTrigger>"""
        all_ok &= _register_windows_task(f"{TASK_PREFIX} - {name}", pythonw, _module_args(journal_root, config_path, module), trigger, time_limit)

    name, module, path, default, time_limit = DAILY_JOB
    time_value = str(_get(config, path, default))
    trigger = f"""<CalendarTrigger>
      <StartBoundary>{dt.date.today().isoformat()}T{time_value}:00</StartBoundary>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
      <Enabled>true</Enabled>
    </CalendarTrigger>"""
    all_ok &= _register_windows_task(f"{TASK_PREFIX} - {name}", pythonw, _module_args(journal_root, config_path, module), trigger, time_limit)

    logon_trigger = f"<LogonTrigger><UserId>{escape(_current_user_id())}</UserId><Enabled>true</Enabled></LogonTrigger>"
    for name, module in (LOGON_JOB, VISION_SERVICE_JOB):
        all_ok &= _register_windows_task(f"{TASK_PREFIX} - {name}", pythonw, _module_args(journal_root, config_path, module), logon_trigger, 5)

    print("Installed scheduled tasks:")
    result = subprocess.run(["schtasks", "/Query", "/FO", "CSV"], capture_output=True, text=True)
    for line in result.stdout.splitlines():
        if TASK_PREFIX in line:
            print(line)
    return all_ok


def _systemd_dir() -> pathlib.Path:
    return pathlib.Path.home() / ".config" / "systemd" / "user"


def _write_systemd_unit(name: str, module: str, journal_root: pathlib.Path, config_path: pathlib.Path, timer_body: str, time_limit_minutes: int) -> None:
    unit_dir = _systemd_dir()
    unit_dir.mkdir(parents=True, exist_ok=True)
    service = f"""[Unit]
Description={TASK_PREFIX} - {name}

[Service]
Type=oneshot
WorkingDirectory={REPO_ROOT}
ExecStart={sys.executable} -m {module} --journal-root {journal_root} --config {config_path}
TimeoutStartSec={time_limit_minutes * 60}
"""
    (unit_dir / f"jarvis-{name}.service").write_text(service, encoding="utf-8")
    timer = f"""[Unit]
Description={TASK_PREFIX} - {name} timer

[Timer]
{timer_body}
AccuracySec=5s
Persistent=true

[Install]
WantedBy=timers.target
"""
    (unit_dir / f"jarvis-{name}.timer").write_text(timer, encoding="utf-8")


def install_linux(journal_root: pathlib.Path, config_path: pathlib.Path, config: dict) -> None:
    for name, module, path, default, time_limit in INTERVAL_JOBS:
        seconds = int(_get(config, path, default))
        _write_systemd_unit(name, module, journal_root, config_path, f"OnBootSec=2min\nOnUnitActiveSec={seconds}s", time_limit)

    name, module, path, default, time_limit = DAILY_JOB
    time_value = str(_get(config, path, default))
    _write_systemd_unit(name, module, journal_root, config_path, f"OnCalendar=*-*-* {time_value}:00", time_limit)

    unit_dir = _systemd_dir()
    unit_dir.mkdir(parents=True, exist_ok=True)
    for name, module in (LOGON_JOB, VISION_SERVICE_JOB):
        logon_service = f"""[Unit]
Description={TASK_PREFIX} - {name}

[Service]
Type=oneshot
WorkingDirectory={REPO_ROOT}
ExecStart={sys.executable} -m {module} --journal-root {journal_root} --config {config_path}

[Install]
WantedBy=default.target
"""
        (unit_dir / f"jarvis-{name}.service").write_text(logon_service, encoding="utf-8")

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    for job_name, *_ in INTERVAL_JOBS + [DAILY_JOB]:
        subprocess.run(["systemctl", "--user", "enable", "--now", f"jarvis-{job_name}.timer"], check=True)
    for name, _module in (LOGON_JOB, VISION_SERVICE_JOB):
        subprocess.run(["systemctl", "--user", "enable", "--now", f"jarvis-{name}.service"], check=True)

    print("Installed systemd user timers under ~/.config/systemd/user/.")
    print("If this machine reboots without you logging in, run: loginctl enable-linger " + getpass.getuser())
    subprocess.run(["systemctl", "--user", "list-timers", "jarvis-*"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal-root", required=True, type=pathlib.Path)
    parser.add_argument("--config", required=True, type=pathlib.Path)
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    system = platform.system()
    if system == "Windows":
        return 0 if install_windows(args.journal_root, args.config, config) else 1
    if system == "Linux":
        if not shutil.which("systemctl"):
            print("systemd is required for automatic scheduling on Linux; install/enable systemd --user, or run the collectors manually via cron.")
            return 1
        install_linux(args.journal_root, args.config, config)
        return 0
    print(f"Automatic scheduling is not implemented for {system!r} yet.")
    print("Run the collectors manually, e.g.:")
    print(f"  {sys.executable} -m src.orchestration.run_now --journal-root {args.journal_root} --config {args.config}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
