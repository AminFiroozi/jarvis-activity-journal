# Jarvis Activity Journal

Local-first activity collection and journal generation for Windows. It captures structured activity metadata, optional focused-window text, and optional full-desktop screenshots. A configurable vision analyzer converts representative screenshots into structured activity events for an LLM-readable journal.

## Privacy model

- Journal data is written outside this repository by default.
- Screenshots and raw activity files are ignored by Git.
- API keys are read from environment variables and never from committed files.
- Screenshot analysis is opt-in through a local configuration file.
- The analyzer sends screenshots only to the endpoint you configure.

Do not use this on a corporate device or with other people's conversations without authorization and policy review.

## Screenshot analysis

The analyzer expects an OpenAI-compatible `POST /chat/completions` endpoint that accepts image input. It works with local or remote providers.

```powershell
$env:VISION_API_KEY = 'your-key'
python .\src\analyze_screenshots.py --journal-root D:\JARVIS\Journal --date 2026-08-23 --endpoint https://example.invalid/v1/chat/completions --model vision-model
```

For a local provider, use an endpoint such as `http://localhost:11434/v1/chat/completions` and configure its vision-capable model. The analyzer selects representative screenshots, asks for structured JSON, and writes `visual-YYYY-MM-DD.jsonl` into the journal's raw folder.

## Repository layout

- `src/analyze_screenshots.py` — provider-neutral screenshot analyzer
- `config/analyzer.example.json` — safe configuration template
- `scripts/Analyze-Screenshots.ps1` — Windows wrapper
- `LICENSE` — MIT license
