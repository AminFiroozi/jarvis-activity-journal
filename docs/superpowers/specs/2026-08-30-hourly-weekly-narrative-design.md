# Hourly/Weekly Narrative Format — Design

**Goal:** replace the deterministic session+evidence-dump renderer for hourly and weekly journals with the same LLM-narrative style `daily/<date>.md` already uses (summary paragraph, `### Timeline`, `### Patterns`, `### Next actions`, `_LLM confidence: N_`), per `rules/hourly-weekly-narrative-format.md`. Hourly stays fine-grained/detailed; weekly stays general/summary-level.

**Non-goals:** changing daily's own format or synthesis logic (already correct, untouched); changing `project_evidence.py`'s or any collector's granularity; adding a scaffold/evidence-dump fallback under the narrative (the rule is explicit: "The narrative replaces the evidence list entirely").

## Current state

- `src/analysis/build_journals.py` + `src/analysis/journalize.py` render hourly/weekly as a deterministic session table + evidence dump (`render_journal`). Confirmed dead-code-adjacent: `journalize.write_journal_documents` has zero callers outside its own test file; `build_journals.py` is the only real caller of `render_journal`, invoked solely from `run_hourly.py`.
- `run_hourly.py` runs three subprocess steps every hour: `build_journals` (deterministic), `build_llm_context`, `synthesize_journal` (refreshes the *daily* LLM narrative only — hourly/weekly get no LLM treatment today).
- `src/analysis/narrative.py` (added by the vault-entity-updates feature, already on `develop`) holds shared evidence primitives: `local_time`, `event_stamp`, `truncate`, `compact_event`, `compact_session`, `parse_model_json`, `read_events(journal_root, date, compact=, limit=)`, `fit_evidence(sessions, recent, max_chars)`. `read_events` only supports one date and no hour-filtering — insufficient for weekly's multi-day span or hourly's within-day slice.
- `src/infra/processing_queue.py`'s `FileJobQueue` (states: pending/processing/completed/failed, exponential backoff via `fail(job_id, error, max_attempts, retry_delay_seconds)`) is already used by `analyze_screenshots.py` for vision-call retries — the same pattern applies here for LLM-call failures.

## Decisions (confirmed with Amin)

- Narrative-only format, matching daily's exact section shape (Timeline/Patterns/Next actions — no Accomplishments/Blockers, per the rule's own wording), for both hourly and weekly.
- Weekly refreshes on the same hourly cadence as hourly itself (not once nightly) — simplest, no new scheduling infra, and the extra Groq calls are cheap.
- On synthesis failure (no network, no key, rate-limited), enqueue a retry job via the existing `FileJobQueue` rather than writing nothing or falling back to a scaffold — "queued so when llm is available it would work."
- `build_journals.py` and `journalize.py` are deleted outright (not kept as a fallback) — nothing calls them once this ships, and the project already has three prior instances of orphaned-module drift this session; better to remove than leave a fourth.
- `cloud-text-groq`'s config gains the same 3-key rotation `cloud-vision-groq` already has (`apiKeyEnv: [GROQ_API_KEY, GROQ_API_KEY_2, GROQ_API_KEY_3]`) — weekly-refreshing-hourly means up to ~48 extra Groq text calls/day on top of daily's 1, all sharing one key today with no rotation; stacking free-tier limits across 3 keys is the same mitigation already applied to vision.
- **Every hour that produced a screenshot must get a journal file**, even a sparse one. Real-data investigation this session found a raw-collection outage (machine asleep 15:01→01:26 the next day) that left `daily/2026-08-29.md` correctly reflecting only what was actually captured — the right behavior, since data that was never collected can't be synthesized from thin air. But the LLM-call-skip guard needed for a *genuinely* empty hour (mirroring the zero-evidence guard just added to the vault-entity-updates feature, avoiding a wasted/fabrication-prone LLM call on nothing) must not fire just because vision analysis hasn't caught up yet to a screenshot taken during that hour — Groq's vision stage is itself queue-and-retry, so a screenshot file can exist for an hour before its `visual-<date>.jsonl` entry does. The skip condition is therefore: no activity/content/visual JSONL events for that hour **AND** no screenshot file under `Journal/screenshots/<date>/` timestamped within that hour. If any of those exist, the hour is synthesized (even sparse), never silently skipped.

## Architecture

```
run_hourly.py (modified)
  ├─ src.analysis.synthesize_period --period hourly   (NEW, replaces build_journals)
  ├─ src.analysis.synthesize_period --period weekly   (NEW, replaces build_journals)
  ├─ src.analysis.build_llm_context                   (unchanged)
  └─ src.analysis.synthesize_journal                  (unchanged — still refreshes daily)
```

One new module, `src/analysis/synthesize_period.py`, mirrors `synthesize_journal.py`'s own shape (a single file doing evidence-gathering, the LLM call, and markdown writing) rather than the `entity_facts.py`/`sync_entities.py` split from the prior feature — that split existed specifically because of vault-write safety concerns (entity name resolution, curated-note protection) that don't apply here; this module only ever writes into `Journal/hourly/` and `Journal/weekly/`, files this pipeline already owns outright.

- `read_period_events(journal_root, dates, hour=None, compact=compact_event, limit=1000) -> dict` — new function in `synthesize_period.py` (not `narrative.py`, since it's period-synthesis-specific): loops the given `dates` list (one date for hourly, Monday-through-today for weekly), reads each date's three JSONL files exactly as `narrative.read_events` does, and — when `hour` is given — filters each raw event to that local hour (via `narrative.event_stamp` + parsing) before compacting. Returns the same `{"sessions": [...], "recent": [...]}` shape `narrative.read_events` produces, so `fit_evidence` and the render step work identically for both callers.
- `has_evidence_for_hour(journal_root, date, hour) -> bool` — new function, hourly-only (weekly never skips: a full week having zero evidence in every hour is itself unlikely, and even so `read_period_events` naturally returns empty lists the LLM prompt already handles via its own "nothing happened" framing). Returns `True` if `read_period_events`'s raw scan for that hour yields any event, **or** if any file under `journal_root / "screenshots" / date` has a filename timestamp (`screen-HH-MM-SS-*.jpg`) within `hour` — the second check exists specifically so a screenshot awaiting vision analysis still counts as evidence.
- `HOURLY_PROMPT` / `WEEKLY_PROMPT` — two system-prompt constants. Hourly's instructs fine-grained detail matching a single hour's evidence density; weekly's instructs a general, summary-level pass covering fewer, broader points across the week (explicitly *not* an hour-by-hour recap).
- `call_model(provider, evidence_dict, prompt, max_chars=6000) -> dict` — same shape as `synthesize_journal.call_model`, parameterized on which prompt to use.
- `render_period_document(title, narrative) -> str` — builds the file fresh each run (title, summary paragraph, `### Timeline`, `### Patterns`, `### Next actions`, `_LLM confidence: N_`) — no upsert-into-existing-scaffold like daily's `upsert_narrative`, since hourly/weekly have no deterministic content left to preserve underneath; each run's output is a complete replacement of that hour's/week's file.
- Retry-on-failure: `synthesize_period.py --period hourly` first drains any due retry jobs from a `FileJobQueue` rooted at `Journal/queue-period/` (a new, dedicated queue root — kept separate from the existing vision-analysis queue at `Journal/queue/` so the two failure domains don't share state), keyed by job id `hourly:<date>:<hour>` / `weekly:<year>-W<week>`, then attempts the current period. On failure (network, rate limit, provider error), the current period's job is enqueued (idempotent by job id, so a retry doesn't duplicate) rather than the run failing outright.

## Data flow (hourly)

1. `run_hourly.py` invokes `python -m src.analysis.synthesize_period --period hourly --journal-root ... --config ... --date <today> --hour <current-local-hour>`.
2. `main()` drains due retries from `queue-period/` (kind="hourly"), attempting each due job's date/hour before the current one — each drained job also re-runs the `has_evidence_for_hour` check (evidence may have shown up since the job was queued, e.g. vision analysis finally caught up).
3. For the current hour: `has_evidence_for_hour(journal_root, date, hour)` — if `False`, write nothing and exit cleanly (genuinely empty hour, no LLM call, no queue entry — there's nothing to retry into existence). If `True`: `read_period_events(journal_root, [date], hour=current_hour)` → `fit_evidence` → `call_model(provider, evidence, HOURLY_PROMPT)` → `render_period_document(...)` → write to `Journal/hourly/<date>/<hour>.md`.
4. On success: `write_heartbeat(journal_root, "hourly-synthesis", "success", items_processed=1)`.
5. On failure (evidence existed but the LLM call/parse failed — network, rate limit, provider error): enqueue `{"date": date, "hour": hour}` with job id `hourly:<date>:<hour>`, `write_heartbeat(..., "failed", error_message=...)`, exit 0 (never break the hourly job's other steps — matches every other stage's non-fatal contract in this pipeline).

Weekly is identical in shape, called with `--period weekly` (no `--hour`), `dates` computed as Monday-through-today of the current ISO week, job id `weekly:<year>-W<week>`.

## Config

New provider-stage keys in `config/settings.example.json`, alongside `journalSynthesis`:

```json
"hourlySynthesis": {
  "enabled": true,
  "activeProvider": "cloud-text-groq"
},
"weeklySynthesis": {
  "enabled": true,
  "activeProvider": "cloud-text-groq"
}
```

`cloud-text-groq`'s `apiKeyEnv` changes from the single string `"GROQ_API_KEY"` to the list `["GROQ_API_KEY", "GROQ_API_KEY_2", "GROQ_API_KEY_3"]`, matching `cloud-vision-groq`'s existing rotation pattern — `resolve_provider`/`call_chat_completions` in `model_client.py` already handle a list `apiKeyEnv` with zero code changes needed.

## Testing

**Automated (temp dirs, no network):**
- `read_period_events`: single-date no-hour-filter matches `narrative.read_events`'s shape; hour-filter correctly excludes events outside the given local hour; multi-date span correctly merges events across days (weekly case) in chronological order.
- `has_evidence_for_hour`: `False` for an hour with no JSONL events and no screenshot files; `True` for an hour with only activity/content/visual JSONL events and no screenshots; `True` for an hour with only a screenshot file and zero JSONL events (the vision-analysis-lag case — this is the case that must not regress); filename-hour parsing correctly matches only the requested hour, not adjacent ones.
- `main()` (hourly): a genuinely empty hour writes no file, makes no LLM call, and enqueues nothing; an hour with only a pending screenshot proceeds to call the model.
- `render_period_document`: produces the exact daily-matching section shape (Timeline/Patterns/Next actions only, no Accomplishments/Blockers) for a given narrative dict; omits a section header when that key's list is empty (matching `upsert_narrative`'s existing behavior).
- `call_model`: mocked `call_chat_completions`, asserts the correct prompt constant is used per period and the response is parsed via `parse_model_json`.
- Retry queueing: a mocked synthesis failure enqueues a job with the correct kind/id; a subsequent run with a due retry job attempts it before the current period; a completed job is never re-attempted.
- `main()` never raises on any failure path (missing provider, network error, malformed response) — always exits 0, writes a failure heartbeat.
- `run_hourly.py`'s wiring: `build_journals` subprocess call is gone, replaced by two `synthesize_period` calls (`--period hourly`, `--period weekly`), mirroring the existing test idiom for subprocess-call assertions already used in `tests/test_daily_summary.py`.
- Deletion is safe: confirm (already verified above, re-confirm via `Grep` at plan-writing time) that removing `build_journals.py`/`journalize.py` leaves no other import site.

**Manual, requires a real model:**
- Run `synthesize_period.py --period hourly` and `--period weekly` against real recent journal data, inspect the rendered output for narrative quality and correct detail-level contrast (hourly granular, weekly general) — same manual-check pattern used for the prior two features' real-data verification steps.
