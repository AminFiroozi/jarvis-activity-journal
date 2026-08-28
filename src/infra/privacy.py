"""Privacy helpers shared by activity collectors and model workers."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Mapping


@dataclass(frozen=True)
class RedactionResult:
    text: str
    rules: list[str]


def redact_text(text: str, patterns: Iterable[str]) -> RedactionResult:
    """Replace every configured match and return only rule identifiers."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")

    redacted = text
    matched_rules: list[str] = []
    for index, pattern in enumerate(patterns, start=1):
        try:
            updated, count = re.subn(pattern, "[REDACTED]", redacted)
        except re.error as error:
            raise ValueError(f"invalid redaction pattern {index}: {error}") from error
        if count:
            matched_rules.append(f"pattern-{index}")
            redacted = updated
    return RedactionResult(redacted, matched_rules)


def is_excluded(
    application: str,
    window_title: str,
    config: Mapping[str, object],
) -> bool:
    """Return whether an application/window pair must not be captured."""
    application_name = application or ""
    title = window_title or ""
    excluded_apps = config.get("excludedApplications", [])
    if any(
        isinstance(value, str) and value.casefold() == application_name.casefold()
        for value in excluded_apps  # type: ignore[union-attr]
    ):
        return True

    for pattern in config.get("excludedWindowTitlePatterns", []):  # type: ignore[union-attr]
        if not isinstance(pattern, str):
            continue
        try:
            if re.search(pattern, title, flags=re.IGNORECASE):
                return True
        except re.error as error:
            raise ValueError(f"invalid excluded window-title pattern: {error}") from error
    return False
