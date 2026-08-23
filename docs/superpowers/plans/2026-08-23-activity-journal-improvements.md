# Jarvis Activity Journal Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evolve the Windows activity journal into a reliable, privacy-preserving, observable, and reusable local-first activity intelligence system.

**Architecture:** Keep PowerShell as the Windows collector and scheduler, introduce a Python/SQLite event store behind a stable event schema, and run vision/OCR/journal work through an explicit local queue. Generate deterministic evidence first, then use the local vision model for interpretation and narrative synthesis. Expose health, controls, and summaries through a small local dashboard.

**Tech Stack:** PowerShell 5.1+, Python 3, SQLite, JSONL import/export, OpenAI-compatible local vision endpoint, Windows Task Scheduler, Pester 3.4+, Python `unittest`.

---

## Delivery order

Implement phases in this order. Each phase must leave the repository runnable:

1. Privacy controls and redaction
2. Health diagnostics and failure monitoring
3. Event schema, durable processing queue, and deferred SQLite store
4. Screenshot deduplication and efficient vision processing
5. Session detection and multi-level journals
6. Local dashboard and operator controls
7. Packaging, installation, upgrade, and uninstall quality
8. Documentation, examples, CI, and public release hardening

Do not enable broader capture defaults until privacy controls and retention behavior are verified.

## Repository map

Create or modify these boundaries:

- `src/event_store.py` — SQLite schema, migrations, and event CRUD.
- `src/privacy.py` — redaction rules and sensitive-data detection.
- `src/processing_queue.py` — durable screenshot/model work queue.
- `src/sessionize.py` — event grouping and activity classification.
- `src/journalize.py` — hourly, daily, and weekly journal generation.
- `src/doctor.py` — machine and service diagnostics.
- `src/dashboard.py` — local read-only dashboard API and control endpoints.
- `scripts/windows/` — collection, startup, retention, install, uninstall, and operator commands.
- `config/settings.example.json` — documented configuration contract.
- `tests/` — Python and Pester regression tests for each boundary.
- `README.md` and `docs/` — user setup, privacy, operations, and architecture documentation.

---

## Phase 1: Privacy controls and redaction

### Task 1: Define privacy configuration

**Files:**
- Modify: `config/settings.example.json`
- Modify: `README.md`
- Create: `tests/test_privacy_config.py`

- [ ] Add these settings with safe defaults:

```json
{
  "privacy": {
    "captureEnabled": true,
    "privateModeHotkey": "Ctrl+Alt+Pause",
    "excludedApplications": [],
    "excludedWindowTitlePatterns": [],
    "redactBeforeStorage": true,
    "retentionDays": 14,
    "deleteRawScreenshotsAfterAnalysis": false
  }
}
```

- [ ] Test that missing privacy settings resolve to the safe defaults and invalid retention values are rejected.
- [ ] Document that capture may include private messages, credentials, tokens, and corporate data.
- [ ] Commit: `feat: define privacy controls and retention settings`.

### Task 2: Implement text and image redaction

**Files:**
- Create: `src/privacy.py`
- Create: `tests/test_privacy.py`
- Modify: `scripts/windows/Collect-ActiveContent.ps1`
- Modify: `src/analyze_screenshots.py`

- [ ] Write failing tests for redacting passwords, bearer tokens, API keys, email addresses when configured, and excluded applications.
- [ ] Implement `redact_text(text, rules) -> RedactionResult` returning redacted text plus matched rule names.
- [ ] Implement `is_excluded(application, window_title, config) -> bool`.
- [ ] For screenshots, apply a conservative redaction layer only to detected secret-like regions; preserve the original only when `deleteRawScreenshotsAfterAnalysis` is false.
- [ ] Store redaction metadata without storing the secret value.
- [ ] Commit: `feat: redact sensitive activity evidence`.

### Task 3: Add private mode and retention enforcement

**Files:**
- Create: `scripts/windows/Set-ActivityJournalPrivateMode.ps1`
- Modify: `scripts/windows/Collect-Activity.ps1`
- Modify: `scripts/windows/Capture-Screen.ps1`
- Modify: `scripts/windows/Invoke-RetentionCleanup.ps1`
- Create: `tests/PrivacyMode.Tests.ps1`

- [ ] Write a failing test for a private-mode marker that causes all collectors to skip capture while retaining a timestamped state file.
- [ ] Implement `Journal/config/private-mode.json` with `enabled`, `changedAt`, and `reason` fields.
- [ ] Make each collector exit cleanly when private mode is enabled.
- [ ] Make retention cleanup delete only files older than the configured retention period and report counts by category.
- [ ] Commit: `feat: add private mode and retention enforcement`.

---

## Phase 2: Health diagnostics and failure monitoring

### Task 4: Build the Doctor command

**Files:**
- Create: `src/doctor.py`
- Create: `scripts/windows/Doctor.ps1`
- Create: `tests/test_doctor.py`
- Modify: `README.md`

- [ ] Write tests for checks covering PowerShell, Python, Journal write access, disk space, scheduled tasks, screenshot dimensions, endpoint reachability, and model availability.
- [ ] Implement machine-readable JSON output and a human-readable table.
- [ ] Return exit code `0` only when all required checks pass; return `2` for warnings and `1` for failures.
- [ ] Add the command to the troubleshooting section.
- [ ] Commit: `feat: add activity journal diagnostics`.

### Task 5: Add structured service health

**Files:**
- Modify: `scripts/windows/Collect-Activity.ps1`
- Modify: `scripts/windows/Capture-Screen.ps1`
- Modify: `scripts/windows/Analyze-Screenshots.ps1`
- Modify: `scripts/windows/Synthesize-Journal.ps1`
- Create: `Journal/health/README.md`

- [ ] Make every worker write a heartbeat JSON file containing `service`, `startedAt`, `lastSuccessAt`, `lastErrorAt`, `lastError`, and `itemsProcessed`.
- [ ] Add stale-heartbeat detection to `Doctor.ps1`.
- [ ] Add bounded log rotation for `vision-service.log` and worker logs.
- [ ] Commit: `feat: add worker health and heartbeats`.

---

## Phase 3: Event schema, SQLite store, and durable queue

### Task 6: Define versioned event schema and SQLite store — DEFERRED

> Deferred temporarily by project decision. Keep JSONL as the current event store until SQLite is resumed. The queue in Task 8 must use a storage interface so it can move to SQLite later.

**Files:**
- Create: `docs/event-schema.md`
- Create: `src/event_store.py`
- Create: `tests/test_event_store.py`

- [ ] Define the canonical event fields:

```json
{
  "id": "uuid",
  "schemaVersion": 1,
  "observedAt": "2026-08-23T12:51:53+03:30",
  "source": "activity|content|visual|project|system",
  "application": "string",
  "project": "string|null",
  "kind": "string",
  "payload": {},
  "confidence": 0.0,
  "privacy": {"redacted": false, "excluded": false}
}
```

- [ ] Implement SQLite migrations for `events`, `screenshots`, `processing_jobs`, `sessions`, and `journal_documents`.
- [ ] Add idempotent insertion using event IDs and source timestamps.
- [ ] Add JSONL export so users can inspect and back up their data.
- [ ] Commit: `feat: add versioned SQLite event store`.

### Task 7: Import existing JSONL and switch reads to SQLite — DEFERRED

> Deferred temporarily by project decision. No existing JSONL consumers should be migrated to SQLite in the interim.

**Files:**
- Create: `src/import_jsonl.py`
- Modify: `scripts/windows/Collect-Activity.ps1`
- Modify: `scripts/windows/Collect-ActiveContent.ps1`
- Modify: `scripts/windows/Collect-ProjectEvidence.ps1`
- Modify: `scripts/windows/New-LLMContext.ps1`
- Create: `tests/test_import_jsonl.py`

- [ ] Write tests for importing valid records, skipping malformed lines with an error report, and running the import twice without duplicates.
- [ ] Import current `activity-*.jsonl`, `content-*.jsonl`, and `visual-*.jsonl` files before switching consumers.
- [ ] Preserve JSONL as an export/debug format while making SQLite the primary read path.
- [ ] Commit: `feat: migrate journal consumers to SQLite`.

### Task 8: Add durable processing queue without SQLite

**Files:**
- Create: `src/processing_queue.py`
- Modify: `src/analyze_screenshots.py`
- Modify: `src/synthesize_journal.py`
- Create: `tests/test_processing_queue.py`

- [ ] Write tests for enqueue, claim, retry, dead-letter, and successful completion.
- [ ] Implement jobs as JSON files under `Journal/queue/` with `pending`, `processing`, `completed`, and `failed` states, attempt counts, and exponential retry timestamps. Keep the queue API independent of this file layout so SQLite can replace it later.
- [ ] Ensure a crashed worker can reclaim jobs stuck in `processing`.
- [ ] Commit: `feat: add durable vision and journal job queue`.

---

## Phase 4: Efficient screenshot and vision processing

### Task 9: Deduplicate screenshots

**Files:**
- Modify: `scripts/windows/Capture-Screen.ps1`
- Create: `src/screenshot_fingerprint.py`
- Modify: `src/analyze_screenshots.py`
- Create: `tests/test_screenshot_fingerprint.py`

- [ ] Write tests for exact duplicates, near-identical screenshots, and meaningful screen changes.
- [ ] Compute SHA-256 plus a perceptual hash for each screenshot.
- [ ] Skip vision analysis when the perceptual distance is below the configured threshold.
- [ ] Store the reason for skipped analysis as an event.
- [ ] Commit: `feat: deduplicate unchanged screenshots`.

### Task 10: Add OCR and application-specific vision prompts

**Files:**
- Create: `src/ocr.py`
- Modify: `src/analyze_screenshots.py`
- Create: `config/prompts.json`
- Create: `tests/test_vision_prompts.py`

- [ ] Write tests proving that terminal, browser, IDE, Telegram, and unknown applications select different prompt instructions.
- [ ] Add OCR output with bounding boxes and confidence values.
- [ ] Keep prompts strict: return observed facts, avoid guessing user intent, and never return secrets.
- [ ] Commit: `feat: add OCR and contextual vision prompts`.

---

## Phase 5: Sessions and multi-level journals

### Task 11: Detect activity sessions

**Files:**
- Create: `src/sessionize.py`
- Create: `tests/test_sessionize.py`
- Modify: `src/event_store.py`

- [ ] Write tests for session start, idle gaps, application changes, project changes, and resumed sessions.
- [ ] Group adjacent events when the gap is under 15 minutes and the project/application context is compatible.
- [ ] Classify sessions as `coding`, `browsing`, `communication`, `terminal`, `meeting`, `idle`, or `mixed` using evidence only.
- [ ] Store sessions with start/end times, source event IDs, classification, and confidence.
- [ ] Commit: `feat: detect activity sessions`.

### Task 12: Generate hourly, daily, and weekly journals

**Files:**
- Create: `src/journalize.py`
- Create: `tests/test_journalize.py`
- Modify: `scripts/windows/New-ActivitySummary.ps1`
- Modify: `scripts/windows/New-LLMContext.ps1`

- [ ] Write tests for deterministic empty, partial, and populated journals.
- [ ] Generate:
  - `Journal/hourly/YYYY-MM-DD/HH.md`
  - `Journal/daily/YYYY-MM-DD.md`
  - `Journal/weekly/YYYY-Www.md`
- [ ] Include accomplishments, evidence links, blockers, decisions, next actions, time allocation, and confidence.
- [ ] Ensure rerunning a journal replaces its generated section instead of duplicating it.
- [ ] Commit: `feat: generate hierarchical activity journals`.

---

## Phase 6: Local dashboard and operator controls

### Task 13: Build the local dashboard API

**Files:**
- Create: `src/dashboard.py`
- Create: `tests/test_dashboard.py`
- Create: `scripts/windows/Start-Dashboard.ps1`
- Modify: `scripts/windows/Install-ActivityJournal.ps1`

- [ ] Write tests for read-only health, today’s sessions, recent events, and journal endpoints.
- [ ] Serve only on `127.0.0.1` with no external bind.
- [ ] Add endpoints for pause, resume, retention cleanup, and reprocess-job actions with local confirmation tokens.
- [ ] Commit: `feat: add local activity dashboard`.

### Task 14: Add pause/resume and visible capture status

**Files:**
- Modify: `scripts/windows/Set-ActivityJournalPrivateMode.ps1`
- Create: `scripts/windows/Get-ActivityJournalStatus.ps1`
- Modify: `README.md`
- Create: `tests/Status.Tests.ps1`

- [ ] Show capture state, last capture, last model result, queue depth, and current errors.
- [ ] Add a clear active/private indicator in the dashboard and status command.
- [ ] Commit: `feat: add operator controls and capture status`.

---

## Phase 7: Packaging and lifecycle quality

### Task 15: Harden install, upgrade, and uninstall

**Files:**
- Modify: `scripts/windows/Install-ActivityJournal.ps1`
- Modify: `scripts/windows/Uninstall-ActivityJournal.ps1`
- Create: `scripts/windows/Upgrade-ActivityJournal.ps1`
- Create: `tests/Lifecycle.Tests.ps1`

- [ ] Write tests for idempotent installation, upgrade without deleting Journal data, and uninstall that removes tasks but preserves user data by default.
- [ ] Add `-PurgeData` as an explicit destructive option requiring confirmation.
- [ ] Record installed version and migration version in `Journal/config/installation.json`.
- [ ] Commit: `feat: harden Windows lifecycle commands`.

### Task 16: Add configuration validation and migration

**Files:**
- Create: `src/config.py`
- Create: `tests/test_config.py`
- Modify: `scripts/windows/Install-ActivityJournal.ps1`
- Modify: `config/settings.example.json`

- [ ] Write tests for missing required fields, unknown fields warning, invalid endpoints, invalid paths, and schema migration.
- [ ] Validate configuration before installing scheduled tasks.
- [ ] Print actionable errors instead of allowing partially configured services.
- [ ] Commit: `feat: validate and migrate configuration`.

---

## Phase 8: Documentation, CI, and release hardening

### Task 17: Complete operational documentation

**Files:**
- Modify: `README.md`
- Create: `docs/architecture.md`
- Create: `docs/privacy.md`
- Create: `docs/operations.md`
- Create: `docs/troubleshooting.md`
- Create: `docs/event-schema.md`

- [ ] Document installation, upgrade, uninstall, private mode, retention, data locations, model setup, dashboard use, backups, and recovery.
- [ ] Include a data-flow diagram and a threat model for screenshots, Telegram content, credentials, and model endpoints.
- [ ] Add a verification checklist using `Doctor.ps1`.
- [ ] Commit: `docs: document operations privacy and architecture`.

### Task 18: Add continuous integration and release checks

**Files:**
- Create: `.github/workflows/test.yml`
- Create: `.github/workflows/release-check.yml`
- Create: `pyproject.toml`
- Modify: `.gitignore`

- [ ] Run Python unit tests, compile checks, PowerShell parser checks, and repository secret scanning on every push and pull request.
- [ ] Verify that no Journal data, screenshots, API keys, or local model files are tracked.
- [ ] Add a release check that validates example configuration and README command paths.
- [ ] Commit: `ci: add automated tests and release checks`.

### Task 19: Publish a contributor-friendly release

**Files:**
- Modify: `README.md`
- Create: `CHANGELOG.md`
- Create: `CONTRIBUTING.md`
- Create: `SECURITY.md`

- [ ] Document supported Windows and Python versions, local model requirements, privacy expectations, issue reporting, and security disclosure.
- [ ] Tag the first stable release only after all previous phases pass their acceptance checks.
- [ ] Commit: `docs: prepare public project release`.

---

## Definition of done

The project is ready for regular use when all of the following are true:

- `Doctor.ps1` reports no required failures.
- Private mode stops every collector within one sampling interval.
- Secrets are redacted before model submission and, when configured, before storage.
- Re-running collectors, imports, analysis, and journal synthesis is idempotent.
- A crashed model worker can resume queued jobs without losing events.
- A screenshot with 125% scaling is saved at physical desktop dimensions.
- Sessions and hourly/daily/weekly journals link back to evidence IDs.
- Dashboard binds only to localhost.
- Uninstall removes scheduled tasks without deleting Journal data unless `-PurgeData` is explicitly used.
- CI passes Python tests, PowerShell parsing, configuration validation, and secret scanning.

## Suggested milestone commits

Use one focused commit per task. The first six milestones should be:

```text
feat: define privacy controls and retention settings
feat: redact sensitive activity evidence
feat: add private mode and retention enforcement
feat: add activity journal diagnostics
feat: add worker health and heartbeats
feat: add versioned SQLite event store
```

After each milestone, run the relevant tests and `Doctor.ps1` before starting the next task.
