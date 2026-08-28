"""Write per-service health heartbeats consumed by doctor.py and dashboard.py."""

from __future__ import annotations

import datetime as dt
import json
import pathlib


def write_heartbeat(
    journal_root: pathlib.Path,
    service: str,
    status: str,
    items_processed: int = 0,
    error_message: str | None = None,
) -> pathlib.Path:
    if status not in ("started", "success", "failed"):
        raise ValueError(f"invalid heartbeat status: {status}")
    health_directory = journal_root / "health"
    health_directory.mkdir(parents=True, exist_ok=True)
    path = health_directory / f"{service}.json"
    existing = None
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = None
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    heartbeat = {
        "service": service,
        "status": status,
        "startedAt": (existing or {}).get("startedAt", now),
        "lastSuccessAt": now if status == "success" else (existing or {}).get("lastSuccessAt"),
        "lastErrorAt": now if status == "failed" else (existing or {}).get("lastErrorAt"),
        "lastError": error_message if status == "failed" else (existing or {}).get("lastError"),
        "itemsProcessed": items_processed,
        "updatedAt": now,
    }
    temporary_path = path.with_suffix(".json.tmp")
    temporary_path.write_text(json.dumps(heartbeat, indent=2), encoding="utf-8")
    temporary_path.replace(path)
    return path
