# Jarvis Activity Journal

Local-first activity collection and journal generation for Windows. It captures structured activity metadata, optional focused-window text, and optional full-desktop screenshots. A configurable vision analyzer converts representative screenshots into structured activity events for an LLM-readable journal.

## Architecture decision

Use one local Qwen-VL model for both semantic stages:

```text
Screenshot → Qwen-VL → visual activity JSON
All events → Qwen-VL → daily journal narrative
```

The model handles visual understanding and text synthesis. PowerShell handles collection, scheduling, redaction, JSONL storage, and Markdown output.

## Privacy model

- Journal data is written outside this repository by default.
- Screenshots and raw activity files are ignored by Git.
- API keys are read from environment variables and never from committed files.
- Screenshot analysis is opt-in through a local configuration file.
- The analyzer sends screenshots only to the endpoint you configure.

Do not use this on a corporate device or with other people's conversations without authorization and policy review.

## Screenshot analysis

The analyzer expects an OpenAI-compatible `POST /chat/completions` endpoint that accepts image input. It works with local or remote providers. The same endpoint/model can also be used for text-only journal synthesis.

For a remote provider, set its API key environment variable before running the analyzer:

```powershell
$env:VISION_API_KEY = 'your-key'
python .\src\analyze_screenshots.py --journal-root C:\Path\To\Journal --date 2026-08-23 --endpoint https://example.invalid/v1/chat/completions --model vision-model
```

For local LM Studio or Ollama endpoints, do **not** set `VISION_API_KEY`; local requests work without an API key. The `apiKeyEnv` setting is only an optional hook for remote providers.

For a local provider, use an endpoint such as `http://localhost:11434/v1/chat/completions` and configure its vision-capable model. The analyzer selects representative screenshots, asks for structured JSON, and writes `visual-YYYY-MM-DD.jsonl` into the journal's raw folder.

## Windows installation

1. Clone this repository.
2. Copy `config/settings.example.json` to the journal root's `config/settings.json`.
3. Set `projectPaths`, `screenshotAnalyzer.repositoryPath`, and the vision endpoint/model.
4. Run the installer from PowerShell:

```powershell
.\scripts\windows\Install-ActivityJournal.ps1
```

The installer creates hidden logon and repeating tasks for activity, focused content, project evidence, screenshots, summaries, and the vision service. It does not require a terminal window to remain open.

## LM Studio setup

1. Download a vision model such as Qwen2.5-VL 3B in LM Studio.
2. Start the LM Studio server on `http://localhost:1234`.
3. Find the model identifier with `lms ls --json` or `GET http://localhost:1234/v1/models`.
4. Set `screenshotAnalyzer.endpoint` to `http://localhost:1234/v1/chat/completions` and set `screenshotAnalyzer.model` to that identifier.
5. Set `visionService.modelPattern` to a stable substring of the same model identifier.
6. Run the installer again so the hidden vision-service logon task is registered.

The vision task starts LM Studio's server at interactive logon and attempts to load a matching model. Its log is `Journal/raw/vision-service.log`.

## Verification

```powershell
.\scripts\windows\Run-ActivityJournalNow.ps1
.\scripts\windows\New-ActivitySummary.ps1
Get-ScheduledTask | Where-Object TaskName -like 'Jarvis Activity Journal -*'
Get-Content Journal\llm-context\latest.md
```

Successful screenshot analysis creates `Journal/raw/visual-YYYY-MM-DD.jsonl` entries and increases `Vision-analyzed screenshots` in `Journal/llm-context/latest.md`. HTTP 503 means the configured vision server is unavailable; check the server, model, endpoint, and `vision-service.log`.

The journal-synthesis stage consumes the structured events and visual observations after screenshot analysis, then produces the daily narrative. Local model calls do not require an API key.

## Storage and privacy

Set `OLLAMA_MODELS` or LM Studio's My Models directory to a drive with enough space. Keep `Journal/` outside Git; the repository ignores screenshots, raw JSONL, and journal data. Maximum capture can record private messages, credentials visible on screen, and corporate information.

## Repository layout

- `src/analyze_screenshots.py` — provider-neutral screenshot analyzer
- `config/analyzer.example.json` — safe configuration template
- `config/settings.example.json` — Windows collector configuration template
- `scripts/Analyze-Screenshots.ps1` — Windows wrapper
- `scripts/windows/` — collector, content capture, screen capture, scheduler, and journal scripts
- `scripts/windows/Start-VisionService.ps1` — hidden logon startup for the local vision server/model
- `LICENSE` — MIT license
