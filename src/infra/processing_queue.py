"""Small durable file-backed job queue used while SQLite is deferred."""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import uuid
from typing import Any


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _timestamp(value: dt.datetime) -> str:
    return value.isoformat()


class FileJobQueue:
    """Persist each job as JSON and move it atomically between state folders."""

    states = ("pending", "processing", "completed", "failed")

    def __init__(self, root: Path):
        self.root = Path(root)
        for state in self.states:
            (self.root / state).mkdir(parents=True, exist_ok=True)

    def _path(self, state: str, job_id: str) -> Path:
        return self.root / state / f"{job_id}.json"

    def _write(self, state: str, job: dict[str, Any]) -> None:
        target = self._path(state, job["id"])
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, target)

    def find(self, job_id: str) -> tuple[str, dict[str, Any]] | None:
        for state in self.states:
            path = self._path(state, job_id)
            if path.exists():
                return state, json.loads(path.read_text(encoding="utf-8"))
        return None

    def enqueue(self, kind: str, payload: dict[str, Any], job_id: str | None = None) -> dict[str, Any]:
        if job_id and self.find(job_id):
            return self.find(job_id)[1]
        job = {
            "id": job_id or str(uuid.uuid4()),
            "kind": kind,
            "payload": payload,
            "status": "pending",
            "attempts": 0,
            "createdAt": _timestamp(_now()),
            "availableAt": _timestamp(_now()),
        }
        self._write("pending", job)
        return job

    def claim(self, kind: str | None = None, exclude_ids: set[str] | None = None) -> dict[str, Any] | None:
        now = _now()
        for path in sorted((self.root / "pending").glob("*.json")):
            job = json.loads(path.read_text(encoding="utf-8"))
            if kind is not None and job.get("kind") != kind:
                continue
            if exclude_ids and job["id"] in exclude_ids:
                continue
            if dt.datetime.fromisoformat(job["availableAt"]) > now:
                continue
            job["status"] = "processing"
            job["attempts"] += 1
            job["processingAt"] = _timestamp(now)
            processing_path = self._path("processing", job["id"])
            os.replace(path, processing_path)
            processing_path.write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return job
        return None

    def _load_processing(self, job_id: str) -> dict[str, Any]:
        path = self._path("processing", job_id)
        if not path.exists():
            raise KeyError(f"processing job not found: {job_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def complete(self, job_id: str, result: dict[str, Any]) -> dict[str, Any]:
        job = self._load_processing(job_id)
        job.update({"status": "completed", "result": result, "completedAt": _timestamp(_now())})
        self._path("processing", job_id).unlink()
        self._write("completed", job)
        return job

    def fail(
        self,
        job_id: str,
        error: str,
        max_attempts: int = 3,
        retry_delay_seconds: int = 30,
    ) -> dict[str, Any]:
        job = self._load_processing(job_id)
        job["lastError"] = error
        if job["attempts"] >= max_attempts:
            job.update({"status": "failed", "failedAt": _timestamp(_now())})
            self._path("processing", job_id).unlink()
            self._write("failed", job)
            return job

        delay = retry_delay_seconds * (2 ** (job["attempts"] - 1))
        job.update({"status": "pending", "availableAt": _timestamp(_now() + dt.timedelta(seconds=delay))})
        self._path("processing", job_id).unlink()
        self._write("pending", job)
        return job
