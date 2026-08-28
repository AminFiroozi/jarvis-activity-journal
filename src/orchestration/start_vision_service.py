"""Start a local model server and pre-load the configured vision model, if one is configured.

Cross-platform: shells out to LM Studio's `lms` CLI, which ships identically for
Windows, Linux, and macOS. Skips silently (logged, not an error) if `lms` isn't
on PATH — expected when the configured provider is cloud-only, or a different
local runtime is used.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import shutil
import subprocess
import sys


def _subprocess_kwargs() -> dict:
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def _log(log_path: pathlib.Path, message: str) -> None:
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"[{dt.datetime.now(dt.timezone.utc).isoformat()}] {message}\n")


def _run(args: list[str], log_path: pathlib.Path) -> str:
    result = subprocess.run(args, capture_output=True, text=True, **_subprocess_kwargs())
    _log(log_path, f"$ {' '.join(args)}\n{result.stdout}{result.stderr}".rstrip())
    return result.stdout


def find_model_key(models_json: str, pattern: str) -> str | None:
    try:
        models = json.loads(models_json)
    except json.JSONDecodeError:
        return None
    for model in models:
        if not isinstance(model, dict):
            continue
        if pattern in json.dumps(model):
            return model.get("modelKey") or model.get("key")
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal-root", required=True, type=pathlib.Path)
    parser.add_argument("--config", required=True, type=pathlib.Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    vision_service = config.get("visionService") or {}
    if not vision_service.get("enabled"):
        return 0

    log_path = args.journal_root / "raw" / "vision-service.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    lms = shutil.which("lms")
    if not lms:
        _log(log_path, "lms CLI not found on PATH; skipping local vision service startup")
        return 0

    _log(log_path, "Starting LM Studio server")
    _run([lms, "server", "start"], log_path)

    if not vision_service.get("loadOnLogon"):
        return 0

    models_json = _run([lms, "ls", "--json"], log_path)
    pattern = vision_service.get("modelPattern", "")
    model_key = find_model_key(models_json, pattern)
    if not model_key:
        _log(log_path, f"Vision model not found for pattern {pattern!r}")
        return 0

    context_length = int(vision_service.get("contextLength", 4096))
    parallel = int(vision_service.get("parallel", 1))
    gpu = vision_service.get("gpu", "auto")
    gpu_args = ["--gpu", gpu] if gpu and gpu != "auto" else []
    _log(log_path, f"Loading vision model {model_key} (context={context_length}, parallel={parallel}, gpu={gpu})")
    _run([lms, "load", model_key, *gpu_args, "--context-length", str(context_length), "--parallel", str(parallel), "-y"], log_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
