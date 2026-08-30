# Jarvis Activity Journal

Local-first, cross-platform activity collection and journal generation. It captures structured activity metadata, optional focused-window text, and optional full-desktop screenshots. A configurable vision model converts representative screenshots into structured activity events; a configurable text model turns the day's events into a narrative journal. Both models can be local (LM Studio, Ollama, any OpenAI-compatible server) or a cloud API — chosen per stage via `config/settings.json`.

Pure Python throughout. Tested on Windows; Linux is supported via X11 (window title + idle time) with an honest gap on Wayland and on focused-content capture, documented below.

## Architecture

```text
Screenshot → vision model  → visual activity JSON        (Journal/raw/visual-DATE.jsonl)
All events → text model    → daily journal narrative      (Journal/daily/DATE.md, "LLM narrative" section)
All events → text model    → hourly/weekly journal narrative (Journal/hourly/DATE/HH.md, Journal/weekly/YYYY-Www.md)
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

Edit `settings.json`: set `repositoryPath` to this repo's absolute path, `projectPaths` to the git repos you want evidence from, and review the `privacy` block before enabling capture. Every interval (`collectors.*.intervalSeconds`, `screenshotAnalyzer.intervalSeconds`, `hourlyBuild.intervalSeconds`, `dailySummary.time`) is config-driven — change the numbers, no code edits needed. And set `vaultRoot` to your Obsidian vault's absolute path if you want the daily journal mirrored there (leave unset to disable). When `vaultRoot` is set, you can optionally enable `entityUpdates.enabled` to automatically extract noteworthy person and project mentions from the daily narrative and append them as companion notes (e.g. `<Name> - Activity Mentions.md` / `<Name> - Activity Log.md`) beside — never inside — your curated vault notes; this is a separate opt-in that defaults to off, uses the local text provider by default, and never modifies existing curated notes.

Register the scheduler for your platform:

```bash
python -m src.orchestration.install --journal-root /path/to/Journal --config /path/to/Journal/config/settings.json
```

This registers one job per collector (Task Scheduler on Windows, systemd user timers on Linux) at the intervals from your config, plus a logon-trigger startup pass and — where `lms` is on PATH — a logon-trigger vision-service pre-loader. `python -m src.orchestration.uninstall` reverses it.

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

Any OpenAI-compatible `POST /chat/completions` endpoint works — local (LM Studio, Ollama) or cloud. Set the provider's `apiKeyEnv` variable in your shell before a cloud provider will authenticate; local providers usually need none. A provider can also set `"proxy": "http://host:port"` — every request to that provider is routed through it (`urllib`'s `ProxyHandler`); leave it unset to connect directly. Use this for any provider whose region restricts your network — see the OFAC note below.

`apiKeyEnv` can also be a list of env var names instead of one — `"apiKeyEnv": ["GROQ_API_KEY", "GROQ_API_KEY_2", "GROQ_API_KEY_3"]` — for round-robin key rotation against a single provider, e.g. to stack several free-tier accounts' rate limits. Only the ones actually set are used; unset names are silently skipped.

**On Groq specifically, rate limits are per-organization** — every project and every key you create *within the same account* draws from one shared pool, so extra keys from one account add nothing. Each key in the list has to come from a genuinely separate account (separate email signup) to actually add budget.

`model` can similarly become `"models": ["model-a", "model-b"]` to rotate across models on the same provider — useful because Groq's token-per-minute limits are enforced per model, not just per organization, so alternating models gives real extra headroom on top of key rotation, even within one account.

Both dimensions combine: with N keys and M models, a 429 tries every (key, model) combination in turn — no sleep between them — before cycling back to the first pair and only then backing off. A full pass through every combination has to fail before it waits at all.

Set the API key with `setx VARNAME "key"`, not `$env:VARNAME = "key"` — `setx` persists it to the Windows user environment so scheduled tasks (which run non-interactively) can see it; a session-only `$env:` assignment won't be visible to them.

### Researched free-tier cloud providers (as of 2026-08-28)

`config/settings.example.json` ships these profiles pre-defined but **inactive** (`activeProvider` still points at `local-*`) — switching to one is a one-line config edit, never automatic.

| Profile | Provider | Model | Free-tier ceiling | Card required | Notes |
|---|---|---|---|---|---|
| `cloud-vision-gemini` | Google Gemini | `gemini-2.5-flash-lite` | ~1,000 req/day | No | Free-tier prompts are used to improve Google's models |
| `cloud-vision-groq` | Groq | `meta-llama/llama-4-scout-17b-16e-instruct` | ~1,000 req/day | No | |
| `cloud-vision-mistral` | Mistral La Plateforme | `ministral-3-8b-25-12` | ~2 req/min (thin for a 12-image batch) | No | Free-tier prompts may be used for training |
| `cloud-text-groq` | Groq | `openai/gpt-oss-120b` | ~1,000 req/day, structured JSON output support | No | |
| `cloud-text-gemini` | Google Gemini | `gemini-2.5-flash` | ~250-1,500 req/day | No | |

All comfortably clear this pipeline's volume (dozens to a few hundred calls/day). None require a credit card for the free tier. GitHub Models (retired July 2026), Cerebras and DeepSeek (both now require a card or are trial-only), Together AI, and HuggingFace Inference were researched and ruled out.

**If you're accessing these from Iran (or any OFAC-sanctioned jurisdiction): Google, Groq, Cloudflare, OpenRouter, and GitHub are all US-domiciled and explicitly restrict access under US export-control law — Google's own terms name Iran directly.** Route traffic through a proxy, or prefer Mistral (EU-domiciled, not bound by the same comprehensive embargo, though EU sectoral sanctions still apply) if you need an option that's more likely to work unproxied. This isn't a pipeline bug if a cloud provider silently fails from a restricted IP — it's the provider enforcing sanctions compliance.

### Local LM Studio setup (Windows)

1. Download a vision-capable model (e.g. Qwen2.5-VL) in LM Studio and start its server on `http://localhost:1234`.
2. Find the model identifier with `lms ls --json` or `GET /v1/models`; put it in the matching `providers.*.model`.
3. Tune `visionService.contextLength`/`.parallel` to fit available VRAM — each parallel slot allocates its own KV cache at the full context length, so `parallel: 1` with a smaller `contextLength` (e.g. 4096) is the biggest lever on constrained hardware.
4. `src/orchestration/start_vision_service.py` starts LM Studio's server and pre-loads the model at logon — `python -m src.orchestration.install` registers it automatically wherever `lms` (LM Studio's own CLI, cross-platform) is on PATH, skipping silently otherwise. If you use a different local runtime (Ollama, etc.) instead of LM Studio, start it normally per its own docs — there's no equivalent for other runtimes.

## Pipeline

```text
Every collectors.activity/content/screenshot.intervalSeconds (default 60s)
  |- collectors/window_activity.py  -> app+window metadata      -> Journal/raw/activity-DATE.jsonl
  |- collectors/active_content.py   -> focused-window text       -> Journal/raw/content-DATE.jsonl
  `- collectors/capture.py           -> full-desktop screenshot  -> Journal/screenshots/DATE/*.jpg
                                        (skipped if perceptually identical to the previous frame)

Every collectors.projectEvidence.intervalSeconds (default 15 min)
  `- collectors/project_evidence.py -> git evidence for configured projects -> Journal/raw/activity-DATE.jsonl

Every screenshotAnalyzer.intervalSeconds (default 15 min)
  `- analysis/analyze_screenshots.py -> deduped screenshots enqueued to Journal/queue/
                                        -> up to maxScreenshotsPerRun drained per run -> vision model
                                        -> Journal/raw/visual-DATE.jsonl
                                        (per-screenshot prompt picked from the app active at capture time)

Every hourlyBuild.intervalSeconds (default 1h)
  |- analysis/synthesize_period.py  -> text model -> Journal/hourly/DATE/HH.md and Journal/weekly/YYYY-Www.md
  |                                    (an hour with zero evidence — no events, no screenshot — is skipped, not synthesized;
  |                                    a failed call is queued in Journal/queue-period/ and retried on the next run)
  |- analysis/build_llm_context.py  -> Journal/llm-context/latest.md (raw evidence feed for an LLM assistant)
  `- analysis/synthesize_journal.py -> text model -> Journal/daily/DATE.md ("LLM narrative" section)

At logon
  |- orchestration/run_now.py             -> one collection pass immediately
  `- orchestration/start_vision_service.py -> starts and pre-loads the local model, where configured

dailySummary.time (default 23:55)
  `- orchestration/daily_summary.py -> retention cleanup, final vision pass, deterministic daily scaffold, narrative refresh,
                                        optional extraction of person/project mentions to companion notes (when vaultRoot and entityUpdates.enabled are set)
```

On constrained hardware a single vision-analysis run over a dozen screenshots can take many minutes; every scheduled job is registered with an execution time limit and "ignore new instance" so a slow run blocks its own next trigger instead of stacking concurrent model loads.

### Durable retry queue

Every captured screenshot is enqueued once (`Journal/queue/pending/`, a durable file-backed job per screenshot — `src/infra/processing_queue.py`) before it's ever sent to a model. If a vision call fails — no internet, provider down, rate-limited, proxy unreachable — the job goes back to `pending` with exponential backoff (`journalSynthesis`'s and `screenshotAnalyzer`'s config: `maxAttempts`, `retryDelaySeconds`) instead of being dropped; the screenshot data isn't lost, it just waits for a later run when connectivity is back. After `maxAttempts` failures a job moves to `Journal/queue/failed/` (dead letter) rather than retrying forever. `python -m src.ops.dashboard` exposes queue depth per state. Hourly and weekly narrative synthesis use the same pattern against a separate queue root, `Journal/queue-period/` — a failed LLM call is queued and retried on the next hourly run rather than lost.

## Verification

```bash
python -m src.orchestration.run_now --journal-root /path/to/Journal --config /path/to/Journal/config/settings.json
python -m src.orchestration.daily_summary --journal-root /path/to/Journal --config /path/to/Journal/config/settings.json
python -m src.ops.doctor --journal-root /path/to/Journal
```

Successful screenshot analysis creates `Journal/raw/visual-YYYY-MM-DD.jsonl` entries and increases "Vision-analyzed screenshots" in `Journal/llm-context/latest.md`. An HTTP error from the vision/synthesis stage means the configured provider is unreachable or misconfigured — check its status file (`Journal/raw/visual-DATE.status.json`, `Journal/raw/journal-DATE.status.json`) for the exact error.

## Repository layout

Every module here is invoked as `python -m src.<subpackage>.<name>`; nothing runs as a bare script.

```text
src/
  collectors/       one process per run, each captures one thing
    window_activity.py    app + window metadata, cross-platform (Windows/X11/Darwin backends)
    active_content.py     focused-window text where the platform's accessibility API supports it
    capture.py             full-desktop screenshot, deduped at capture time
    project_evidence.py    git evidence for configured project paths
  analysis/         vision/text model calls and deterministic rendering
    analyze_screenshots.py  screenshots -> vision model -> visual-DATE.jsonl
    synthesize_journal.py   events -> text model -> daily narrative
    synthesize_period.py    events -> text model -> hourly + weekly narrative, queue-backed retry
    sessionize.py            activity-session classification (no model call)
    build_llm_context.py     llm-context/latest.md, raw evidence for an LLM assistant
    ocr.py, screenshot_fingerprint.py   OCR and perceptual-hash helpers
  providers/         model_client.py — provider-neutral OpenAI-compatible client,
                     key/model rotation, proxy support
  infra/             shared, dependency-free building blocks
    heartbeat.py, privacy_state.py, retention.py, processing_queue.py
    privacy.py, privacy_config.py     redaction/exclusion + config validation
  orchestration/      wires the above together on a schedule
    run_now.py, run_hourly.py, daily_summary.py, start_vision_service.py
    install.py, uninstall.py           cross-platform scheduler registration
  ops/                doctor.py, dashboard.py — diagnostics and a localhost status endpoint

config/
  settings.example.json   full configuration template; copy to your journal root
  prompts.json              per-app-context vision prompts

rules/                    durable project rules (see rules/README.md)
tests/                    one test module per src module, same flat layout
LICENSE                    MIT license
```
