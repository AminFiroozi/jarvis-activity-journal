"""Capture visible text from the focused window's controls, where the platform supports it.

Windows uses UI Automation via pywinauto. Linux and macOS accessibility APIs are not
implemented yet (AT-SPI and the macOS Accessibility API both require environment-specific
setup that cannot be exercised or verified from this codebase); both back ends return no
content rather than pretend to support something untested.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import platform
import sys

from src.infra.heartbeat import write_heartbeat
from src.infra.privacy import is_excluded, redact_text
from src.infra.privacy_state import is_private_mode

_warned_unsupported = False
_TEXT_CONTROL_TYPES = {"Text", "Edit", "ListItem", "Document", "TabItem"}


def _capture_windows(allowed_process_names: list[str], max_element_count: int) -> tuple[str | None, str | None, int | None, str | None]:
    try:
        import ctypes

        import psutil
        from pywinauto import Desktop
    except ImportError:
        return None, None, None, None

    handle = ctypes.windll.user32.GetForegroundWindow()
    if not handle:
        return None, None, None, None
    try:
        window = Desktop(backend="uia").window(handle=handle).wrapper_object()
    except Exception:
        return None, None, None, None

    try:
        process_id = window.process_id()
        process_name = psutil.Process(process_id).name().removesuffix(".exe")
    except Exception:
        return None, None, None, None

    if allowed_process_names and process_name not in allowed_process_names:
        return None, None, None, None

    window_title = None
    try:
        window_title = window.window_text()
    except Exception:
        pass

    parts: list[str] = []
    count = 0

    def visit(element) -> None:
        nonlocal count
        if count >= max_element_count:
            return
        try:
            control_type = element.element_info.control_type
            if control_type in _TEXT_CONTROL_TYPES:
                value = element.window_text()
                if value and value.strip() and value not in parts:
                    parts.append(value.strip())
                    count += 1
            for child in element.children():
                if count >= max_element_count:
                    return
                visit(child)
        except Exception:
            return

    visit(window)
    return "\n".join(parts), process_name, process_id, window_title


def capture_focused_content(allowed_process_names: list[str], max_element_count: int) -> tuple[str | None, str | None, int | None, str | None]:
    global _warned_unsupported
    system = platform.system()
    if system == "Windows":
        return _capture_windows(allowed_process_names, max_element_count)
    if not _warned_unsupported:
        print(f"active_content: focused-content capture is not implemented on {system!r}; skipping.", file=sys.stderr)
        _warned_unsupported = True
    return None, None, None, None


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
    content_config = (config.get("collectors") or {}).get("content") or {}
    if not content_config.get("enabled", True):
        return 0
    privacy = config.get("privacy") or {}
    if privacy.get("captureEnabled") is False:
        return 0

    text, process_name, process_id, window_title = capture_focused_content(
        content_config.get("allowedProcessNames") or [],
        int(content_config.get("maxElementCount", 120)),
    )
    if not text or not text.strip():
        return 0
    if is_excluded(process_name or "", window_title or "", privacy):
        return 0

    if privacy.get("redactBeforeStorage", True):
        text = redact_text(text, content_config.get("redactTextPatterns") or []).text
    max_length = int(content_config.get("maxTextLength", 12000))
    if len(text) > max_length:
        text = text[:max_length] + "…"

    now = dt.datetime.now()
    event = {
        "timestamp": now.astimezone(dt.timezone.utc).isoformat(),
        "localTimestamp": now.astimezone().isoformat(),
        "source": "focused-content",
        "process": process_name,
        "processId": process_id,
        "content": text,
        "captureMode": f"{platform.system()} accessibility API; focused window only",
    }
    output_path = journal_root / "raw" / f"content-{now.strftime('%Y-%m-%d')}.jsonl"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    write_heartbeat(journal_root, "content-collector", "success", items_processed=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
