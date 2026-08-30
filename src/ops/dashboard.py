"""Localhost-only status dashboard for the activity journal."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


def build_status(journal_root: Path) -> dict[str, Any]:
    root = Path(journal_root)
    health: list[dict[str, Any]] = []
    for path in sorted((root / "health").glob("*.json")) if (root / "health").exists() else []:
        try:
            health.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            health.append({"service": path.stem, "status": "invalid"})
    journals = sorted((root / "daily").glob("*.md"), reverse=True) if (root / "daily").exists() else []
    return {
        "health": health,
        "latestJournal": journals[0].name if journals else None,
        "queue": {
            state: len(list((root / "queue" / state).glob("*.json")))
            if (root / "queue" / state).exists()
            else 0
            for state in ("pending", "processing", "completed", "failed")
        },
        "queuePeriod": {
            state: len(list((root / "queue-period" / state).glob("*.json")))
            if (root / "queue-period" / state).exists()
            else 0
            for state in ("pending", "processing", "completed", "failed")
        },
    }


class DashboardHandler(BaseHTTPRequestHandler):
    journal_root: Path

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/api/status":
            self.send_error(404)
            return
        body = json.dumps(build_status(self.journal_root), ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_: object) -> None:
        return


def serve(journal_root: Path, port: int = 8765) -> None:
    handler = type("ConfiguredDashboardHandler", (DashboardHandler,), {"journal_root": Path(journal_root)})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.serve_forever()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal-root", required=True, type=Path)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    serve(args.journal_root, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
