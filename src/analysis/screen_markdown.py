"""Render one Markdown file per screenshot from its vision analysis."""

from __future__ import annotations

import json
import pathlib
import re

_STEM_PATTERN = re.compile(r"^screen-(\d{2})-(\d{2})-(\d{2})-(\d{3})$")


def _clock(image: pathlib.Path) -> str:
    match = _STEM_PATTERN.match(image.stem)
    return f"{match.group(1)}:{match.group(2)}:{match.group(3)}" if match else image.stem


def _names(value) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _lines(value) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def screen_path(journal_root: pathlib.Path, image: pathlib.Path) -> pathlib.Path:
    match = _STEM_PATTERN.match(image.stem)
    hour = match.group(1) if match else "unknown"
    return journal_root / "screens" / image.parent.name / hour / f"{image.stem.removeprefix('screen-')}.md"


def render_screen_markdown(image: pathlib.Path, analysis: dict, unchanged_since: str | None = None) -> str:
    lines = [f"# Screen — {image.parent.name} {_clock(image)}", ""]
    summary = str(analysis.get("summary") or "").strip()
    if summary:
        lines.extend([summary, ""])
    if unchanged_since:
        lines.extend([f"Unchanged since {unchanged_since}.", ""])
    details = _lines(analysis.get("screen_details")) + _lines(analysis.get("observations"))
    if details:
        lines.extend(["### On screen", ""])
        lines.extend(f"- {detail}" for detail in details)
        lines.append("")
    for label, names in (("Apps", _names(analysis.get("applications"))), ("Projects", _names(analysis.get("projects")))):
        if names:
            lines.extend([f"**{label}:** {', '.join(names)}", ""])
    activity = str(analysis.get("activity_type") or "").strip()
    if activity:
        lines.extend([f"**Activity:** {activity}", ""])
    return "\n".join(lines).rstrip() + "\n"


def write_screen_markdown(
    journal_root: pathlib.Path,
    image: pathlib.Path,
    analysis: dict,
    unchanged_since: str | None = None,
) -> pathlib.Path:
    target = screen_path(journal_root, image)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_screen_markdown(image, analysis, unchanged_since), encoding="utf-8")
    return target


def load_analyses(journal_root: pathlib.Path, date: str) -> dict[str, dict]:
    path = journal_root / "raw" / f"visual-{date}.jsonl"
    analyses: dict[str, dict] = {}
    if not path.exists():
        return analyses
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            analysis = record["analysis"]
            screenshot = record["screenshot"]
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
        if isinstance(analysis, dict):
            analyses[str(screenshot)] = analysis
    return analyses


def reconcile_duplicates(
    journal_root: pathlib.Path,
    date: str,
    new_matches: dict[pathlib.Path, pathlib.Path],
) -> list[pathlib.Path]:
    map_path = journal_root / "raw" / f"screen-dups-{date}.json"
    mapping: dict[str, str] = {}
    if map_path.exists():
        try:
            loaded = json.loads(map_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                mapping = {str(key): str(value) for key, value in loaded.items()}
        except (OSError, json.JSONDecodeError):
            mapping = {}
    mapping.update({str(duplicate): str(kept) for duplicate, kept in new_matches.items()})

    analyses = load_analyses(journal_root, date)
    written: list[pathlib.Path] = []
    for duplicate, kept in mapping.items():
        duplicate_image = pathlib.Path(duplicate)
        if screen_path(journal_root, duplicate_image).exists():
            continue
        analysis = analyses.get(kept)
        if analysis is None:
            continue
        written.append(write_screen_markdown(journal_root, duplicate_image, analysis, unchanged_since=_clock(pathlib.Path(kept))))

    map_path.parent.mkdir(parents=True, exist_ok=True)
    map_path.write_text(json.dumps(mapping, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return written
