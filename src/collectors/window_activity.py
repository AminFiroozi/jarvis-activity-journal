"""Cross-platform foreground-window + idle-time snapshot, one OS backend per platform."""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import getpass
import json
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys

from src.infra.heartbeat import write_heartbeat
from src.infra.privacy_state import is_private_mode

_warned_unsupported = False


@dataclasses.dataclass
class WindowSnapshot:
    process: str | None
    executable: str | None
    process_id: int | None
    window_title: str | None
    idle_seconds: float | None


def _snapshot_windows() -> WindowSnapshot | None:
    import ctypes

    user32 = ctypes.windll.user32

    class LastInputInfo(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    handle = user32.GetForegroundWindow()
    buffer = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(handle, buffer, 512)
    title = buffer.value

    process_id = ctypes.c_uint()
    user32.GetWindowThreadProcessId(handle, ctypes.byref(process_id))

    process_name = None
    executable = None
    if process_id.value:
        try:
            import psutil

            process = psutil.Process(process_id.value)
            process_name = process.name().removesuffix(".exe")
            executable = process.exe()
        except Exception:
            pass

    info = LastInputInfo()
    info.cbSize = ctypes.sizeof(LastInputInfo)
    idle_seconds = None
    if user32.GetLastInputInfo(ctypes.byref(info)):
        tick_count = ctypes.windll.kernel32.GetTickCount()
        idle_seconds = round((tick_count - info.dwTime) / 1000, 1)

    return WindowSnapshot(process_name, executable, process_id.value or None, title, idle_seconds)


def _snapshot_linux_x11() -> WindowSnapshot | None:
    try:
        from Xlib import X, display
    except ImportError:
        return None

    disp = display.Display()
    root = disp.screen().root
    active_atom = disp.intern_atom("_NET_ACTIVE_WINDOW")
    pid_atom = disp.intern_atom("_NET_WM_PID")
    prop = root.get_full_property(active_atom, X.AnyPropertyType)
    if not prop or not prop.value:
        return None
    window_id = prop.value[0]
    window = disp.create_resource_object("window", window_id)
    title = None
    try:
        name_prop = window.get_full_property(disp.intern_atom("_NET_WM_NAME"), 0)
        title = name_prop.value.decode("utf-8", errors="replace") if name_prop else window.get_wm_name()
    except Exception:
        pass
    process_id = None
    try:
        pid_prop = window.get_full_property(pid_atom, X.AnyPropertyType)
        process_id = int(pid_prop.value[0]) if pid_prop else None
    except Exception:
        pass

    process_name = None
    executable = None
    if process_id:
        try:
            import psutil

            process = psutil.Process(process_id)
            process_name = process.name()
            executable = process.exe()
        except Exception:
            pass

    idle_seconds = None
    if shutil.which("xprintidle"):
        try:
            output = subprocess.run(["xprintidle"], capture_output=True, text=True, timeout=5)
            idle_seconds = round(int(output.stdout.strip()) / 1000, 1)
        except (subprocess.SubprocessError, ValueError):
            idle_seconds = None

    return WindowSnapshot(process_name, executable, process_id, title, idle_seconds)


def _snapshot_macos() -> WindowSnapshot | None:
    try:
        import Quartz
    except ImportError:
        return None

    window_list = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID,
    )
    front = next((w for w in window_list if w.get("kCGWindowLayer") == 0), None)
    if not front:
        return None
    process_name = front.get("kCGWindowOwnerName")
    title = front.get("kCGWindowName")
    process_id = front.get("kCGWindowOwnerPID")

    idle_seconds = None
    try:
        idle_seconds = round(Quartz.CGEventSourceSecondsSinceLastEventType(Quartz.kCGEventSourceStateHIDSystemState, Quartz.kCGAnyInputEventType), 1)
    except Exception:
        pass

    return WindowSnapshot(process_name, None, process_id, title, idle_seconds)


def take_snapshot() -> WindowSnapshot | None:
    global _warned_unsupported
    system = platform.system()
    if system == "Windows":
        return _snapshot_windows()
    if system == "Linux":
        if "WAYLAND_DISPLAY" in os.environ and "DISPLAY" not in os.environ:
            if not _warned_unsupported:
                print("window_activity: Wayland has no standard active-window API; skipping window activity collection.", file=sys.stderr)
                _warned_unsupported = True
            return None
        return _snapshot_linux_x11()
    if system == "Darwin":
        return _snapshot_macos()
    if not _warned_unsupported:
        print(f"window_activity: unsupported platform {system!r}; skipping window activity collection.", file=sys.stderr)
        _warned_unsupported = True
    return None


def redact_title(title: str | None, patterns: list[str], max_length: int) -> str | None:
    if title is None:
        return None
    for pattern in patterns:
        if re.search(pattern, title, re.IGNORECASE):
            return "[redacted window title]"
    if len(title) > max_length:
        return title[:max_length] + "…"
    return title


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
    activity_config = (config.get("collectors") or {}).get("activity") or {}
    if not activity_config.get("enabled", True):
        return 0

    snapshot = take_snapshot()
    now = dt.datetime.now()
    interval_seconds = int(activity_config.get("intervalSeconds", 60))
    title = redact_title(
        snapshot.window_title if snapshot else None,
        config.get("redactTitlePatterns") or [],
        int(config.get("titleMaxLength", 180)),
    )
    event = {
        "timestamp": now.astimezone(dt.timezone.utc).isoformat(),
        "localTimestamp": now.astimezone().isoformat(),
        "source": "foreground-window",
        "computer": platform.node(),
        "user": getpass.getuser(),
        "process": snapshot.process if snapshot else None,
        "executable": snapshot.executable if snapshot else None,
        "processId": snapshot.process_id if snapshot else None,
        "windowTitle": title,
        "idleSeconds": snapshot.idle_seconds if snapshot else None,
        "active": snapshot is not None and (snapshot.idle_seconds is None or snapshot.idle_seconds < interval_seconds * 2),
    }
    output_path = journal_root / "raw" / f"activity-{now.strftime('%Y-%m-%d')}.jsonl"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    write_heartbeat(journal_root, "collector", "success", items_processed=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
