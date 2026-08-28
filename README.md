# Jarvis Activity Journal

Local-first, cross-platform activity collection and journal generation. It captures structured activity metadata, optional focused-window text, and optional full-desktop screenshots. A configurable vision model converts representative screenshots into structured activity events; a configurable text model turns the day's events into a narrative journal. Both models can be local (LM Studio, Ollama, any OpenAI-compatible server) or a cloud API — chosen per stage via `config/settings.json`.

Pure Python throughout. Tested on Windows; Linux is supported via X11 (window title + idle time) with an honest gap on Wayland and on focused-content capture, documented below.

## Architecture

```text
Screenshot → vision model  → visual activity JSON   (Journal/raw/visual-DATE.jsonl)
All events → text model    → daily journal narrative (Journal/daily/DATE.md, "LLM narrative" section)
```

Everything that isn't a model call — capture, redaction, JSONL storage, deterministic Markdown, scheduling — is plain Python with no network access.

## Privacy model

- Journal data is written outside this repository by default; screenshots and raw activity files are gitignored.
- API keys are read from environment variables, never from committed config.
- Privacy settings support capture enablement, excluded applications/window titles, redaction-before-storage, retention, and raw-screenshot deletion after analysis. A manual private-mode flag (`config/private-mode.json`) pauses every collector instantly.
- Screenshot analysis and journal synthesis are opt-in and provider-neutral: point them at a local server or a cloud API. **Choosing a cloud provider sends screenshots and window/app text to that provider** — review its data-retention policy before switching `activeProvider` away from a local one. Nothing is sent anywhere by default.

Do not use this on a corporate device or with other people's conversations without authorization and policy review.

## Platform support

| Capability | Windows | Linux (X11) | Linux (Wayland) | macOS |
|---|---|---|---|---|
| Screenshot capture | yes (`mss`) | yes (`mss`) | yes (`mss`) | yes (`mss`) |
| Foreground window + idle time | yes (ctypes) | yes (`python-xlib`, `xprintidle`) | no — no standard cross-compositor API | best-effort (`pyobjc`/Quartz), untested |
| Focused-window text capture | yes (`pywinauto`/UI Automation) | not implemented (would need AT-SPI) | not implemented | not implemented |
| Automatic scheduling | yes (Task Scheduler) | yes (systemd --user timers) | yes (same as X11) | not implemented — run collectors manually or via your own launchd job |

Where a platform isn't supported, the collector logs one warning and returns cleanly rather than crashing the rest of the pipeline.

## Install

```bash
pip install -e ".[dev]"          # add [linux] on Linux, [windows] or [macos] as applicable
cp config/settings.example.json /path/to/Journal/config/settings.json
```

Edit `settings.json`: set `repositoryPath` to this repo's absolute path, `projectPaths` to the git repos you want evidence from, and review the `privacy` block before enabling capture. Every interval (`collectors.*.intervalSeconds`, `screenshotAnalyzer.intervalSeconds`, `hourlyBuild.intervalSeconds`, `dailySummary.time`) is config-driven — change the numbers, no code edits needed.

Register the scheduler for your platform:

```bash
python -m src.install --journal-root /path/to/Journal --config /path/to/Journal/config/settings.json
```

This registers one job per collector (Task Scheduler on Windows, systemd user timers on Linux) at the intervals from your config, plus a logon/startup pass. `python -m src.uninstall` reverses it.

On some Windows configurations, registering the logon-trigger startup task fails with "Access is denied" from a non-elevated shell (a Task Scheduler quirk specific to `LogonTrigger`) while every interval-based task registers fine. The installer reports this and continues rather than aborting — the recurring tasks alone start collecting within minutes of any logon regardless, so the startup task is a minor convenience, not a requirement. Run the installer from an elevated PowerShell if you want it registered too.

## Choosing a model provider

`config/settings.json` has a `providers` map — each entry is one named profile (`endpoint`, `model`, `apiKeyEnv`, optional `headers`). `screenshotAnalyzer.activeProvider` and `journalSynthesis.activeProvider` each pick a profile by name, independently — vision can stay local while synthesis uses a cloud model, or vice versa.

```json
"providers": {
  "local-vision": { "endpoint": "http://localhost:1234/v1/chat/completions", "model": "qwen2.5-vl", "apiKeyEnv": "VISION_API_KEY" },
  "cloud-text":   { "endpoint": "https://api.example.com/v1/chat/completions", "model": "some-model", "apiKeyEnv": "CLOUD_API_KEY" }
},
"screenshotAnalyzer": { "activeProvider": "local-vision" },
"journalSynthesis":   { "activeProvider": "cloud-text" }
```

Any OpenAI-compatible `POST /chat/completions` endpoint works — local (LM Studio, Ollama) or cloud. Set the provider's `apiKeyEnv` variable in your shell before a cloud provider will authenticate; local providers usually need none.

### Local LM Studio setup (Windows)

1. Download a vision-capable model (e.g. Qwen2.5-VL) in LM Studio and start its server on `http://localhost:1234`.
2. Find the model identifier with `lms ls --json` or `GET /v1/models`; put it in the matching `providers.*.model`.
3. Tune `visionService.contextLength`/`.parallel` to fit available VRAM — each parallel slot allocates its own KV cache at the full context length, so `parallel: 1` with a smaller `contextLength` (e.g. 4096) is the biggest lever on constrained hardware.
4. `scripts/windows/Start-VisionService.ps1` is an optional Windows-only helper that starts LM Studio's server and pre-loads the model at logon; `python -m src.install` does not require it, but registering it avoids paying model-load time on the first request. There is no equivalent script here for other local runtimes (Ollama, etc.) — start those normally per their own docs.

## Pipeline

```text
Every collectors.activity/content/screenshot.intervalSeconds (default 60s)
  |- window_activity.py  -> app+window metadata      -> Journal/raw/activity-DATE.jsonl
  |- active_content.py   -> focused-window text       -> Journal/raw/content-DATE.jsonl
  `- capture.py           -> full-desktop screenshot  -> Journal/screenshots/DATE/*.jpg
                              (skipped if perceptually identical to the previous frame)

Every collectors.projectEvidence.intervalSeconds (default 15 min)
  `- project_evidence.py -> git evidence for configured projects -> Journal/raw/activity-DATE.jsonl

Every screenshotAnalyzer.intervalSeconds (default 15 min)
  `- analyze_screenshots.py -> representative, deduped screenshots -> vision model
                               -> Journal/raw/visual-DATE.jsonl
                               (per-screenshot prompt picked from the app active at capture time)

Every hourlyBuild.intervalSeconds (default 1h)
  |- build_journals.py     -> deterministic hourly + weekly Markdown (no model call)
  |- build_llm_context.py  -> Journal/llm-context/latest.md (raw evidence feed for an LLM assistant)
  `- synthesize_journal.py -> text model -> Journal/daily/DATE.md ("LLM narrative" section)

At logon
  `- run_now.py -> one collection pass immediately

dailySummary.time (default 23:55)
  `- daily_summary.py -> retention cleanup, final vision pass, deterministic daily scaffold, narrative refresh
```

On constrained hardware a single vision-analysis run over a dozen screenshots can take many minutes; every scheduled job is registered with an execution time limit and "ignore new instance" so a slow run blocks its own next trigger instead of stacking concurrent model loads.

## Verification

```bash
python -m src.run_now --journal-root /path/to/Journal --config /path/to/Journal/config/settings.json
python -m src.daily_summary --journal-root /path/to/Journal --config /path/to/Journal/config/settings.json
python -m src.doctor --journal-root /path/to/Journal
```

Successful screenshot analysis creates `Journal/raw/visual-YYYY-MM-DD.jsonl` entries and increases "Vision-analyzed screenshots" in `Journal/llm-context/latest.md`. An HTTP error from the vision/synthesis stage means the configured provider is unreachable or misconfigured — check its status file (`Journal/raw/visual-DATE.status.json`, `Journal/raw/journal-DATE.status.json`) for the exact error.

## Repository layout

- `src/capture.py`, `window_activity.py`, `active_content.py`, `project_evidence.py` — collectors, one process per run
- `src/analyze_screenshots.py`, `synthesize_journal.py`, `model_client.py` — vision/text model calls, provider-neutral
- `src/build_journals.py`, `build_llm_context.py`, `daily_summary.py`, `run_hourly.py`, `run_now.py` — deterministic rendering and orchestration (no model calls except where noted)
- `src/journalize.py`, `sessionize.py` — deterministic Markdown rendering and activity-session classification
- `src/heartbeat.py`, `privacy_state.py`, `retention.py` — shared infrastructure
- `src/install.py`, `uninstall.py` — cross-platform scheduler registration
- `src/doctor.py`, `dashboard.py` — diagnostics and a localhost status endpoint
- `config/settings.example.json` — full configuration template; copy to your journal root
- `config/prompts.json` — per-app-context vision prompts
- `scripts/windows/Start-VisionService.ps1` — optional Windows-only LM Studio pre-loader
- `LICENSE` — MIT license
