# Reliability and Visibility Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the concrete gaps found while building and stress-testing the activity-journal pipeline this session — missing health visibility on the most failure-prone stage, unbounded disk growth, a dropped app-name in reports, a truncated daily narrative, an orphaned validation module, and no CI.

**Architecture:** Eight independent, small tasks against the existing `src/collectors|analysis|providers|infra|orchestration|ops` package layout. No new subsystems, no new dependencies. Each task touches 1-2 files and ships its own tests.

**Tech Stack:** Python 3.10+, pytest, GitHub Actions.

**Spec:** No separate spec doc — this plan documents its own rationale per task, drawn from gaps found live-testing the pipeline earlier in this session (see repo commit history on `develop` for the context each gap was found in).

## Global Constraints

- Every module is invoked as `python -m src.<subpackage>.<name>` — no bare-script imports, no new `try/except ImportError` fallback patterns (removed project-wide already).
- Follow `rules/human-readable-reports.md`: any report-facing text stays human-readable prose, never raw IDs or ISO-with-microseconds timestamps.
- Commits: conventional format (`feat:`, `fix:`, `test:`, `docs:`, `ci:`), plain everyday words, authored as `AminFiroozi <afiroozi007@gmail.com>` — never a Claude co-author trailer. Work on a feature branch off `develop` (`git checkout -b feat/reliability-improvements`), squash-merge into `develop` when the whole plan is done, then merge `develop` into `master`. See `docs`-level `git-workflow` skill for the exact commands — this plan assumes that workflow, doesn't repeat it per task.
- Run `python -m pytest tests/ -q` after every task; all tests must pass before moving to the next task.

---

### Task 1: Heartbeat for vision analysis

**Files:**
- Modify: `src/analysis/analyze_screenshots.py`
- Test: `tests/test_analyze_screenshots_queue.py`

**Interfaces:**
- Consumes: `src.infra.heartbeat.write_heartbeat(journal_root: Path, service: str, status: str, items_processed: int = 0, error_message: str | None = None) -> Path` (already exists, used by every other collector).
- Produces: a `Journal/health/vision-analysis.json` heartbeat file, service name `"vision-analysis"`.

Right now this module has no heartbeat call at all — it's the only pipeline stage `doctor.py` can never report on, and it's the stage most likely to fail (network, rate limits, provider outage).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_analyze_screenshots_queue.py` (uses the existing `_make_journal`/`_run` helpers already in that file):

```python
    def test_successful_run_writes_a_heartbeat(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = _make_journal(Path(directory))
            with mock.patch.object(module, "call_vision", return_value={"summary": "coding", "confidence": 0.9}):
                _run(journal)

            heartbeat_path = journal / "health" / "vision-analysis.json"
            self.assertTrue(heartbeat_path.exists())
            heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
            self.assertEqual(heartbeat["status"], "success")
            self.assertEqual(heartbeat["itemsProcessed"], 1)

    def test_failed_run_writes_a_failed_heartbeat_when_nothing_succeeds(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = _make_journal(Path(directory))
            with mock.patch.object(module, "call_vision", side_effect=ValueError("model unavailable")):
                _run(journal)

            heartbeat_path = journal / "health" / "vision-analysis.json"
            self.assertTrue(heartbeat_path.exists())
            heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
            self.assertEqual(heartbeat["status"], "failed")
            self.assertEqual(heartbeat["itemsProcessed"], 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_analyze_screenshots_queue.py -v`
Expected: both new tests FAIL (no `health/vision-analysis.json` gets written).

- [ ] **Step 3: Add the heartbeat import and calls**

In `src/analysis/analyze_screenshots.py`, add the import alongside the existing ones near the top:

```python
from src.infra.heartbeat import write_heartbeat
```

Find the end of `main()` (the block that writes `status.write_text(...)` and prints the summary, currently the last few lines before `return 0 if results or not failures else 1`). Replace:

```python
    with output.open("a", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")
    remaining = sum(1 for _ in (journal / "queue" / "pending").glob("*.json"))
    status.write_text(json.dumps({"date": args.date, "status": "complete" if not failures else "partial", "analyzed": len(results), "failed": failures, "queuedRemaining": remaining}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"analyzed": len(results), "failed": len(failures), "queuedRemaining": remaining, "output": str(output)}))
    return 0 if results or not failures else 1
```

with:

```python
    with output.open("a", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")
    remaining = sum(1 for _ in (journal / "queue" / "pending").glob("*.json"))
    status.write_text(json.dumps({"date": args.date, "status": "complete" if not failures else "partial", "analyzed": len(results), "failed": failures, "queuedRemaining": remaining}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"analyzed": len(results), "failed": len(failures), "queuedRemaining": remaining, "output": str(output)}))
    if results or not failures:
        write_heartbeat(journal, "vision-analysis", "success", items_processed=len(results))
        return 0
    write_heartbeat(journal, "vision-analysis", "failed", items_processed=len(results), error_message=failures[0]["error"] if failures else None)
    return 1
```

This mirrors the existing `return 0 if results or not failures else 1` logic exactly, just also recording it. The two early-return paths above this (`no-screenshots` status, and the `ProviderError` on `resolve_provider` failure) don't need a heartbeat call added — `no-screenshots` isn't a failure worth alerting on, and the provider-resolution failure already writes a `status.json` a caller can inspect; add heartbeats there too only if you find yourself wanting them later, out of scope for this task.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_analyze_screenshots_queue.py -v`
Expected: all tests PASS, including the two new ones and the three pre-existing ones in that file.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass, no regressions.

- [ ] **Step 6: Commit**

```bash
git add src/analysis/analyze_screenshots.py tests/test_analyze_screenshots_queue.py
git commit -m "feat(analysis): add heartbeat to vision analysis"
```

---

### Task 2: Retention cleans up the queue directories

**Files:**
- Modify: `src/infra/retention.py`
- Test: `tests/test_retention.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `run_retention` now also removes old files under `Journal/queue/completed/` and `Journal/queue/failed/`.

`_PRUNED_SUBDIRECTORIES` in `retention.py` is `("raw", "screenshots", "hourly", "daily", "llm-context")` — `queue/completed/` and `queue/failed/` (job-state JSON files, one per screenshot ever processed or given up on) are never touched and grow forever.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_retention.py`:

```python
    def test_removes_old_completed_and_failed_queue_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for state in ("completed", "failed", "pending", "processing"):
                (root / "queue" / state).mkdir(parents=True)
            old_completed = root / "queue" / "completed" / "old.json"
            old_failed = root / "queue" / "failed" / "old.json"
            new_pending = root / "queue" / "pending" / "new.json"
            for path in (old_completed, old_failed, new_pending):
                path.write_text("{}", encoding="utf-8")
            old_time = time.time() - (200 * 86400)
            os.utime(old_completed, (old_time, old_time))
            os.utime(old_failed, (old_time, old_time))

            result = run_retention(root, retention_days=90)

            self.assertFalse(old_completed.exists())
            self.assertFalse(old_failed.exists())
            self.assertTrue(new_pending.exists())
            self.assertEqual(result["removedFiles"], 2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_retention.py -v`
Expected: FAIL — `old_completed.exists()` is still `True` because `queue/completed` isn't in `_PRUNED_SUBDIRECTORIES`.

- [ ] **Step 3: Add the queue state directories to the pruned list**

In `src/infra/retention.py`, change:

```python
_PRUNED_SUBDIRECTORIES = ("raw", "screenshots", "hourly", "daily", "llm-context")
```

to:

```python
_PRUNED_SUBDIRECTORIES = ("raw", "screenshots", "hourly", "daily", "llm-context", "queue/completed", "queue/failed")
```

`queue/pending` and `queue/processing` are deliberately **not** included — those hold live, unfinished work; pruning them by age would silently drop a screenshot that's still legitimately waiting on a retry backoff. `run_retention`'s existing loop already does `journal_root / relative` and `target.rglob("*")`, so a two-segment relative path (`"queue/completed"`) works without any other code change — `pathlib.Path` handles the `/` in the string the same as a nested join.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_retention.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/infra/retention.py tests/test_retention.py
git commit -m "fix(infra): prune old completed and failed queue jobs in retention"
```

---

### Task 3: Surface dead-lettered queue jobs in doctor

**Files:**
- Modify: `src/ops/doctor.py`
- Test: `tests/test_doctor.py`

**Interfaces:**
- Consumes: nothing new (reads `Journal/queue/failed/*.json` directly, same pattern the existing checks use for `Journal/health/*.json`).
- Produces: a new check row, `name="queue-failed"`, in `run_local_checks`'s output. `required=False` (a WARN, not a FAIL) — dead-lettered jobs are notable, not fatal.

Right now nothing surfaces "N screenshots permanently gave up" anywhere a human would see it.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_doctor.py`:

```python
    def test_warns_when_queue_has_failed_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "config" / "settings.json").write_text(json.dumps({"projectPaths": []}), encoding="utf-8")
            (root / "queue" / "failed").mkdir(parents=True)
            (root / "queue" / "failed" / "job1.json").write_text("{}", encoding="utf-8")
            (root / "queue" / "failed" / "job2.json").write_text("{}", encoding="utf-8")

            checks = run_local_checks(root, minimum_free_bytes=1)

            queue_check = next(check for check in checks if check["name"] == "queue-failed")
            self.assertFalse(queue_check["ok"])
            self.assertFalse(queue_check["required"])
            self.assertIn("2", queue_check["detail"])

    def test_queue_failed_check_is_ok_when_empty_or_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "config" / "settings.json").write_text(json.dumps({"projectPaths": []}), encoding="utf-8")

            checks = run_local_checks(root, minimum_free_bytes=1)

            queue_check = next(check for check in checks if check["name"] == "queue-failed")
            self.assertTrue(queue_check["ok"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_doctor.py -v`
Expected: FAIL with `StopIteration` — no check named `"queue-failed"` exists yet.

- [ ] **Step 3: Add the check**

In `src/ops/doctor.py`, in `run_local_checks`, right before the final `return checks` (after the `python-version` check is appended), add:

```python
    failed_queue_dir = root / "queue" / "failed"
    failed_count = len(list(failed_queue_dir.glob("*.json"))) if failed_queue_dir.exists() else 0
    checks.append(
        _check(
            "queue-failed",
            failed_count == 0,
            f"{failed_count} screenshot(s) gave up after repeated failures" if failed_count else "no dead-lettered jobs",
            required=False,
        )
    )
    return checks
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_doctor.py -v`
Expected: all PASS, including the pre-existing `test_reports_healthy_local_journal` — that test asserts `all(check["ok"] for check in checks)`, and with no `queue/failed/` directory present in that test's temp dir, `queue-failed` resolves `ok=True`, so it still holds.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/ops/doctor.py tests/test_doctor.py
git commit -m "feat(ops): warn in doctor when the queue has dead-lettered jobs"
```

---

### Task 4: Fix "unknown" app name for screen-type evidence lines

**Files:**
- Modify: `src/analysis/journalize.py`
- Test: `tests/test_journalize.py`

**Interfaces:**
- Consumes: nothing new — reads the same raw event dict shape `build_journals.py` already passes in, specifically `event["analysis"]["applications"]` for `source == "screenshot-vision"` events.
- Produces: `_event_kind_and_app` now returns a real app name for screen-type events instead of always `"unknown"`.

`screenshot-vision` events (from `analyze_screenshots.py`'s output) never have a top-level `application` or `process` key — the detected app names live at `event["analysis"]["applications"]`. `_event_kind_and_app` only checks the top-level keys, so every screen-type evidence line reads `... — screen — unknown (N samples)` even though the real app name exists in the data.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_journalize.py`:

```python
    def test_screen_evidence_shows_detected_app_not_unknown(self):
        markdown = render_journal(
            "Daily journal",
            [
                {
                    "source": "screenshot-vision",
                    "timestamp": "2026-08-23T10:00:00+00:00",
                    "analysis": {"applications": ["Visual Studio Code"], "summary": "coding"},
                }
            ],
            [],
        )

        self.assertIn("Visual Studio Code", markdown)
        self.assertNotIn("unknown", markdown)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_journalize.py -v`
Expected: FAIL — the evidence line reads `... — screen — unknown`.

- [ ] **Step 3: Fix `_event_kind_and_app`**

In `src/analysis/journalize.py`, replace:

```python
def _event_kind_and_app(event: dict[str, Any]) -> tuple[str, str]:
    kind = event.get("kind") or event.get("source") or "activity"
    application = event.get("application") or event.get("process") or "unknown"
    return _KIND_LABELS.get(kind, kind), application
```

with:

```python
def _event_kind_and_app(event: dict[str, Any]) -> tuple[str, str]:
    kind = event.get("kind") or event.get("source") or "activity"
    application = event.get("application") or event.get("process")
    if not application and kind == "screenshot-vision":
        applications = (event.get("analysis") or {}).get("applications")
        if isinstance(applications, list) and applications:
            application = ", ".join(str(item) for item in applications)
        elif isinstance(applications, str) and applications:
            application = applications
    return _KIND_LABELS.get(kind, kind), application or "unknown"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_journalize.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass — this touches shared rendering code used by both hourly and weekly journals, so watch for any other test asserting the literal string `"unknown"` in rendered output before assuming a clean pass.

- [ ] **Step 6: Commit**

```bash
git add src/analysis/journalize.py tests/test_journalize.py
git commit -m "fix(analysis): show detected app name for screen evidence, not unknown"
```

---

### Task 5: Wire `load_privacy_config` into `active_content.py`

**Files:**
- Modify: `src/collectors/active_content.py`
- Test: none new — this is a pure behavior-preserving refactor; the existing test suite for `active_content.py`'s neighbors and `infra/privacy_config.py`'s own tests (`tests/test_privacy_config.py`) already cover both sides. If you want an integration-level test, skip it here — `active_content.py` has no existing test file (it needs real pywinauto/Windows UI Automation to exercise meaningfully, which isn't testable in this environment) and adding one just for this wiring is disproportionate to the change.

**Interfaces:**
- Consumes: `src.infra.privacy_config.load_privacy_config(settings: dict) -> dict` (already exists, already tested, currently unused anywhere in the codebase).
- Produces: no behavior change — `load_privacy_config` returns the same shape `active_content.py` already reads from (`captureEnabled`, `redactBeforeStorage`, `excludedApplications`, `excludedWindowTitlePatterns`), just validated and defaulted instead of raw `config.get("privacy") or {}`.

This closes the third orphaned-but-tested module found this session (after `journalize.py`/`sessionize.py` and `processing_queue.py`).

- [ ] **Step 1: Confirm the current behavior with the existing tests**

Run: `python -m pytest tests/test_privacy_config.py -v`
Expected: all PASS already — this step is just establishing the baseline before you touch anything.

- [ ] **Step 2: Swap the raw config read for the validated one**

In `src/collectors/active_content.py`, add the import near the top:

```python
from src.infra.privacy_config import load_privacy_config
```

Find this line in `main()`:

```python
    privacy = config.get("privacy") or {}
```

Replace it with:

```python
    privacy = load_privacy_config(config)
```

`load_privacy_config` takes the **whole** settings dict (not just the `privacy` sub-object — it does `settings.get("privacy", {})` internally), which is exactly what `config` already is at this call site. Every key `active_content.py` reads afterward (`privacy.get("captureEnabled")`, `privacy.get("excludedApplications")`, `privacy.get("redactBeforeStorage", True)`, `privacy.get("excludedWindowTitlePatterns")` via `is_excluded`) is in `DEFAULT_PRIVACY_CONFIG`, so nothing downstream needs to change.

One behavior difference to be aware of, not to fix here: `load_privacy_config` raises `ValueError` on a malformed `privacy` block (e.g. `retentionDays` not a positive int, or `excludedApplications` containing a non-string) instead of silently proceeding with whatever garbage was there. `main()`'s `if __name__` entrypoint has no try/except around this call, so a malformed config now makes `active_content.py` crash loudly instead of misbehaving quietly — this is the correct, intended behavior (fail fast on bad config), but mention it if you're the one who eventually adds a general "validate config at startup" pass across all collectors (a natural follow-up, not in scope here).

- [ ] **Step 3: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass — no test currently constructs an `active_content.py`-shaped config with an invalid `privacy` block, so nothing should newly fail.

- [ ] **Step 4: Manually verify against a real config**

Run: `python -m src.collectors.active_content --journal-root D:/JARVIS/Journal --config D:/JARVIS/Journal/config/settings.json`
Expected: exits 0 (same as before this change), and `Journal/health/content-collector.json`'s `lastSuccessAt` updates if the foreground window matched an allowed process name at the moment you ran it — if it didn't match, that's fine too, that's pre-existing behavior unrelated to this task.

- [ ] **Step 5: Commit**

```bash
git add src/collectors/active_content.py
git commit -m "refactor(collectors): validate privacy config in active_content via load_privacy_config"
```

---

### Task 6: Give the daily narrative whole-day coverage via session summaries

**Files:**
- Modify: `src/analysis/synthesize_journal.py`
- Test: `tests/test_synthesize_journal.py`

**Interfaces:**
- Consumes: `src.analysis.sessionize.detect_sessions(events: list[dict]) -> list[dict]` (already exists, already used by `build_journals.py`).
- Produces: `read_events` now returns `dict[str, list[dict]]` with keys `"sessions"` and `"recent"` instead of a flat `list[dict]`. `call_model`'s signature changes to match. This is a breaking change to both functions' contracts within this module — both callers are inside this same file (`main()`), so it's fully contained.

Right now `read_events` keeps only the **last 150** compacted raw events, and `call_model` shrinks further to fit a 6000-character budget. On a busy day this means the daily narrative only ever sees the last hour or two — the model has no idea what happened at 9am if it's synthesizing at 11pm. `detect_sessions` output is dramatically more compact per unit of day covered (one session line can represent dozens of raw events), so feeding session summaries for the *whole day* alongside a smaller tail of raw events for *recent detail* fits both within the same character budget.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_synthesize_journal.py`:

```python
    def test_compact_session_produces_a_compact_dict(self):
        from src.analysis.synthesize_journal import compact_session

        session = {
            "startAt": "2026-08-23T10:00:00+00:00",
            "endAt": "2026-08-23T10:30:00+00:00",
            "classification": "coding",
            "apps": ["Code", "WindowsTerminal"],
            "confidence": 0.9,
        }

        result = compact_session(session)

        self.assertEqual(result["class"], "coding")
        self.assertEqual(result["apps"], ["Code", "WindowsTerminal"])
        self.assertIn("t", result)
        self.assertNotIn("confidence", result)

    def test_read_events_returns_sessions_and_recent_events_separately(self):
        import json
        import tempfile
        from pathlib import Path

        from src.analysis.synthesize_journal import read_events

        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            raw = journal / "raw"
            raw.mkdir()
            events = [
                {"source": "foreground-window", "process": "Code", "timestamp": f"2026-08-23T{hour:02d}:00:00+00:00", "localTimestamp": f"2026-08-23T{hour:02d}:00:00+00:00", "active": True}
                for hour in range(9, 18)
            ]
            (raw / "activity-2026-08-23.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")

            result = read_events(journal, "2026-08-23")

            self.assertIn("sessions", result)
            self.assertIn("recent", result)
            self.assertTrue(len(result["sessions"]) >= 1)
            first_hour = result["sessions"][0]["t"]
            self.assertTrue(first_hour.startswith("09:") or "09:" in first_hour)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_synthesize_journal.py -v`
Expected: FAIL — `compact_session` and the new return shape of `read_events` don't exist yet.

- [ ] **Step 3: Implement `compact_session` and rework `read_events`/`call_model`**

In `src/analysis/synthesize_journal.py`, add the import:

```python
from src.analysis.sessionize import detect_sessions
```

Add this function near `compact_event`:

```python
def compact_session(session: dict) -> dict:
    start = local_time({"localTimestamp": session.get("startAt")})
    end = local_time({"localTimestamp": session.get("endAt")})
    return {
        "t": f"{start}-{end}" if start and end else start or end,
        "class": session.get("classification", "unknown"),
        "apps": session.get("apps") or [],
    }
```

Replace `read_events`:

```python
def read_events(journal: pathlib.Path, date: str) -> dict:
    raw_events: list[dict] = []
    compacted: list[dict] = []
    for filename in (f"activity-{date}.jsonl", f"content-{date}.jsonl", f"visual-{date}.jsonl"):
        path = journal / "raw" / filename
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                raw_events.append(record)
                event = compact_event(record)
                if event:
                    compacted.append(event)
    sessions = [compact_session(session) for session in detect_sessions(raw_events)]
    return {"sessions": sessions, "recent": compacted[-60:]}
```

Replace `call_model`:

```python
def call_model(provider: dict, evidence_dict: dict) -> dict:
    sessions = evidence_dict["sessions"]
    recent = evidence_dict["recent"]
    evidence = json.dumps({"day_sessions": sessions, "recent_detail": recent}, ensure_ascii=False, separators=(",", ":"))
    max_chars = 6000
    while len(evidence) > max_chars and len(recent) > 5:
        recent = recent[len(recent) // 3:]
        evidence = json.dumps({"day_sessions": sessions, "recent_detail": recent}, ensure_ascii=False, separators=(",", ":"))
    while len(evidence) > max_chars and len(sessions) > 5:
        sessions = sessions[len(sessions) // 5:]
        evidence = json.dumps({"day_sessions": sessions, "recent_detail": recent}, ensure_ascii=False, separators=(",", ":"))
    messages = [{"role": "system", "content": PROMPT}, {"role": "user", "content": f"Observed events for the day:\n{evidence}"}]
    content = call_chat_completions(provider, messages, temperature=0.2)
    return parse_model_json(content)
```

Note the shrink order: `recent` (raw event detail) gets thinned first, `day_sessions` (the whole-day coverage this task exists to preserve) only gets thinned as a last resort if the day was so eventful that even the compact session summaries don't fit.

In `main()`, find:

```python
    events = read_events(journal, args.date)
    status_path = journal / "raw" / f"journal-{args.date}.status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    if not events:
        status_path.write_text(json.dumps({"date": args.date, "status": "no-events"}) + "\n", encoding="utf-8")
        return 0
    try:
        provider = resolve_provider(config, "journalSynthesis")
        narrative = call_model(provider, events)
```

Replace with:

```python
    evidence_dict = read_events(journal, args.date)
    status_path = journal / "raw" / f"journal-{args.date}.status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    if not evidence_dict["sessions"] and not evidence_dict["recent"]:
        status_path.write_text(json.dumps({"date": args.date, "status": "no-events"}) + "\n", encoding="utf-8")
        return 0
    try:
        provider = resolve_provider(config, "journalSynthesis")
        narrative = call_model(provider, evidence_dict)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_synthesize_journal.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Verify against real data**

Run: `python -m src.analysis.synthesize_journal --journal-root D:/JARVIS/Journal --config D:/JARVIS/Journal/config/settings.json --date 2026-08-28`
Expected: exits 0, `Journal/daily/2026-08-28.md`'s `## LLM narrative` section updates. Open it and check the timeline now references morning activity too, not just the last hour or two before the run.

- [ ] **Step 7: Commit**

```bash
git add src/analysis/synthesize_journal.py tests/test_synthesize_journal.py
git commit -m "feat(analysis): give daily synthesis whole-day coverage via session summaries"
```

---

### Task 7: GitHub Actions CI

**Files:**
- Create: `.github/workflows/tests.yml`

**Interfaces:**
- Consumes: nothing from the codebase — this is pure CI config.
- Produces: a workflow that runs `pytest tests/ -q` on every push and pull request against `master` and `develop`.

71 tests exist and nothing runs them automatically. This is the single cheapest, highest-leverage addition on the whole list.

- [ ] **Step 1: Create the workflow file**

```yaml
name: tests

on:
  push:
    branches: [master, develop]
  pull_request:
    branches: [master, develop]

jobs:
  pytest:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install dependencies
        run: pip install -e ".[dev]"
      - name: Run tests
        run: python -m pytest tests/ -q
```

`windows-latest` matches the platform this pipeline is actually developed and run on (Task Scheduler XML generation, `pywinauto`-backed collectors); the test suite itself is written to run cross-platform (nothing in it requires Windows specifically — it mocks the OS-specific bits), but running CI on the same OS as the primary deployment target catches real Windows-path issues (like the `parents[N]` bug found this session) that a Linux CI runner would silently pass through.

- [ ] **Step 2: Verify the YAML is well-formed**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/tests.yml'))"`
Expected: no error. (If `pyyaml` isn't installed locally, `pip install pyyaml` first, or just eyeball the indentation carefully — this is the only verification step available before it actually runs on GitHub's infrastructure.)

- [ ] **Step 3: Commit and push to see it run**

```bash
git add .github/workflows/tests.yml
git commit -m "ci: run pytest on push and pull request"
```

This one can't be verified locally beyond YAML syntax — push it as part of this plan's feature branch and check the Actions tab on GitHub after the branch is pushed to confirm the workflow actually triggers and passes.

---

## Self-Review

**Spec coverage:** all eight items from the "Quick wins" and "Real gaps" tiers of the improvement list are covered by Tasks 1-7 (task 3 in the original list — cloud fallback for synthesis — is deliberately left out of this plan; it's a config recommendation, not a code change, and belongs in a conversation about whether Amin wants that tradeoff, not a task an engineer executes unilaterally). The two "worth considering" items (dashboard-as-HTML, Credential Manager) are explicitly out of scope — bigger design decisions, not gaps to close.

**Placeholder scan:** every step has real code, real file paths, real current-state snippets copied from the actual files as they exist on `develop` right now.

**Type consistency:** `read_events`'s return type changes from `list[dict]` to `dict` (Task 6) — checked that its only caller (`main()`, same file) is updated in the same task, and no other file in the codebase calls `synthesize_journal.read_events` or `synthesize_journal.call_model` directly (both are internal to this module; `run_hourly.py` and `daily_summary.py` invoke the whole module via `subprocess`, not by importing these functions).
