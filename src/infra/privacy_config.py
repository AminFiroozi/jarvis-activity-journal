"""Validation and defaults for activity-journal privacy settings."""

from copy import deepcopy
from typing import Any, Dict


DEFAULT_PRIVACY_CONFIG: Dict[str, Any] = {
    "captureEnabled": True,
    "privateModeHotkey": "Ctrl+Alt+Pause",
    "excludedApplications": [],
    "excludedWindowTitlePatterns": [],
    "redactBeforeStorage": True,
    "retentionDays": 14,
    "deleteRawScreenshotsAfterAnalysis": False,
}


def load_privacy_config(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Return validated privacy settings merged with safe defaults."""
    if not isinstance(settings, dict):
        raise ValueError("settings must be a JSON object")

    supplied = settings.get("privacy", {})
    if not isinstance(supplied, dict):
        raise ValueError("privacy must be a JSON object")

    result = deepcopy(DEFAULT_PRIVACY_CONFIG)
    result.update(supplied)

    if not isinstance(result["captureEnabled"], bool):
        raise ValueError("privacy.captureEnabled must be a boolean")
    if not isinstance(result["redactBeforeStorage"], bool):
        raise ValueError("privacy.redactBeforeStorage must be a boolean")
    if not isinstance(result["deleteRawScreenshotsAfterAnalysis"], bool):
        raise ValueError(
            "privacy.deleteRawScreenshotsAfterAnalysis must be a boolean"
        )
    if not isinstance(result["privateModeHotkey"], str) or not result[
        "privateModeHotkey"
    ].strip():
        raise ValueError("privacy.privateModeHotkey must be a non-empty string")
    if (
        not isinstance(result["retentionDays"], int)
        or isinstance(result["retentionDays"], bool)
        or result["retentionDays"] < 1
    ):
        raise ValueError("privacy.retentionDays must be a positive integer")

    for key in ("excludedApplications", "excludedWindowTitlePatterns"):
        values = result[key]
        if not isinstance(values, list) or not all(
            isinstance(value, str) and value.strip() for value in values
        ):
            raise ValueError(f"privacy.{key} must be a list of non-empty strings")

    return result
