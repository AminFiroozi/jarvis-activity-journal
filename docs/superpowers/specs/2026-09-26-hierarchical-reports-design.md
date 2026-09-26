# Hierarchical Screen-Aware Reports — Design

**Goal:** every screenshot's vision analysis is saved as its own Markdown file describing what the model saw on screen. The hourly report compacts that hour's screenshot files, the daily report compacts that day's hourly reports, and the weekly report compacts that week's daily reports. All levels share one format and differ only in depth of detail.

**Non-goals:** changing collectors, the screenshot queue, retention, or the Obsidian vault entity logic; adding new LLM providers; transcribing chat text verbatim (existing rules still hold).

## Current state

- `analyze_screenshots.py` calls the vision model per screenshot and appends `{timestamp, source: "screenshot-vision", screenshot, analysis}` to `raw/visual-DATE.jsonl`. `analysis` has `summary`, `applications`, `projects`, `activity_type`, `observations`, `confidence`. No per-screenshot file exists.
- `narrative.compact_event` cuts a screen event to `summary[:200]`, `apps` and `activity_type`, dropping `observations` and `projects`. The narrative models never see the on-screen detail.
- Hourly and weekly (`synthesize_period.py`) and daily (`synthesize_journal.py`) each read raw events with separate prompts and separate renderers. Daily has Accomplishments; hourly and weekly do not; hourly omits the confidence line.
- `daily/DATE.md` = deterministic scaffold (`daily_summary.render_daily_scaffold`) + a `## LLM narrative` section appended by `synthesize_journal.upsert_narrative`. `sync_vault.py` mirrors from the `## LLM narrative` marker onward, so that marker must be kept.
- `run_hourly.py` runs: hourly synthesis, weekly synthesis, `build_llm_context`, daily synthesis. `daily_summary.py` (23:55) also runs the vision analysis and daily synthesis.
- Failed period synthesis is queued in `queue-period/` via `FileJobQueue`.

## Decisions (confirmed with Amin)

- Per-screenshot Markdown is rendered by plain code from the vision JSON — no second LLM call. The vision prompt is enriched with a `screen_details` field.
- Hourly input = that hour's screenshot Markdown files **plus** a compact activity/window summary (covers hours with no analysed screenshot). Daily reads only that day's hourly files. Weekly reads only that week's daily narratives. Neither reads raw events.
- One shared skeleton: summary paragraph, `### On screen`, `### Timeline`, `### Patterns`, `### Next actions`. Accomplishments and Blockers are dropped from daily so all three match. There is no confidence value anywhere in this format.
- Depth: hourly lists every distinct screen; daily groups by task/app; weekly keeps the few notable themes.
- **Every screenshot gets its own Markdown file.** Near-identical screenshots that dedupe currently skips get a file too: it copies the matched screen's on-screen details, marked "unchanged since HH:MM:SS", with no extra LLM call.
- **Confidence is removed** wherever a model reports it: vision output and prompts, the report line, and entity notes. Entity ranking and dedupe use evidence count instead, and `minConfidence` is dropped. Internal computed scores that are not model opinions (session classification in `sessionize.py`, OCR box confidence in `ocr.py`) stay.

## Architecture

```
analyze_screenshots ──► raw/visual-DATE.jsonl        (unchanged)
                    └─► screens/DATE/HH/HH-MM-SS.md  (NEW, rendered from analysis)
synthesize_period hourly  reads screens/DATE/HH/*.md + activity summary ──► hourly/DATE/HH.md
synthesize_period daily   reads hourly/DATE/*.md                        ──► daily/DATE.md ("## LLM narrative")
synthesize_period weekly  reads daily/DATE.md narratives of the week    ──► weekly/YYYY-Www.md
```

`synthesize_journal.py` is folded into `synthesize_period.py` as `--period daily`; `run_hourly.py` and `daily_summary.py` call it that way. The old separate daily prompt and `upsert_narrative` are removed.

### Components

- **`src/analysis/screen_markdown.py` (new):** `render_screen_markdown(analysis, screenshot_path, timestamp) -> str` and `write_screen_markdown(journal_root, result)`. Layout: `# Screen — DATE HH:MM:SS`, summary line, `### On screen` (screen_details then observations), then `Apps:`, `Projects:`, `Activity:`. A duplicate screenshot renders the same body with an `Unchanged since HH:MM:SS` line instead of a fresh analysis. Local time only; no IDs, no ISO timestamps, no backticked evidence (rule: human-readable-reports). Called from `analyze_screenshots.main` for each successful result and for each screenshot dedupe dropped. Idempotent: the file is overwritten with the same content.
- **`src/analysis/report_levels.py` (new):** the depth table (`hourly`, `daily`, `weekly`) — per level: prompt depth instruction, section item limits, input character budget. Provides `build_prompt(level)` used by all three levels so the JSON shape is identical: `{summary, on_screen[], timeline[{time, activity}], patterns[], next_actions[]}`.
- **`src/analysis/report_render.py` (new):** `render_report(title, narrative)` — the single renderer for the shared format. Replaces `render_period_document` and `upsert_narrative`. Daily keeps the deterministic scaffold above and appends `## LLM narrative` + this output, so `sync_vault` still works.
- **`src/analysis/synthesize_period.py` (modified):** `--period hourly|daily|weekly`. Input gatherers: `gather_hour(journal, date, hour)` (screen MDs + compact activity summary), `gather_day(journal, date)` (hourly MDs), `gather_week(journal, date)` (the `## LLM narrative` part of each daily file, skipping the scaffold). Shared `call_model`.
- **`src/analysis/screenshot_fingerprint.py` (modified):** `deduplicate_images` also returns which kept screenshot each dropped one matched (`{dropped: kept}`), so `analyze_screenshots` can write its "unchanged" file. The existing list-returning behaviour is kept for current callers.
- **Confidence removal (modified):** `config/prompts.json` (`base.output.confidence`), `analyze_screenshots.py` prompt ("lower confidence" line), `entity_facts.py` (schema and validation), `sync_entities.py` (`render_entry` source line, `minConfidence` filter, ranking by evidence count), `config/settings.example.json` (`minConfidence`), and the docs/spec mentions.
- **`src/analysis/narrative.py` (modified):** `compact_event` keeps `observations` and `projects` for screen events so the activity summary can still be built; the activity summary uses only window and session data.
- **`config/prompts.json` (modified):** add `screen_details` to `base.output` — "visible window/tab titles, panel or dashboard names, file, ticket and page names, terminal commands, chat topic and correspondent". Messaging context keeps the no-verbatim-text rule.

### Freshness and rebuild

- Each report file carries a hidden source line at the end: `<!-- sources: N files, newest mtime T -->`. On each run a level rebuilds only if N or T changed (new screenshots analysed, an hour rebuilt).
- Order per hourly run: hourly for the current and previous hour, then daily for today, then weekly for the current week. Queue backfill after a vision outage rebuilds affected hours on the next run because their source count changed.
- A day or week built from partial data states the coverage in its summary ("covers 14 of 24 hours").

## Failure handling

- Model JSON that fails to parse gets one retry with a "return only valid JSON" nudge; a second failure goes to `queue-period/` via the existing `FileJobQueue` retry path. Fixes the current `Expecting ',' delimiter` failure.
- An hour with no screenshot MDs and no activity events produces no file and no model call. A day with no hourly files, or a week with no daily files, likewise.
- The proxy and provider config fixes made earlier (live `settings.json`) are unchanged; `settings.example.json` and the README get a `proxy` example.

## Migration

- Existing `raw/visual-*.jsonl` entries are backfilled into `screens/` by a one-shot `python -m src.analysis.screen_markdown --journal-root … --backfill`, so already-analysed history participates. The dead-lettered vision jobs from the Groq outage (`queue/failed/`, from the 403 and retired-model errors) are moved back to `pending` once so those screenshots get analysed; a small `--requeue-failed` option handles this.
- Existing hourly, daily and weekly files are regenerated by the normal freshness rule on the next run (the source line is absent, so they rebuild once).

## Testing

Temp directories, no network, extending existing suites where they exist:

- `tests/test_screen_markdown.py` (new): rendering shape, human-readable-report rule (no ISO timestamps, no IDs), idempotent overwrite, backfill from jsonl, a duplicate screenshot gets a file marked unchanged, no confidence anywhere.
- `tests/test_synthesize_period.py`: hour gathering (hour filter, screen MDs + activity summary), day gathering from hourly MDs, week gathering that strips the scaffold, freshness skip, zero-input skip, JSON retry then queue.
- `tests/test_report_render.py` (new): identical section skeleton across all three levels; daily keeps `## LLM narrative` marker (with `tests/test_sync_vault.py`).
- `tests/test_run_hourly.py`, `tests/test_daily_summary.py`: updated step lists.
- `tests/test_narrative.py`, `tests/test_vision_prompts.py`, `tests/test_screenshot_fingerprint.py`: updated for the compact-event change, `screen_details`, and the dedupe mapping.
- `tests/test_entity_facts.py`, `tests/test_sync_entities.py`: confidence assertions replaced by evidence-count ranking; `tests/test_analyze_screenshots_queue.py`: mocked vision results no longer carry confidence.
- Deleted along with the code they cover: `tests/test_synthesize_journal.py`.

## Rules

`rules/hourly-weekly-narrative-format.md` is updated to describe the chain and the shared format with the On screen section — draft shown to Amin for approval before it is written.

## Out of scope / risks

- One extra field in the vision output makes each vision call slightly longer; the 262-item backlog drains a little slower.
- Weekly quality depends on daily narratives; a bad daily propagates. Mitigated by the retry, not by fallback to raw events (chain is strict by design).
