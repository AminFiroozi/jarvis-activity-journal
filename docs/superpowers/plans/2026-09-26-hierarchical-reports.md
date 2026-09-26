# Hierarchical Screen-Aware Reports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every screenshot gets its own Markdown file describing what the vision model saw; hourly reports compact that hour's screenshot files, daily reports compact that day's hourly reports, weekly reports compact that week's daily reports, all in one format that differs only in depth. Model-reported confidence is removed from the project.

**Architecture:** `analyze_screenshots` renders each vision result (and each dedupe-dropped duplicate) to `screens/DATE/HH/<clock>.md` with plain code. `synthesize_period.py` gains `--period hourly|daily|weekly`; each level gathers the Markdown of the level below, hashes that input, and rebuilds its own file only when the hash differs from the stamp stored in the existing file. One prompt builder (`report_levels.py`) and one renderer (`report_render.py`) serve all three levels.

**Tech Stack:** Python 3.13 stdlib only (unittest style, run with pytest), Pillow (already used), existing `FileJobQueue`, `call_chat_completions`.

**Spec:** `docs/superpowers/specs/2026-09-26-hierarchical-reports-design.md`

## Global Constraints

- No model-reported confidence anywhere: not in vision output/prompt, not in reports, not in entity notes, no `minConfidence`. Internal computed scores (`sessionize.py` session confidence, `ocr.py` box confidence) stay.
- Reports are plain human text (rule `human-readable-reports`): local time, real app names, no event IDs, no ISO8601 timestamps, no backtick evidence dumps. The only machine marker allowed is the trailing HTML comment `<!-- input: <hex> -->`.
- Chat/messaging content is summarized, never quoted verbatim; no secrets (existing rules `capture-chat-topic-and-correspondent`).
- `daily/DATE.md` keeps the `## LLM narrative` marker (the Obsidian sync reads from it).
- Shared report skeleton, exactly this order, empty sections omitted: summary paragraph, `### On screen`, `### Timeline`, `### Patterns`, `### Next actions`. No Accomplishments/Blockers.
- Config stage keys: hourly → `hourlySynthesis`, daily → `journalSynthesis`, weekly → `weeklySynthesis`.
- Tests: `cd /home/amin/jarvis-activity-journal && .venv/bin/python -m pytest -q`. Baseline before this plan: 186 passed.
- Git: work on branch `feat/hierarchical-reports`. Commit with the user's own configured git identity, plain messages, **no `Co-Authored-By` trailer and no Claude attribution** (standing user rule; it overrides any default attribution).
- Rule files in `rules/` are binding; do not edit or add any rule without the interactive approval described in Task 9.

## Review Focus

- A screenshot filename that does not match `screen-HH-MM-SS-mmm.jpg` must not crash rendering (Task 3 test).
- The vision model may return `applications` / `projects` as a list instead of a comma string, and `observations` / `screen_details` as a string instead of a list (Task 3 tests).
- An hour whose only activity events have no process ("no active window") must produce no report and no model call (Task 6 test).
- A daily file with no `## LLM narrative` marker must be skipped by the weekly gatherer, not crash it (Task 6 test).
- A model that returns section values as a bare string, or timeline entries as plain strings, must still render (Task 5 tests).

---

### Task 1: Remove model-reported confidence

**Files:**
- Modify: `config/prompts.json:4,10-11`
- Modify: `src/analysis/analyze_screenshots.py:117`
- Modify: `src/analysis/entity_facts.py:20-23,124-128`
- Modify: `src/orchestration/sync_entities.py:101-106,162-186`
- Modify: `src/analysis/build_llm_context.py:85`
- Modify: `config/settings.example.json:130`
- Test: `tests/test_entity_facts.py`, `tests/test_sync_entities.py`, `tests/test_vision_prompts.py`, `tests/test_analyze_screenshots_queue.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `entity_facts.validate_facts` entries are `{"name", "note", "evidence"}` (no `confidence`); `sync_entities.render_entry(date, note, evidence)` (3 args); dedupe/ranking of entity entries by `len(entry["evidence"])`; skip reason string `"superseded-by-more-evidence"`.

- [ ] **Step 0: Create the branch**

```bash
cd /home/amin/jarvis-activity-journal && git switch -c feat/hierarchical-reports
```

- [ ] **Step 1: Write the failing tests**

In `tests/test_vision_prompts.py`, add inside the existing prompt test class (next to `test_prompt_includes_ocr_regions_and_fact_only_contract`):

```python
    def test_prompt_schema_has_no_confidence_field(self):
        prompts = load_prompts(Path(__file__).parents[1] / "config" / "prompts.json")

        prompt = build_prompt("browser", prompts, None)

        self.assertNotIn('"confidence"', prompt)
        self.assertNotIn("lower confidence", prompt.lower())
```

In `tests/test_entity_facts.py`, replace `test_defaults_confidence_and_evidence` with:

```python
    def test_defaults_evidence_and_has_no_confidence(self):
        payload = {"people": [{"name": "X", "note": "y" * 50, "confidence": 0.9}], "projects": []}
        result = validate_facts(payload)
        self.assertEqual(result["people"][0]["evidence"], [])
        self.assertNotIn("confidence", result["people"][0])
```

In `tests/test_entity_facts.py::ValidateFactsTests::test_drops_entries_with_blank_name_or_short_note` no change is needed (the stray `"confidence": 0.7` key is simply ignored).

In `tests/test_sync_entities.py`:
1. `SyncEntitiesTests._config`: remove `"minConfidence": 0.0,` from the `entityUpdates` dict.
2. `test_max_entities_per_day_caps_output`: replace the `canned` JSON with
```python
            canned = json.dumps({
                "people": [
                    {"name": "DariushSeif", "note": "x" * 50, "evidence": ["a", "b"]},
                    {"name": "AnotherPerson", "note": "y" * 50, "evidence": ["a"]},
                ],
                "projects": [],
            })
```
3. Rename `test_confidence_dedup_loser_is_recorded_in_skipped` to `test_evidence_dedup_loser_is_recorded_in_skipped`, replace its `canned` with
```python
            canned = json.dumps({
                "people": [
                    {"name": "DariushSeif", "note": "a" * 50, "evidence": ["one"]},
                    {"name": "Dariush", "note": "b" * 50, "evidence": ["one", "two"]},
                ],
                "projects": [],
            })
```
   and change its assertions to expect the winner to be the entry with more evidence. Both names resolve to the same note, so `result["written"][0]["name"]` is still the note stem `"DariushSeif"`; the skipped reason becomes `"superseded-by-more-evidence"`:
```python
            self.assertEqual(len(result["written"]), 1)
            self.assertEqual(result["written"][0]["name"], "DariushSeif")
            superseded = [entry for entry in result["skipped"] if entry["reason"] == "superseded-by-more-evidence"]
            self.assertEqual(len(superseded), 1)
            self.assertEqual(superseded[0]["name"], "DariushSeif")
```
4. In the tests that only pass `"confidence": 0.9` inside canned JSON (`test_ambiguous_name_is_skipped_not_guessed`, `test_dry_run_writes_status_but_nothing_under_the_vault`, the parse test in `test_entity_facts.py::ExtractEntityFactsTests`), delete the `"confidence": ...` key; behavior is unchanged.
5. Any test calling `render_entry(date, note, evidence, confidence)` gets the 3-argument form (search: `grep -n "render_entry" tests/test_sync_entities.py`).

In `tests/test_analyze_screenshots_queue.py`, change both `return_value={"summary": "coding", "confidence": 0.9}` to `return_value={"summary": "coding"}`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_vision_prompts.py tests/test_entity_facts.py tests/test_sync_entities.py -q`
Expected: FAIL (`confidence` still in the schema/entries, `render_entry` arity, reason string).

- [ ] **Step 3: Implement**

`config/prompts.json`:
- Line 4: change `If something is uncertain, say so and lower confidence.` to `If something is uncertain, say so.`
- Remove the `"confidence": "number from 0.0 to 1.0"` line and the comma after the `"observations"` line above it (so `observations` becomes the last key of `output`).

`src/analysis/analyze_screenshots.py` line 117: change
`Use empty arrays and lower confidence when evidence is unclear. Do not include secrets.` to
`Use empty arrays when evidence is unclear. Do not include secrets.`

`src/analysis/entity_facts.py`:
- In `PROMPT`, remove `, "confidence": 0.0` from both example lines (people and projects), and change the last sentence `Mark uncertain interpretations through a lower confidence value.` to `Leave out anything you are unsure of.`
- Replace the confidence block in `_validate_entries`:
```python
        evidence_list = entry.get("evidence")
        evidence_list = [str(item) for item in evidence_list] if isinstance(evidence_list, list) else []
        valid.append({"name": name, "note": note, "evidence": evidence_list})
```
  (delete the `try: confidence = float(...)` block).

`src/orchestration/sync_entities.py`:
```python
def render_entry(date: str, note: str, evidence: list[str]) -> str:
    lines = [f"## {date}", "", note.strip(), ""]
    if evidence:
        lines.append(f"_Evidence: {'; '.join(evidence)}_")
    lines.append(f"_Source: [[Journal/Daily/{date}|daily journal]]_")
    return "\n".join(lines).rstrip() + "\n"
```
In `sync_entities`: delete the `min_confidence = ...` line and the `if entry["confidence"] < min_confidence:` block (3 lines incl. `continue`); replace the resolve/rank section with:
```python
            existing = resolved.get(note_path)
            if existing is None or len(entry["evidence"]) > len(existing["evidence"]):
                if existing is not None:
                    skipped.append({"name": existing["name"], "category": category, "reason": "superseded-by-more-evidence"})
                resolved[note_path] = entry
            else:
                skipped.append({"name": entry["name"], "category": category, "reason": "superseded-by-more-evidence"})
        ranked = sorted(resolved.items(), key=lambda item: len(item[1]["evidence"]), reverse=True)[:max_per_day]
        for note_path, entry in ranked:
            note_text = inject_links(entry["note"], index)
            entry_body = render_entry(date, note_text, entry["evidence"])
```

`src/analysis/build_llm_context.py` line 85: drop the ` (confidence: {analysis.get('confidence')})` suffix from the f-string.

`config/settings.example.json`: delete the `"minConfidence": 0.0,` line (line 130).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass (186 + 1 new prompt test).

- [ ] **Step 5: Commit**

```bash
git add config src tests && git commit -m "refactor: remove model-reported confidence from vision, entity notes, and prompts"
```

---

### Task 2: Dedupe returns which screenshot each duplicate matched

**Files:**
- Modify: `src/analysis/screenshot_fingerprint.py:32-46`
- Test: `tests/test_screenshot_fingerprint.py`

**Interfaces:**
- Consumes: `fingerprint_image`, `hamming_distance` (existing).
- Produces: `deduplicate_with_matches(images: list[Path], threshold: int = 4) -> tuple[list[Path], dict[Path, Path]]` — first element is the kept images in input order, second maps each dropped image to the kept image it matched. `deduplicate_images` keeps its current return value (list) by delegating.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_screenshot_fingerprint.py` (import `deduplicate_with_matches`):

```python
    def test_deduplication_reports_which_kept_image_each_duplicate_matched(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "one.jpg"
            duplicate = Path(directory) / "two.jpg"
            different = Path(directory) / "three.jpg"
            Image.new("RGB", (100, 100), "black").save(first)
            Image.new("RGB", (100, 100), "black").save(duplicate)
            image = Image.new("RGB", (100, 100), "black")
            ImageDraw.Draw(image).rectangle((0, 0, 50, 50), fill="white")
            image.save(different)

            kept, matches = deduplicate_with_matches([first, duplicate, different], threshold=4)

            self.assertEqual(kept, [first, different])
            self.assertEqual(matches, {duplicate: first})
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_screenshot_fingerprint.py -q`
Expected: FAIL (`ImportError: cannot import name 'deduplicate_with_matches'`).

- [ ] **Step 3: Implement**

Replace `deduplicate_images` in `src/analysis/screenshot_fingerprint.py` with:

```python
def deduplicate_with_matches(images: list[Path], threshold: int = 4) -> tuple[list[Path], dict[Path, Path]]:
    selected: list[Path] = []
    fingerprints: list[Fingerprint] = []
    matches: dict[Path, Path] = {}
    for image in images:
        current = fingerprint_image(image)
        matched = next(
            (
                index
                for index, previous in enumerate(fingerprints)
                if current.sha256 == previous.sha256
                or hamming_distance(current.perceptual_hash, previous.perceptual_hash) <= threshold
            ),
            None,
        )
        if matched is not None:
            matches[image] = selected[matched]
            continue
        selected.append(image)
        fingerprints.append(current)
    return selected, matches


def deduplicate_images(images: list[Path], threshold: int = 4) -> list[Path]:
    return deduplicate_with_matches(images, threshold)[0]
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_screenshot_fingerprint.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/analysis/screenshot_fingerprint.py tests/test_screenshot_fingerprint.py && git commit -m "feat: dedupe reports which kept screenshot each duplicate matched"
```

---

### Task 3: Per-screenshot Markdown renderer

**Files:**
- Create: `src/analysis/screen_markdown.py`
- Modify: `config/prompts.json` (add `screen_details` to `base.output`)
- Test: `tests/test_screen_markdown.py` (new), `tests/test_vision_prompts.py`

**Interfaces:**
- Consumes: nothing from earlier tasks besides the confidence-free prompt.
- Produces (all in `src.analysis.screen_markdown`):
  - `screen_path(journal_root: Path, image: Path) -> Path` → `journal_root/"screens"/<image.parent.name>/<HH or "unknown">/<stem without "screen-">.md`
  - `render_screen_markdown(image: Path, analysis: dict, unchanged_since: str | None = None) -> str`
  - `write_screen_markdown(journal_root: Path, image: Path, analysis: dict, unchanged_since: str | None = None) -> Path`
  - `load_analyses(journal_root: Path, date: str) -> dict[str, dict]` (screenshot path string → analysis, from `raw/visual-DATE.jsonl`)
  - `reconcile_duplicates(journal_root: Path, date: str, new_matches: dict[Path, Path]) -> list[Path]` (persists the dup→kept map in `raw/screen-dups-DATE.json`; writes "unchanged" files for duplicates whose kept screenshot has been analysed; returns the paths written)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_screen_markdown.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from src.analysis.screen_markdown import (
    load_analyses,
    reconcile_duplicates,
    render_screen_markdown,
    screen_path,
    write_screen_markdown,
)

IMAGE = Path("/j/screenshots/2026-09-26/screen-10-21-15-521.jpg")
ANALYSIS = {
    "summary": "Viewing Kibana dashboards.",
    "applications": "Elastic Kibana, Google Chrome",
    "projects": "kassa-log, nginx-moadian",
    "activity_type": "browsing",
    "observations": ["A 12-hour chart is visible."],
    "screen_details": ["The data view selector lists declaration-app-log."],
}


class RenderTests(unittest.TestCase):
    def test_renders_details_before_observations_and_metadata(self):
        text = render_screen_markdown(IMAGE, ANALYSIS)

        self.assertTrue(text.startswith("# Screen — 2026-09-26 10:21:15\n\nViewing Kibana dashboards.\n"))
        self.assertIn("### On screen", text)
        self.assertLess(text.index("- The data view selector"), text.index("- A 12-hour chart"))
        self.assertIn("**Apps:** Elastic Kibana, Google Chrome", text)
        self.assertIn("**Projects:** kassa-log, nginx-moadian", text)
        self.assertIn("**Activity:** browsing", text)

    def test_is_human_readable_with_no_confidence_or_iso_timestamps(self):
        text = render_screen_markdown(IMAGE, {**ANALYSIS, "confidence": 0.9})

        self.assertNotIn("confidence", text.lower())
        self.assertNotIn("+00:00", text)
        self.assertNotIn("T10:", text)
        self.assertNotIn("`", text)

    def test_duplicate_gets_an_unchanged_line(self):
        text = render_screen_markdown(IMAGE, ANALYSIS, unchanged_since="10:19:15")

        self.assertIn("Unchanged since 10:19:15.", text)
        self.assertIn("### On screen", text)

    def test_list_valued_apps_and_string_valued_details_are_tolerated(self):
        analysis = {"summary": "s", "applications": ["Code", "Terminal"], "projects": [], "observations": "One observation", "screen_details": "One detail"}

        text = render_screen_markdown(IMAGE, analysis)

        self.assertIn("**Apps:** Code, Terminal", text)
        self.assertNotIn("**Projects:**", text)
        self.assertIn("- One detail", text)
        self.assertIn("- One observation", text)

    def test_unrecognised_filename_does_not_crash(self):
        image = Path("/j/screenshots/2026-09-26/odd-name.jpg")

        text = render_screen_markdown(image, ANALYSIS)
        path = screen_path(Path("/j"), image)

        self.assertTrue(text.startswith("# Screen — 2026-09-26 odd-name\n"))
        self.assertEqual(path, Path("/j/screens/2026-09-26/unknown/odd-name.md"))


class WriteTests(unittest.TestCase):
    def test_writes_under_screens_date_hour_and_overwrites_idempotently(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)

            first = write_screen_markdown(journal, IMAGE, ANALYSIS)
            content = first.read_text(encoding="utf-8")
            second = write_screen_markdown(journal, IMAGE, ANALYSIS)

            self.assertEqual(first, journal / "screens" / "2026-09-26" / "10" / "10-21-15-521.md")
            self.assertEqual(first, second)
            self.assertEqual(content, second.read_text(encoding="utf-8"))


def _write_visual(journal: Path, date: str, entries: list[tuple[Path, dict]]) -> None:
    raw = journal / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"source": "screenshot-vision", "screenshot": str(image), "analysis": analysis}) for image, analysis in entries]
    (raw / f"visual-{date}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


class ReconcileDuplicatesTests(unittest.TestCase):
    def setUp(self):
        self.kept = Path("/j/screenshots/2026-09-26/screen-10-19-15-000.jpg")
        self.dup = Path("/j/screenshots/2026-09-26/screen-10-20-15-000.jpg")

    def test_duplicate_of_an_analysed_screenshot_gets_an_unchanged_file(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            _write_visual(journal, "2026-09-26", [(self.kept, ANALYSIS)])

            written = reconcile_duplicates(journal, "2026-09-26", {self.dup: self.kept})

            target = screen_path(journal, self.dup)
            self.assertEqual(written, [target])
            text = target.read_text(encoding="utf-8")
            self.assertIn("# Screen — 2026-09-26 10:20:15", text)
            self.assertIn("Unchanged since 10:19:15.", text)
            self.assertIn("### On screen", text)

    def test_waits_until_the_kept_screenshot_is_analysed_then_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)

            self.assertEqual(reconcile_duplicates(journal, "2026-09-26", {self.dup: self.kept}), [])
            self.assertFalse(screen_path(journal, self.dup).exists())

            _write_visual(journal, "2026-09-26", [(self.kept, ANALYSIS)])
            written = reconcile_duplicates(journal, "2026-09-26", {})

            self.assertEqual(written, [screen_path(journal, self.dup)])

    def test_existing_file_is_not_rewritten(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            _write_visual(journal, "2026-09-26", [(self.kept, ANALYSIS)])
            reconcile_duplicates(journal, "2026-09-26", {self.dup: self.kept})

            self.assertEqual(reconcile_duplicates(journal, "2026-09-26", {}), [])

    def test_load_analyses_maps_screenshot_to_analysis(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            _write_visual(journal, "2026-09-26", [(self.kept, ANALYSIS)])

            self.assertEqual(load_analyses(journal, "2026-09-26"), {str(self.kept): ANALYSIS})
            self.assertEqual(load_analyses(journal, "2026-01-01"), {})


if __name__ == "__main__":
    unittest.main()
```

In `tests/test_vision_prompts.py` add next to the confidence test from Task 1:

```python
    def test_prompt_schema_asks_for_screen_details(self):
        prompts = load_prompts(Path(__file__).parents[1] / "config" / "prompts.json")

        prompt = build_prompt("browser", prompts, None)

        self.assertIn('"screen_details"', prompt)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_screen_markdown.py tests/test_vision_prompts.py -q`
Expected: FAIL (`ModuleNotFoundError: src.analysis.screen_markdown`; schema lacks `screen_details`).

- [ ] **Step 3: Implement**

`config/prompts.json`: after the `"observations": "short list of directly observed facts"` line add a comma and a new last key:

```json
      "screen_details": "list of concrete things visible on screen: window and tab titles, page, panel and dashboard names, file, ticket and repository names, terminal commands, and for chat pages the topic and who it is with (never verbatim message text)"
```

Create `src/analysis/screen_markdown.py`:

```python
"""Render one Markdown file per screenshot from its vision analysis."""

from __future__ import annotations

import json
import pathlib
import re

_STEM_PATTERN = re.compile(r"^screen-(\d{2})-(\d{2})-(\d{2})-(\d{3})$")


def _clock(image: pathlib.Path) -> str:
    match = _STEM_PATTERN.match(image.stem)
    return f"{match.group(1)}:{match.group(2)}:{match.group(3)}" if match else image.stem


def _names(value) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _lines(value) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def screen_path(journal_root: pathlib.Path, image: pathlib.Path) -> pathlib.Path:
    match = _STEM_PATTERN.match(image.stem)
    hour = match.group(1) if match else "unknown"
    return journal_root / "screens" / image.parent.name / hour / f"{image.stem.removeprefix('screen-')}.md"


def render_screen_markdown(image: pathlib.Path, analysis: dict, unchanged_since: str | None = None) -> str:
    lines = [f"# Screen — {image.parent.name} {_clock(image)}", ""]
    summary = str(analysis.get("summary") or "").strip()
    if summary:
        lines.extend([summary, ""])
    if unchanged_since:
        lines.extend([f"Unchanged since {unchanged_since}.", ""])
    details = _lines(analysis.get("screen_details")) + _lines(analysis.get("observations"))
    if details:
        lines.extend(["### On screen", ""])
        lines.extend(f"- {detail}" for detail in details)
        lines.append("")
    for label, names in (("Apps", _names(analysis.get("applications"))), ("Projects", _names(analysis.get("projects")))):
        if names:
            lines.extend([f"**{label}:** {', '.join(names)}", ""])
    activity = str(analysis.get("activity_type") or "").strip()
    if activity:
        lines.extend([f"**Activity:** {activity}", ""])
    return "\n".join(lines).rstrip() + "\n"


def write_screen_markdown(
    journal_root: pathlib.Path,
    image: pathlib.Path,
    analysis: dict,
    unchanged_since: str | None = None,
) -> pathlib.Path:
    target = screen_path(journal_root, image)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_screen_markdown(image, analysis, unchanged_since), encoding="utf-8")
    return target


def load_analyses(journal_root: pathlib.Path, date: str) -> dict[str, dict]:
    path = journal_root / "raw" / f"visual-{date}.jsonl"
    analyses: dict[str, dict] = {}
    if not path.exists():
        return analyses
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            analysis = record["analysis"]
            screenshot = record["screenshot"]
        except (json.JSONDecodeError, KeyError):
            continue
        if isinstance(analysis, dict):
            analyses[str(screenshot)] = analysis
    return analyses


def reconcile_duplicates(
    journal_root: pathlib.Path,
    date: str,
    new_matches: dict[pathlib.Path, pathlib.Path],
) -> list[pathlib.Path]:
    map_path = journal_root / "raw" / f"screen-dups-{date}.json"
    mapping: dict[str, str] = {}
    if map_path.exists():
        try:
            loaded = json.loads(map_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                mapping = {str(key): str(value) for key, value in loaded.items()}
        except (OSError, json.JSONDecodeError):
            mapping = {}
    mapping.update({str(duplicate): str(kept) for duplicate, kept in new_matches.items()})

    analyses = load_analyses(journal_root, date)
    written: list[pathlib.Path] = []
    for duplicate, kept in mapping.items():
        duplicate_image = pathlib.Path(duplicate)
        if screen_path(journal_root, duplicate_image).exists():
            continue
        analysis = analyses.get(kept)
        if analysis is None:
            continue
        written.append(write_screen_markdown(journal_root, duplicate_image, analysis, unchanged_since=_clock(pathlib.Path(kept))))

    map_path.parent.mkdir(parents=True, exist_ok=True)
    map_path.write_text(json.dumps(mapping, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return written
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_screen_markdown.py tests/test_vision_prompts.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/analysis/screen_markdown.py config/prompts.json tests/test_screen_markdown.py tests/test_vision_prompts.py && git commit -m "feat: render a Markdown file per screenshot and ask the vision model for screen details"
```

---

### Task 4: analyze_screenshots writes a file for every screenshot

**Files:**
- Modify: `src/analysis/analyze_screenshots.py` (imports; `main` lines ~184-240)
- Test: `tests/test_analyze_screenshots_queue.py`

**Interfaces:**
- Consumes: `deduplicate_with_matches` (Task 2); `screen_path`, `write_screen_markdown`, `reconcile_duplicates` (Task 3).
- Produces: after each run, every analysed screenshot has `screens/DATE/HH/<clock>.md`; every dedupe-dropped screenshot has one once its kept screenshot is analysed; screenshots that already have a file are never re-queued; each vision result is appended to the `raw/visual-<screenshot's own date>.jsonl`.

- [ ] **Step 1: Write the failing tests**

Read `_run` and `_make_journal` at the top of `tests/test_analyze_screenshots_queue.py` (they already exist). Add these tests to the existing test class, plus `import os` at the top of the file:

```python
    def test_successful_analysis_writes_a_markdown_file_for_the_screenshot(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = _make_journal(Path(directory))
            analysis = {"summary": "coding", "screen_details": ["editor shows main.py"]}
            with mock.patch.object(module, "call_vision", return_value=analysis):
                _run(journal)

            target = journal / "screens" / "2026-01-01" / "00" / "00-00-00-000.md"
            self.assertTrue(target.exists())
            text = target.read_text(encoding="utf-8")
            self.assertIn("coding", text)
            self.assertIn("- editor shows main.py", text)

    def test_near_duplicate_screenshot_gets_an_unchanged_file_without_a_second_call(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = _make_journal(Path(directory))
            screenshot_dir = journal / "screenshots" / "2026-01-01"
            first = screenshot_dir / "screen-00-00-00-000.jpg"
            second = screenshot_dir / "screen-00-01-00-000.jpg"
            Image.new("RGB", (32, 32), color="white").save(second, "JPEG")
            os.utime(first, (1000, 1000))
            os.utime(second, (2000, 2000))
            with mock.patch.object(module, "call_vision", return_value={"summary": "coding"}) as mocked:
                _run(journal)

            self.assertEqual(mocked.call_count, 1)
            duplicate = journal / "screens" / "2026-01-01" / "00" / "00-01-00-000.md"
            self.assertTrue(duplicate.exists())
            self.assertIn("Unchanged since 00:00:00.", duplicate.read_text(encoding="utf-8"))

    def test_screenshot_that_already_has_a_file_is_not_queued_again(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = _make_journal(Path(directory))
            existing = journal / "screens" / "2026-01-01" / "00" / "00-00-00-000.md"
            existing.parent.mkdir(parents=True)
            existing.write_text("# Screen\n", encoding="utf-8")
            with mock.patch.object(module, "call_vision", return_value={"summary": "coding"}) as mocked:
                _run(journal)

            mocked.assert_not_called()

    def test_result_is_filed_under_the_screenshots_own_date(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = _make_journal(Path(directory))
            with mock.patch.object(module, "call_vision", return_value={"summary": "coding"}):
                _run(journal)

            self.assertTrue((journal / "raw" / "visual-2026-01-01.jsonl").exists())
```

(Note: `_make_journal` puts the image in `screenshots/2026-01-01/` and `_run` runs with `--date 2026-01-01`; if `_run` uses another date, adjust the assertions' dates to match `_run`'s `--date`.)

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_analyze_screenshots_queue.py -q`
Expected: the new tests FAIL (no `screens/` files; duplicate analysed twice).

- [ ] **Step 3: Implement**

In `src/analysis/analyze_screenshots.py`:

1. Imports: replace `from src.analysis.screenshot_fingerprint import deduplicate_images` with
```python
from src.analysis.screen_markdown import reconcile_duplicates, screen_path, write_screen_markdown
from src.analysis.screenshot_fingerprint import deduplicate_with_matches
```
2. Replace the candidate selection in `main` (the lines from `analyzed = load_analyzed_screenshots(output)` through the `deduplicate_images(...)` line) with:
```python
    analyzed = load_analyzed_screenshots(output)
    reconcile_duplicates(journal, args.date, {})
    candidates = [image for image in all_images if str(image) not in analyzed and not screen_path(journal, image).exists()]
    candidates, duplicates = deduplicate_with_matches(candidates, threshold=max(0, int(screenshot_config.get("dedupeHammingThreshold", 4))))
    reconcile_duplicates(journal, args.date, duplicates)
```
3. Replace the block that writes results (`with output.open("a", encoding="utf-8") as handle: ... handle.write(...)`) with:
```python
    by_date: dict[str, list[dict]] = {}
    for result in results:
        by_date.setdefault(pathlib.Path(result["screenshot"]).parent.name, []).append(result)
    for result_date, items in by_date.items():
        with (raw_dir / f"visual-{result_date}.jsonl").open("a", encoding="utf-8") as handle:
            for result in items:
                handle.write(json.dumps(result, ensure_ascii=False) + "\n")
    for result in results:
        write_screen_markdown(journal, pathlib.Path(result["screenshot"]), result["analysis"])
    reconcile_duplicates(journal, args.date, {})
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_analyze_screenshots_queue.py -q` then the full suite `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/analysis/analyze_screenshots.py tests/test_analyze_screenshots_queue.py && git commit -m "feat: write a Markdown file for every screenshot, including near-duplicates"
```

---

### Task 5: Shared report prompt and renderer

**Files:**
- Create: `src/analysis/report_levels.py`
- Create: `src/analysis/report_render.py`
- Test: `tests/test_report_levels.py` (new), `tests/test_report_render.py` (new)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `report_levels.LEVELS = ("hourly", "daily", "weekly")`; `report_levels.build_prompt(level: str) -> str` (raises `KeyError` for an unknown level).
  - `report_render.NARRATIVE_MARKER = "## LLM narrative"`
  - `report_render.render_sections(narrative: dict) -> str`; `render_report(title: str, narrative: dict) -> str`; `upsert_daily_narrative(markdown: str, narrative: dict) -> str`; `daily_narrative_text(markdown: str) -> str | None`; `with_input_stamp(text: str, digest: str) -> str`; `read_input_stamp(text: str) -> str | None`; `strip_input_stamp(text: str) -> str`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_report_levels.py`:

```python
import unittest

from src.analysis.report_levels import LEVELS, build_prompt


class BuildPromptTests(unittest.TestCase):
    def test_all_levels_share_the_same_json_shape(self):
        for level in LEVELS:
            prompt = build_prompt(level)
            for key in ('"summary"', '"on_screen"', '"timeline"', '"patterns"', '"next_actions"'):
                self.assertIn(key, prompt)

    def test_no_level_asks_for_confidence(self):
        for level in LEVELS:
            self.assertNotIn("confidence", build_prompt(level).lower())

    def test_levels_differ_in_depth_and_source(self):
        hourly, daily, weekly = (build_prompt(level) for level in LEVELS)

        self.assertIn("one hour", hourly)
        self.assertIn("every distinct screen", hourly)
        self.assertIn("one day", daily)
        self.assertIn("hourly reports", daily)
        self.assertIn("one week", weekly)
        self.assertIn("daily reports", weekly)
        self.assertEqual(len({hourly, daily, weekly}), 3)

    def test_privacy_and_readability_rules_are_stated(self):
        prompt = build_prompt("hourly")

        self.assertIn("never quote message text", prompt)
        self.assertIn("local times", prompt)

    def test_unknown_level_raises(self):
        with self.assertRaises(KeyError):
            build_prompt("monthly")


if __name__ == "__main__":
    unittest.main()
```

Create `tests/test_report_render.py`:

```python
import unittest

from src.analysis.report_render import (
    NARRATIVE_MARKER,
    daily_narrative_text,
    read_input_stamp,
    render_report,
    render_sections,
    strip_input_stamp,
    upsert_daily_narrative,
    with_input_stamp,
)

NARRATIVE = {
    "summary": "Worked on the pipeline.",
    "on_screen": ["Kibana dashboard kassa-log", "Terminal running pytest"],
    "timeline": [{"time": "09:15", "activity": "Started coding"}],
    "patterns": ["Steady focus"],
    "next_actions": ["Write tests"],
}


class RenderTests(unittest.TestCase):
    def test_sections_appear_in_the_shared_order(self):
        text = render_report("Hourly journal — 2026-09-26 09:00", NARRATIVE)

        self.assertTrue(text.startswith("# Hourly journal — 2026-09-26 09:00\n\nWorked on the pipeline.\n"))
        order = [text.index(heading) for heading in ("### On screen", "### Timeline", "### Patterns", "### Next actions")]
        self.assertEqual(order, sorted(order))
        self.assertIn("- Kibana dashboard kassa-log", text)
        self.assertIn("- 09:15 — Started coding", text)

    def test_no_confidence_line_and_no_legacy_sections(self):
        text = render_report("T", {**NARRATIVE, "confidence": 0.9, "accomplishments": ["x"], "blockers": ["y"]})

        self.assertNotIn("confidence", text.lower())
        self.assertNotIn("Accomplishments", text)
        self.assertNotIn("Blockers", text)

    def test_empty_sections_are_omitted(self):
        text = render_report("T", {"summary": "Quiet."})

        self.assertNotIn("###", text)

    def test_bare_string_sections_and_string_timeline_entries_are_tolerated(self):
        text = render_report("T", {"summary": "s", "on_screen": "One screen", "timeline": ["10:00 something"], "patterns": None})

        self.assertIn("- One screen", text)
        self.assertIn("- 10:00 something", text)
        self.assertNotIn("### Patterns", text)


class DailyTests(unittest.TestCase):
    def test_upsert_keeps_the_scaffold_and_replaces_the_previous_narrative(self):
        scaffold = "# Automatic Activity Journal — 2026-09-26\n\n## Applications\n\n- Code\n"
        first = upsert_daily_narrative(scaffold, {"summary": "First."})
        second = upsert_daily_narrative(first, NARRATIVE)

        self.assertIn("## Applications", second)
        self.assertEqual(second.count(NARRATIVE_MARKER), 1)
        self.assertIn("Worked on the pipeline.", second)
        self.assertNotIn("First.", second)

    def test_daily_narrative_text_returns_body_without_marker_or_stamp(self):
        markdown = with_input_stamp(upsert_daily_narrative("# D\n", NARRATIVE), "abc123")

        body = daily_narrative_text(markdown)

        self.assertTrue(body.startswith("Worked on the pipeline."))
        self.assertNotIn(NARRATIVE_MARKER, body)
        self.assertNotIn("<!--", body)

    def test_daily_without_marker_has_no_narrative(self):
        self.assertIsNone(daily_narrative_text("# Automatic Activity Journal — 2026-09-26\n"))


class StampTests(unittest.TestCase):
    def test_stamp_round_trip(self):
        stamped = with_input_stamp("# T\n\nBody.\n", "deadbeef0123")

        self.assertEqual(read_input_stamp(stamped), "deadbeef0123")
        self.assertEqual(strip_input_stamp(stamped), "# T\n\nBody.\n")

    def test_restamping_replaces_the_old_stamp(self):
        once = with_input_stamp("# T\n", "aaaa")
        twice = with_input_stamp(once, "bbbb")

        self.assertEqual(read_input_stamp(twice), "bbbb")
        self.assertEqual(twice.count("<!--"), 1)

    def test_no_stamp_reads_as_none(self):
        self.assertIsNone(read_input_stamp("# T\n"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_report_levels.py tests/test_report_render.py -q`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement**

Create `src/analysis/report_levels.py`:

```python
"""One prompt builder for the hourly, daily and weekly reports: same JSON shape, different depth."""

from __future__ import annotations

LEVELS = ("hourly", "daily", "weekly")

_SHAPE = """Return only valid JSON with this shape:
{{
  "summary": "one concise factual paragraph",
  "on_screen": ["concrete things that were visible on screen: applications, pages, dashboards, tickets, files, terminal commands, chat topics"],
  "timeline": [{{"time": "{time_hint}", "activity": "what was observed"}}],
  "patterns": ["useful observed patterns"],
  "next_actions": ["reasonable next actions grounded in the sources, if any"]
}}"""

_RULES = """Report only what the sources show. Do not invent intent, people, conversations, or conclusions. Keep private message content summarized: never quote message text, and omit passwords, tokens and keys. Write plain human-readable text: local times, real application and page names, no identifiers."""

_LEVELS = {
    "hourly": {
        "unit": "one hour",
        "sources": "per-screenshot notes describing what was on screen, plus a list of the active windows for that hour",
        "time_hint": "HH:MM",
        "depth": "Be specific and fine-grained. List every distinct screen in on_screen with the visible application, page, panel, file, ticket, dashboard or command names and other concrete details. Follow the actual sequence in the timeline, noting when the screen changed.",
    },
    "daily": {
        "unit": "one day",
        "sources": "the hourly reports of that day",
        "time_hint": "HH:MM",
        "depth": "Group the day by task or application. on_screen lists the main things seen in each block of work, not every screen. The timeline has one entry per block of work. Say how many hours the sources cover if the day is incomplete.",
    },
    "weekly": {
        "unit": "one week",
        "sources": "the daily reports of that week",
        "time_hint": "weekday and date, e.g. Tue 2026-09-22",
        "depth": "Stay general. on_screen names only the few notable screens or themes of the week. The timeline holds only the week's most significant moments. Do not merge the daily reports into a log.",
    },
}


def build_prompt(level: str) -> str:
    spec = _LEVELS[level]
    return (
        f"You are writing a factual personal activity report covering {spec['unit']}. "
        f"Your sources are {spec['sources']}.\n"
        f"{_SHAPE.format(time_hint=spec['time_hint'])}\n"
        f"{spec['depth']}\n"
        f"{_RULES}"
    )
```

Create `src/analysis/report_render.py`:

```python
"""Single Markdown renderer for the hourly, daily and weekly reports."""

from __future__ import annotations

import re

NARRATIVE_MARKER = "## LLM narrative"
SECTIONS = (("On screen", "on_screen"), ("Timeline", "timeline"), ("Patterns", "patterns"), ("Next actions", "next_actions"))
_STAMP = re.compile(r"\s*<!-- input: ([0-9a-f]+) -->\s*")


def _items(value) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, (list, tuple)):
        return []
    items = []
    for entry in value:
        if isinstance(entry, dict):
            text = f"{entry.get('time', '')} — {entry.get('activity', '')}".strip(" —")
        else:
            text = str(entry).strip()
        if text:
            items.append(text)
    return items


def render_sections(narrative: dict) -> str:
    summary = str(narrative.get("summary") or "No summary returned.").strip()
    lines = [summary, ""]
    for title, key in SECTIONS:
        items = _items(narrative.get(key))
        if not items:
            continue
        lines.extend([f"### {title}", ""])
        lines.extend(f"- {item}" for item in items)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_report(title: str, narrative: dict) -> str:
    return f"# {title}\n\n{render_sections(narrative)}"


def read_input_stamp(text: str) -> str | None:
    match = _STAMP.search(text)
    return match.group(1) if match else None


def strip_input_stamp(text: str) -> str:
    if not text.strip():
        return ""
    return _STAMP.sub("\n", text).strip() + "\n"


def with_input_stamp(text: str, digest: str) -> str:
    return strip_input_stamp(text).rstrip("\n") + f"\n\n<!-- input: {digest} -->\n"


def upsert_daily_narrative(markdown: str, narrative: dict) -> str:
    markdown = strip_input_stamp(markdown)
    before = markdown.split(NARRATIVE_MARKER, 1)[0].rstrip() if NARRATIVE_MARKER in markdown else markdown.rstrip()
    return f"{before}\n\n{NARRATIVE_MARKER}\n\n{render_sections(narrative)}"


def daily_narrative_text(markdown: str) -> str | None:
    if NARRATIVE_MARKER not in markdown:
        return None
    body = strip_input_stamp(markdown.split(NARRATIVE_MARKER, 1)[1]).strip()
    return body or None
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_report_levels.py tests/test_report_render.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/analysis/report_levels.py src/analysis/report_render.py tests/test_report_levels.py tests/test_report_render.py && git commit -m "feat: shared report prompt and renderer for hourly, daily and weekly levels"
```

---

### Task 6: Rewrite synthesize_period as the hourly → daily → weekly chain

**Files:**
- Modify (full rewrite): `src/analysis/synthesize_period.py`
- Delete: `src/analysis/synthesize_journal.py`, `tests/test_synthesize_journal.py`
- Rewrite: `tests/test_synthesize_period.py`

**Interfaces:**
- Consumes: `build_prompt` (Task 5), `render_report`, `upsert_daily_narrative`, `daily_narrative_text`, `read_input_stamp`, `strip_input_stamp`, `with_input_stamp` (Task 5); screen files from Task 3/4 (`screens/DATE/HH/*.md`); `narrative.parse_model_json`, `narrative.truncate`; `model_client.call_chat_completions`, `resolve_provider`, `ProviderError`; `heartbeat.write_heartbeat`.
- Produces (all in `src.analysis.synthesize_period`):
  - `STAGE_KEYS = {"hourly": "hourlySynthesis", "daily": "journalSynthesis", "weekly": "weeklySynthesis"}`
  - `week_dates(date: str) -> tuple[int, int, list[str]]` (unchanged: ISO year, ISO week, Monday..date)
  - `activity_lines(journal_root, date, hour) -> list[str]`
  - `hours_with_input(journal_root, date) -> list[int]`
  - `gather_hour(journal_root, date, hour) -> str | None`, `gather_day(journal_root, date) -> str | None`, `gather_week(journal_root, date) -> str | None`
  - `call_report_model(provider: dict, level: str, source_text: str) -> dict` (one retry on invalid JSON, then `ValueError`)
  - `build_report(provider, journal_root, level, date, hour=None) -> dict` returning `{"status": "complete"|"unchanged"|"no-input", "path": str}` (`path` absent for `no-input`)
  - `main() -> int` with CLI `--journal-root --config --period hourly|daily|weekly --date`; returns 1 if any report failed, else 0.
  - Freshness: `<!-- input: <sha1[:12] of the gathered source text> -->` stamp; a report is rebuilt only when the stamp differs. **Failure is retried simply by the next run finding the stamp stale** (this replaces the `queue-period` retry in the spec; the spec is updated in Task 9).

- [ ] **Step 1: Write the failing tests**

Replace all of `tests/test_synthesize_period.py` with:

```python
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.analysis.report_render import NARRATIVE_MARKER, read_input_stamp
from src.analysis.synthesize_period import (
    STAGE_KEYS,
    activity_lines,
    build_report,
    call_report_model,
    gather_day,
    gather_hour,
    gather_week,
    hours_with_input,
    main,
    week_dates,
)

DATE = "2026-09-26"
CANNED = json.dumps({
    "summary": "Worked on dashboards.",
    "on_screen": ["Kibana dashboard kassa-log"],
    "timeline": [{"time": "10:21", "activity": "Opened Kibana"}],
    "patterns": ["Log review"],
    "next_actions": ["Check errors"],
})
PROVIDER = {"name": "test"}


def _screen(journal: Path, date: str, hour: int, clock: str, body: str = "Viewing Kibana.") -> Path:
    path = journal / "screens" / date / f"{hour:02d}" / f"{clock}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# Screen — {date} {clock[:8].replace('-', ':')}\n\n{body}\n", encoding="utf-8")
    return path


def _activity(journal: Path, date: str, events: list[dict]) -> None:
    raw = journal / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / f"activity-{date}.jsonl").write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")


def _window(stamp: str, process: str | None, title: str | None = None, executable: str | None = None) -> dict:
    return {"source": "foreground-window", "localTimestamp": f"{stamp}+03:30", "process": process, "executable": executable, "windowTitle": title}


class WeekDatesTests(unittest.TestCase):
    def test_returns_monday_through_the_given_date(self):
        year, week, dates = week_dates("2026-08-27")
        self.assertEqual(dates, ["2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27"])
        self.assertEqual((year, week), (2026, 35))


class ActivityLinesTests(unittest.TestCase):
    def test_collapses_consecutive_identical_windows_and_ignores_other_hours(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            _activity(journal, DATE, [
                _window("2026-09-26T10:00:10", "remmina", "311", "/usr/bin/remmina"),
                _window("2026-09-26T10:01:10", "remmina", "311", "/usr/bin/remmina"),
                _window("2026-09-26T10:02:10", "chrome", "Kibana", "/opt/google/chrome/chrome"),
                _window("2026-09-26T11:00:10", "code", "main.py"),
            ])

            lines = activity_lines(journal, DATE, 10)

            self.assertEqual(lines, ["10:00–10:01 remmina — 311", "10:02 chrome — Kibana"])

    def test_events_without_a_process_are_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            _activity(journal, DATE, [_window("2026-09-26T18:13:00", None)])

            self.assertEqual(activity_lines(journal, DATE, 18), [])


class HoursWithInputTests(unittest.TestCase):
    def test_union_of_screen_hours_and_activity_hours(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            _screen(journal, DATE, 9, "09-05-16-374")
            _activity(journal, DATE, [_window("2026-09-26T14:00:10", "code", "x"), _window("2026-09-26T15:00:10", None)])

            self.assertEqual(hours_with_input(journal, DATE), [9, 14])


class GatherTests(unittest.TestCase):
    def test_hour_with_nothing_returns_none(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(gather_hour(Path(directory), DATE, 10))

    def test_hour_with_only_no_active_window_events_returns_none(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            _activity(journal, DATE, [_window("2026-09-26T18:13:00", None)])

            self.assertIsNone(gather_hour(journal, DATE, 18))

    def test_hour_includes_screens_and_activity_and_counts_repeats_without_including_them(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            _screen(journal, DATE, 10, "10-21-15-521", "Viewing Kibana.")
            _screen(journal, DATE, 10, "10-22-15-521", "Viewing Kibana.\n\nUnchanged since 10:21:15.")
            _activity(journal, DATE, [_window("2026-09-26T10:21:00", "chrome", "Kibana")])

            text = gather_hour(journal, DATE, 10)

            self.assertIn("10:21:15", text)
            self.assertNotIn("10:22:15", text)
            self.assertIn("1 further screenshot(s) were unchanged repeats", text)
            self.assertIn("chrome — Kibana", text)

    def test_hour_source_text_ignores_the_stamp_comment_in_screen_files(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            path = _screen(journal, DATE, 10, "10-21-15-521")
            path.write_text(path.read_text(encoding="utf-8") + "\n<!-- input: abc123 -->\n", encoding="utf-8")

            self.assertNotIn("<!--", gather_hour(journal, DATE, 10))

    def test_day_reads_only_hourly_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            (journal / "hourly" / DATE).mkdir(parents=True)
            (journal / "hourly" / DATE / "10.md").write_text("# Hourly journal — 2026-09-26 10:00\n\nKibana hour.\n", encoding="utf-8")
            (journal / "hourly" / DATE / "11.md").write_text("# Hourly journal — 2026-09-26 11:00\n\nCoding hour.\n", encoding="utf-8")
            _screen(journal, DATE, 12, "12-00-00-000", "should not appear")

            text = gather_day(journal, DATE)

            self.assertLess(text.index("Kibana hour."), text.index("Coding hour."))
            self.assertNotIn("should not appear", text)
            self.assertIsNone(gather_day(journal, "2026-01-01"))

    def test_week_reads_daily_narratives_and_skips_days_without_one(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            (journal / "daily").mkdir()
            (journal / "daily" / "2026-09-21.md").write_text(f"# D\n\n## Applications\n\nscaffold-only\n\n{NARRATIVE_MARKER}\n\nMonday summary.\n", encoding="utf-8")
            (journal / "daily" / "2026-09-22.md").write_text("# D\n\n## Applications\n\nno narrative yet\n", encoding="utf-8")

            text = gather_week(journal, "2026-09-23")

            self.assertIn("Monday summary.", text)
            self.assertIn("2026-09-21", text)
            self.assertNotIn("scaffold-only", text)
            self.assertNotIn("no narrative yet", text)

    def test_week_with_no_narratives_returns_none(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(gather_week(Path(directory), "2026-09-23"))


class CallReportModelTests(unittest.TestCase):
    def test_retries_once_on_invalid_json_then_succeeds(self):
        with mock.patch("src.analysis.synthesize_period.call_chat_completions", side_effect=['{"summary": "x",', CANNED]) as mocked:
            result = call_report_model(PROVIDER, "hourly", "sources")

        self.assertEqual(result["summary"], "Worked on dashboards.")
        self.assertEqual(mocked.call_count, 2)
        retry_messages = mocked.call_args.args[1]
        self.assertEqual(retry_messages[-1]["role"], "user")
        self.assertIn("not valid JSON", retry_messages[-1]["content"])

    def test_two_invalid_responses_raise_value_error(self):
        with mock.patch("src.analysis.synthesize_period.call_chat_completions", return_value="nope"):
            with self.assertRaises(ValueError):
                call_report_model(PROVIDER, "hourly", "sources")

    def test_system_prompt_is_the_level_prompt(self):
        from src.analysis.report_levels import build_prompt

        with mock.patch("src.analysis.synthesize_period.call_chat_completions", return_value=CANNED) as mocked:
            call_report_model(PROVIDER, "weekly", "sources")

        self.assertEqual(mocked.call_args.args[1][0]["content"], build_prompt("weekly"))


class BuildReportTests(unittest.TestCase):
    def test_hourly_report_is_written_with_shared_format_and_stamp(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            _screen(journal, DATE, 10, "10-21-15-521")
            with mock.patch("src.analysis.synthesize_period.call_chat_completions", return_value=CANNED):
                result = build_report(PROVIDER, journal, "hourly", DATE, hour=10)

            path = journal / "hourly" / DATE / "10.md"
            self.assertEqual(result, {"status": "complete", "path": str(path)})
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("# Hourly journal — 2026-09-26 10:00\n\nWorked on dashboards.\n"))
            self.assertIn("### On screen", text)
            self.assertIsNotNone(read_input_stamp(text))
            self.assertNotIn("confidence", text.lower())

    def test_unchanged_input_skips_the_model_and_changed_input_rebuilds(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            _screen(journal, DATE, 10, "10-21-15-521")
            with mock.patch("src.analysis.synthesize_period.call_chat_completions", return_value=CANNED) as mocked:
                build_report(PROVIDER, journal, "hourly", DATE, hour=10)
                second = build_report(PROVIDER, journal, "hourly", DATE, hour=10)
                self.assertEqual(second["status"], "unchanged")
                self.assertEqual(mocked.call_count, 1)

                _screen(journal, DATE, 10, "10-30-00-000", "A new screen.")
                third = build_report(PROVIDER, journal, "hourly", DATE, hour=10)
                self.assertEqual(third["status"], "complete")
                self.assertEqual(mocked.call_count, 2)

    def test_no_input_writes_nothing_and_never_calls_the_model(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            with mock.patch("src.analysis.synthesize_period.call_chat_completions") as mocked:
                result = build_report(PROVIDER, journal, "hourly", DATE, hour=3)

            mocked.assert_not_called()
            self.assertEqual(result, {"status": "no-input"})
            self.assertFalse((journal / "hourly").exists())

    def test_failed_model_call_leaves_no_file_so_the_next_run_retries(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            _screen(journal, DATE, 10, "10-21-15-521")
            with mock.patch("src.analysis.synthesize_period.call_chat_completions", return_value="nope"):
                with self.assertRaises(ValueError):
                    build_report(PROVIDER, journal, "hourly", DATE, hour=10)

            self.assertFalse((journal / "hourly" / DATE / "10.md").exists())

    def test_daily_report_keeps_the_scaffold_and_adds_the_narrative_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            (journal / "hourly" / DATE).mkdir(parents=True)
            (journal / "hourly" / DATE / "10.md").write_text("# Hourly journal — 2026-09-26 10:00\n\nKibana hour.\n", encoding="utf-8")
            (journal / "daily").mkdir()
            (journal / "daily" / f"{DATE}.md").write_text("# Automatic Activity Journal — 2026-09-26\n\n## Applications\n\n- Code\n", encoding="utf-8")
            with mock.patch("src.analysis.synthesize_period.call_chat_completions", return_value=CANNED):
                result = build_report(PROVIDER, journal, "daily", DATE)

            text = (journal / "daily" / f"{DATE}.md").read_text(encoding="utf-8")
            self.assertEqual(result["status"], "complete")
            self.assertIn("## Applications", text)
            self.assertIn(NARRATIVE_MARKER, text)
            self.assertIn("### On screen", text)
            self.assertIsNotNone(read_input_stamp(text))

    def test_daily_rewritten_by_the_scaffold_is_rebuilt_even_if_input_is_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            (journal / "hourly" / DATE).mkdir(parents=True)
            (journal / "hourly" / DATE / "10.md").write_text("# Hourly\n\nKibana hour.\n", encoding="utf-8")
            with mock.patch("src.analysis.synthesize_period.call_chat_completions", return_value=CANNED) as mocked:
                build_report(PROVIDER, journal, "daily", DATE)
                (journal / "daily" / f"{DATE}.md").write_text("# Automatic Activity Journal — 2026-09-26\n", encoding="utf-8")
                result = build_report(PROVIDER, journal, "daily", DATE)

            self.assertEqual(result["status"], "complete")
            self.assertEqual(mocked.call_count, 2)

    def test_weekly_report_path_uses_iso_week(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            (journal / "daily").mkdir()
            (journal / "daily" / "2026-09-21.md").write_text(f"# D\n\n{NARRATIVE_MARKER}\n\nMonday summary.\n", encoding="utf-8")
            with mock.patch("src.analysis.synthesize_period.call_chat_completions", return_value=CANNED):
                result = build_report(PROVIDER, journal, "weekly", "2026-09-23")

            self.assertEqual(result["path"], str(journal / "weekly" / "2026-W39.md"))
            self.assertTrue(result["path"].endswith("2026-W39.md"))
            self.assertTrue(Path(result["path"]).read_text(encoding="utf-8").startswith("# Weekly journal — 2026-W39\n"))


def _config(journal: Path, stage: str = "hourlySynthesis", **stage_overrides) -> Path:
    config_path = journal.parent / "settings.json"
    config_path.write_text(json.dumps({
        stage: {"enabled": True, "activeProvider": "test-provider", **stage_overrides},
        "providers": {"test-provider": {"endpoint": "http://x", "model": "m"}},
    }), encoding="utf-8")
    return config_path


def _run_main(journal: Path, config_path: Path, period: str, date: str = DATE) -> int:
    old_argv = sys.argv
    sys.argv = ["synthesize_period", "--journal-root", str(journal), "--config", str(config_path), "--period", period, "--date", date]
    try:
        return main()
    finally:
        sys.argv = old_argv


class MainTests(unittest.TestCase):
    def test_stage_keys(self):
        self.assertEqual(STAGE_KEYS, {"hourly": "hourlySynthesis", "daily": "journalSynthesis", "weekly": "weeklySynthesis"})

    def test_hourly_builds_every_hour_with_input_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "journal"
            journal.mkdir()
            _screen(journal, DATE, 9, "09-05-16-374")
            _screen(journal, DATE, 14, "14-10-00-000")
            config_path = _config(journal)
            with mock.patch("src.analysis.synthesize_period.call_chat_completions", return_value=CANNED) as mocked:
                first = _run_main(journal, config_path, "hourly")
                second = _run_main(journal, config_path, "hourly")

            self.assertEqual((first, second), (0, 0))
            self.assertEqual(mocked.call_count, 2)
            self.assertTrue((journal / "hourly" / DATE / "09.md").exists())
            self.assertTrue((journal / "hourly" / DATE / "14.md").exists())

    def test_disabled_stage_does_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "journal"
            journal.mkdir()
            _screen(journal, DATE, 9, "09-05-16-374")
            config_path = _config(journal, enabled=False)
            with mock.patch("src.analysis.synthesize_period.call_chat_completions") as mocked:
                exit_code = _run_main(journal, config_path, "hourly")

            self.assertEqual(exit_code, 0)
            mocked.assert_not_called()

    def test_missing_provider_returns_one_and_writes_a_failed_heartbeat(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "journal"
            journal.mkdir()
            config_path = root / "settings.json"
            config_path.write_text(json.dumps({"hourlySynthesis": {"enabled": True}}), encoding="utf-8")

            exit_code = _run_main(journal, config_path, "hourly")

            self.assertEqual(exit_code, 1)
            heartbeat = json.loads((journal / "health" / "hourly-synthesis.json").read_text(encoding="utf-8"))
            self.assertEqual(heartbeat["status"], "failed")

    def test_model_failure_returns_one_and_a_later_run_retries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "journal"
            journal.mkdir()
            _screen(journal, DATE, 9, "09-05-16-374")
            config_path = _config(journal)
            with mock.patch("src.analysis.synthesize_period.call_chat_completions", return_value="nope"):
                failed = _run_main(journal, config_path, "hourly")
            with mock.patch("src.analysis.synthesize_period.call_chat_completions", return_value=CANNED):
                recovered = _run_main(journal, config_path, "hourly")

            self.assertEqual((failed, recovered), (1, 0))
            self.assertTrue((journal / "hourly" / DATE / "09.md").exists())

    def test_daily_period_uses_the_journal_synthesis_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "journal"
            (journal / "hourly" / DATE).mkdir(parents=True)
            (journal / "hourly" / DATE / "10.md").write_text("# Hourly\n\nKibana hour.\n", encoding="utf-8")
            config_path = _config(journal, stage="journalSynthesis")
            with mock.patch("src.analysis.synthesize_period.call_chat_completions", return_value=CANNED):
                exit_code = _run_main(journal, config_path, "daily")

            self.assertEqual(exit_code, 0)
            self.assertIn(NARRATIVE_MARKER, (journal / "daily" / f"{DATE}.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
```

Also delete the old daily test file: `git rm tests/test_synthesize_journal.py` (its `parse_model_json` case is already covered by `tests/test_narrative.py`).

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_synthesize_period.py -q`
Expected: FAIL (`ImportError: cannot import name 'STAGE_KEYS'` …).

- [ ] **Step 3: Implement**

Replace the whole of `src/analysis/synthesize_period.py` with:

```python
#!/usr/bin/env python3
"""Build hourly, daily and weekly reports; each level compacts the Markdown of the level below."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re

from src.analysis.narrative import parse_model_json, truncate
from src.analysis.report_levels import LEVELS, build_prompt
from src.analysis.report_render import (
    daily_narrative_text,
    read_input_stamp,
    render_report,
    strip_input_stamp,
    upsert_daily_narrative,
    with_input_stamp,
)
from src.infra.heartbeat import write_heartbeat
from src.providers.model_client import ProviderError, call_chat_completions, resolve_provider

STAGE_KEYS = {"hourly": "hourlySynthesis", "daily": "journalSynthesis", "weekly": "weeklySynthesis"}
MAX_INPUT_CHARS = {"hourly": 24000, "daily": 16000, "weekly": 16000}
MAX_ACTIVITY_LINES = 40
_REPEAT_MARKER = "\nUnchanged since "


def week_dates(date: str) -> tuple[int, int, list[str]]:
    parsed = dt.date.fromisoformat(date)
    year, week, weekday = parsed.isocalendar()
    monday = parsed - dt.timedelta(days=weekday - 1)
    dates = []
    day = monday
    while day <= parsed:
        dates.append(day.isoformat())
        day += dt.timedelta(days=1)
    return year, week, dates


def _activity_records(journal_root: pathlib.Path, date: str):
    path = journal_root / "raw" / f"activity-{date}.jsonl"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        stamp = record.get("localTimestamp")
        if record.get("source") != "foreground-window" or not record.get("process") or not isinstance(stamp, str) or len(stamp) < 16:
            continue
        if stamp[:10] != date or not stamp[11:13].isdigit():
            continue
        yield record, int(stamp[11:13]), stamp[11:16]


def activity_lines(journal_root: pathlib.Path, date: str, hour: int) -> list[str]:
    runs: list[list[str]] = []
    for record, record_hour, clock in _activity_records(journal_root, date):
        if record_hour != hour:
            continue
        app = pathlib.Path(str(record.get("executable") or "")).stem or str(record["process"])
        title = truncate(record.get("windowTitle") or "", 60)
        if runs and runs[-1][2] == app and runs[-1][3] == title:
            runs[-1][1] = clock
        else:
            runs.append([clock, clock, app, title])
    lines = [
        f"{start if start == end else f'{start}–{end}'} {app}" + (f" — {title}" if title else "")
        for start, end, app, title in runs
    ]
    if len(lines) > MAX_ACTIVITY_LINES:
        step = -(-len(lines) // MAX_ACTIVITY_LINES)
        lines = lines[::step]
    return lines


def _screen_dir(journal_root: pathlib.Path, date: str, hour: int) -> pathlib.Path:
    return journal_root / "screens" / date / f"{hour:02d}"


def hours_with_input(journal_root: pathlib.Path, date: str) -> list[int]:
    hours: set[int] = set()
    screens = journal_root / "screens" / date
    if screens.exists():
        for directory in screens.iterdir():
            if directory.is_dir() and directory.name.isdigit() and any(directory.glob("*.md")):
                hours.add(int(directory.name))
    for _, record_hour, _ in _activity_records(journal_root, date):
        hours.add(record_hour)
    return sorted(hours)


def _fit(parts: list[str], limit: int) -> list[str]:
    while len(parts) > 2 and len("\n\n".join(parts)) > limit:
        parts = parts[::2]
    return parts


def gather_hour(journal_root: pathlib.Path, date: str, hour: int) -> str | None:
    directory = _screen_dir(journal_root, date, hour)
    files = sorted(directory.glob("*.md")) if directory.exists() else []
    activity = activity_lines(journal_root, date, hour)
    if not files and not activity:
        return None
    screens: list[str] = []
    repeats = 0
    for file in files:
        text = strip_input_stamp(file.read_text(encoding="utf-8")).strip()
        if _REPEAT_MARKER in text:
            repeats += 1
        else:
            screens.append(text)
    header = f"Hour {hour:02d}:00 on {date}."
    activity_block = "## Active windows\n\n" + "\n".join(f"- {line}" for line in activity) if activity else ""
    budget = MAX_INPUT_CHARS["hourly"] - len(activity_block)
    parts = [header, f"## Screens ({len(screens)} analysed)"] + _fit(screens, budget)
    if repeats:
        parts.append(f"{repeats} further screenshot(s) were unchanged repeats of the screens above.")
    if activity_block:
        parts.append(activity_block)
    return "\n\n".join(parts)


def gather_day(journal_root: pathlib.Path, date: str) -> str | None:
    directory = journal_root / "hourly" / date
    files = sorted(directory.glob("*.md")) if directory.exists() else []
    parts = [strip_input_stamp(file.read_text(encoding="utf-8")).strip() for file in files]
    parts = [part for part in parts if part]
    if not parts:
        return None
    return "\n\n".join([f"Day {date}, {len(parts)} hourly report(s)."] + _fit(parts, MAX_INPUT_CHARS["daily"]))


def gather_week(journal_root: pathlib.Path, date: str) -> str | None:
    _, _, dates = week_dates(date)
    parts: list[str] = []
    for day in dates:
        path = journal_root / "daily" / f"{day}.md"
        if not path.exists():
            continue
        narrative = daily_narrative_text(path.read_text(encoding="utf-8"))
        if narrative:
            label = dt.date.fromisoformat(day).strftime("%a %Y-%m-%d")
            parts.append(f"## {label}\n\n{narrative}")
    if not parts:
        return None
    return "\n\n".join([f"Week up to {date}, {len(parts)} daily report(s)."] + _fit(parts, MAX_INPUT_CHARS["weekly"]))


def call_report_model(provider: dict, level: str, source_text: str) -> dict:
    messages = [
        {"role": "system", "content": build_prompt(level)},
        {"role": "user", "content": f"Sources:\n{source_text}"},
    ]
    last_error: Exception | None = None
    for _ in range(2):
        content = call_chat_completions(provider, messages, temperature=0.2)
        try:
            return parse_model_json(content)
        except ValueError as error:
            last_error = error
            messages = messages + [
                {"role": "assistant", "content": content},
                {"role": "user", "content": "That was not valid JSON. Return only the corrected JSON object."},
            ]
    raise ValueError(f"model returned invalid JSON twice: {last_error}")


def build_report(provider: dict, journal_root: pathlib.Path, level: str, date: str, hour: int | None = None) -> dict:
    if level == "hourly":
        source = gather_hour(journal_root, date, hour)
        path = journal_root / "hourly" / date / f"{hour:02d}.md"
        title = f"Hourly journal — {date} {hour:02d}:00"
    elif level == "daily":
        source = gather_day(journal_root, date)
        path = journal_root / "daily" / f"{date}.md"
        title = f"Automatic Activity Journal — {date}"
    else:
        source = gather_week(journal_root, date)
        year, week, _ = week_dates(date)
        path = journal_root / "weekly" / f"{year}-W{week:02d}.md"
        title = f"Weekly journal — {year}-W{week:02d}"
    if source is None:
        return {"status": "no-input"}
    digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:12]
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if read_input_stamp(existing) == digest:
        return {"status": "unchanged", "path": str(path)}
    narrative = call_report_model(provider, level, source)
    path.parent.mkdir(parents=True, exist_ok=True)
    if level == "daily":
        text = upsert_daily_narrative(existing or f"# {title}\n", narrative)
    else:
        text = render_report(title, narrative)
    path.write_text(with_input_stamp(text, digest), encoding="utf-8")
    return {"status": "complete", "path": str(path)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal-root", required=True, type=pathlib.Path)
    parser.add_argument("--config", required=True, type=pathlib.Path)
    parser.add_argument("--period", required=True, choices=LEVELS)
    parser.add_argument("--date", default=dt.date.today().isoformat())
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    journal = args.journal_root
    level = args.period
    heartbeat_name = f"{level}-synthesis"
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"{level} synthesis failed: {error}")
        return 1
    stage_key = STAGE_KEYS[level]
    if not (config.get(stage_key) or {}).get("enabled", True):
        print(json.dumps({"period": level, "status": "disabled"}))
        return 0
    try:
        provider = resolve_provider(config, stage_key)
    except (ProviderError, KeyError) as error:
        write_heartbeat(journal, heartbeat_name, "failed", error_message=str(error))
        print(f"{level} synthesis failed: {error}")
        return 1

    hours: list[int | None] = hours_with_input(journal, args.date) if level == "hourly" else [None]
    results: list[dict] = []
    for hour in hours:
        try:
            result = build_report(provider, journal, level, args.date, hour=hour)
        except (OSError, ValueError, KeyError, ProviderError) as error:
            result = {"status": "failed", "error": str(error)}
        if hour is not None:
            result["hour"] = hour
        results.append(result)

    print(json.dumps({"period": level, "results": results}, ensure_ascii=False))
    failed = [item for item in results if item["status"] == "failed"]
    completed = [item for item in results if item["status"] == "complete"]
    if failed:
        write_heartbeat(journal, heartbeat_name, "failed", items_processed=len(completed), error_message=failed[-1]["error"])
        return 1
    write_heartbeat(journal, heartbeat_name, "success", items_processed=len(completed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Then remove the old daily module: `git rm src/analysis/synthesize_journal.py`. (`run_hourly.py` and `daily_summary.py` still reference it until Task 7; their tests mock `subprocess.run`, so the suite stays green.)

`re` is imported but unused in the module above — delete the `import re` line.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_synthesize_period.py -q` then `.venv/bin/python -m pytest -q`
Expected: PASS. If `test_hour_includes_screens_and_activity_and_counts_repeats_without_including_them` fails on the `10:22:15` assertion, check that `_screen(... "Unchanged since 10:21:15.")` content contains `\nUnchanged since ` (the test writes it after a blank line, so it does).

- [ ] **Step 5: Commit**

```bash
git add -A src tests && git commit -m "feat: hourly, daily and weekly reports each compact the level below, rebuilt only when input changes"
```

---

### Task 7: Wire the chain into run_hourly and daily_summary

**Files:**
- Modify: `src/orchestration/run_hourly.py:1,17-22`
- Modify: `src/orchestration/daily_summary.py` (the `synthesize_journal` call in `main`)
- Test: `tests/test_run_hourly.py`, `tests/test_daily_summary.py`

**Interfaces:**
- Consumes: `python -m src.analysis.synthesize_period --period hourly|daily|weekly` (Task 6).
- Produces: `run_hourly` runs periods in the order hourly → daily → weekly, then `build_llm_context`; `daily_summary` runs hourly before writing the scaffold and daily → weekly after it. Exit code of `daily_summary` is the daily step's return code.

- [ ] **Step 1: Write the failing tests**

In `tests/test_run_hourly.py` replace `test_synthesize_period_is_invoked_for_both_hourly_and_weekly` with:

```python
    def test_periods_run_in_chain_order_hourly_daily_weekly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal_root = root / "journal"
            journal_root.mkdir()
            config_path = root / "settings.json"
            config_path.write_text("{}", encoding="utf-8")

            exit_code, mock_run = self._invoke_main(journal_root, config_path, "2026-08-30")

            self.assertEqual(exit_code, 0)
            period_calls = self._calls_containing(mock_run, "src.analysis.synthesize_period")
            periods = [call.args[0][call.args[0].index("--period") + 1] for call in period_calls]
            self.assertEqual(periods, ["hourly", "daily", "weekly"])
            self.assertEqual(len(self._calls_containing(mock_run, "src.analysis.synthesize_journal")), 0)
```

Add to `tests/test_daily_summary.py`, in a new class at the end (before `if __name__`), reusing the same invoke pattern as the existing class (read its `_invoke_main` and copy it):

```python
class DailySummaryChainTests(unittest.TestCase):
    def test_periods_run_hourly_before_daily_before_weekly_and_never_the_old_daily_module(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal_root = root / "journal"
            journal_root.mkdir()
            config_path = root / "settings.json"
            config_path.write_text(json.dumps({}), encoding="utf-8")
            mock_result = MagicMock()
            mock_result.returncode = 0
            old_argv = sys.argv
            sys.argv = ["daily_summary", "--journal-root", str(journal_root), "--config", str(config_path), "--date", "2026-08-30"]
            try:
                with patch("src.orchestration.daily_summary.subprocess.run", return_value=mock_result) as mock_run:
                    exit_code = main()
            finally:
                sys.argv = old_argv

            self.assertEqual(exit_code, 0)
            commands = [call.args[0] for call in mock_run.call_args_list]
            periods = [command[command.index("--period") + 1] for command in commands if "src.analysis.synthesize_period" in command]
            self.assertEqual(periods, ["hourly", "daily", "weekly"])
            self.assertFalse(any("src.analysis.synthesize_journal" in command for command in commands))
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_run_hourly.py tests/test_daily_summary.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

`src/orchestration/run_hourly.py`: change the docstring to `"""Hourly job: build the hourly, daily and weekly reports (each compacting the level below), then refresh llm-context."""` and replace the `steps` list with:

```python
    steps = [
        [sys.executable, "-m", "src.analysis.synthesize_period", "--journal-root", str(args.journal_root), "--config", str(args.config), "--period", period, "--date", args.date]
        for period in ("hourly", "daily", "weekly")
    ] + [
        [sys.executable, "-m", "src.analysis.build_llm_context", "--journal-root", str(args.journal_root), "--date", args.date],
    ]
```

`src/orchestration/daily_summary.py`: add a helper above `main`:

```python
def run_period(args, period: str) -> int:
    return subprocess.run(
        [sys.executable, "-m", "src.analysis.synthesize_period", "--journal-root", str(args.journal_root), "--config", str(args.config), "--period", period, "--date", args.date],
        cwd=pathlib.Path(__file__).parents[2],
    ).returncode
```

In `main`: after the `analyze_screenshots` subprocess call add `run_period(args, "hourly")`; replace the `result = subprocess.run([... "src.analysis.synthesize_journal" ...])` statement with
```python
    daily_code = run_period(args, "daily")
    run_period(args, "weekly")
```
and change the final `return result.returncode` to `return daily_code`.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (whole suite).

- [ ] **Step 5: Commit**

```bash
git add src/orchestration tests && git commit -m "feat: run hourly, daily and weekly reports as one chain"
```

---

### Task 8: History migration — backfill screen files and requeue dead-lettered vision jobs

**Files:**
- Modify: `src/infra/processing_queue.py` (add `requeue_failed`)
- Create: `src/ops/migrate_screens.py`
- Test: `tests/test_processing_queue.py`, `tests/test_migrate_screens.py` (new)

**Interfaces:**
- Consumes: `screen_path`, `write_screen_markdown` (Task 3).
- Produces:
  - `FileJobQueue.requeue_failed(kind: str | None = None) -> int` — moves matching jobs from `failed/` to `pending/` with `attempts = 0`, `availableAt = now`, `failedAt` removed; returns the count.
  - `migrate_screens.backfill(journal_root: Path) -> int` — writes a screen file for every `raw/visual-*.jsonl` entry that lacks one; returns the count.
  - CLI: `python -m src.ops.migrate_screens --journal-root PATH [--backfill] [--requeue-failed]`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_processing_queue.py` (match the file's existing import/class style; it uses `FileJobQueue` and a temp dir):

```python
    def test_requeue_failed_moves_matching_jobs_back_to_pending_with_fresh_attempts(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = FileJobQueue(Path(directory))
            queue.enqueue("vision", {"screenshot": "a.jpg"}, job_id="a")
            queue.enqueue("hourly", {"date": "2026-09-26"}, job_id="b")
            for job_id in ("a", "b"):
                queue.claim()
                queue.fail(job_id, "boom", max_attempts=1)

            moved = queue.requeue_failed(kind="vision")

            self.assertEqual(moved, 1)
            state, job = queue.find("a")
            self.assertEqual((state, job["attempts"], job["status"]), ("pending", 0, "pending"))
            self.assertNotIn("failedAt", job)
            self.assertEqual(queue.find("b")[0], "failed")
            self.assertIsNotNone(queue.claim(kind="vision"))
```

Create `tests/test_migrate_screens.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from src.infra.processing_queue import FileJobQueue
from src.ops.migrate_screens import backfill, main


def _visual(journal: Path, date: str, image: Path, analysis: dict) -> None:
    raw = journal / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    with (raw / f"visual-{date}.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"source": "screenshot-vision", "screenshot": str(image), "analysis": analysis}) + "\n")


class BackfillTests(unittest.TestCase):
    def test_writes_a_file_per_analysed_screenshot_and_skips_existing_ones(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            first = journal / "screenshots" / "2026-09-26" / "screen-10-21-15-521.jpg"
            second = journal / "screenshots" / "2026-09-25" / "screen-09-00-00-000.jpg"
            _visual(journal, "2026-09-26", first, {"summary": "Kibana", "observations": ["chart"]})
            _visual(journal, "2026-09-25", second, {"summary": "Editor"})

            self.assertEqual(backfill(journal), 2)
            self.assertEqual(backfill(journal), 0)
            self.assertIn("Kibana", (journal / "screens" / "2026-09-26" / "10" / "10-21-15-521.md").read_text(encoding="utf-8"))
            self.assertTrue((journal / "screens" / "2026-09-25" / "09" / "09-00-00-000.md").exists())

    def test_malformed_lines_are_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            (journal / "raw").mkdir()
            (journal / "raw" / "visual-2026-09-26.jsonl").write_text("not json\n{}\n", encoding="utf-8")

            self.assertEqual(backfill(journal), 0)


class MainTests(unittest.TestCase):
    def test_requeue_failed_flag_moves_vision_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            queue = FileJobQueue(journal / "queue")
            queue.enqueue("vision", {"screenshot": "a.jpg"}, job_id="a")
            queue.claim()
            queue.fail("a", "boom", max_attempts=1)

            exit_code = main(["--journal-root", str(journal), "--requeue-failed"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(queue.find("a")[0], "pending")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_processing_queue.py tests/test_migrate_screens.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Add to `FileJobQueue` in `src/infra/processing_queue.py` (after `fail`):

```python
    def requeue_failed(self, kind: str | None = None) -> int:
        moved = 0
        for path in sorted((self.root / "failed").glob("*.json")):
            job = json.loads(path.read_text(encoding="utf-8"))
            if kind is not None and job.get("kind") != kind:
                continue
            job.update({"status": "pending", "attempts": 0, "availableAt": _timestamp(_now())})
            job.pop("failedAt", None)
            path.unlink()
            self._write("pending", job)
            moved += 1
        return moved
```

Create `src/ops/migrate_screens.py`:

```python
"""One-shot migration helpers for the per-screenshot Markdown reports."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

from src.analysis.screen_markdown import screen_path, write_screen_markdown
from src.infra.processing_queue import FileJobQueue


def backfill(journal_root: pathlib.Path) -> int:
    written = 0
    for path in sorted((journal_root / "raw").glob("visual-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                image = pathlib.Path(record["screenshot"])
                analysis = record["analysis"]
            except (json.JSONDecodeError, KeyError):
                continue
            if not isinstance(analysis, dict) or screen_path(journal_root, image).exists():
                continue
            write_screen_markdown(journal_root, image, analysis)
            written += 1
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal-root", required=True, type=pathlib.Path)
    parser.add_argument("--backfill", action="store_true", help="write screen files for already-analysed screenshots")
    parser.add_argument("--requeue-failed", action="store_true", help="move dead-lettered vision jobs back to pending")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    summary: dict[str, int] = {}
    if args.backfill:
        summary["backfilled"] = backfill(args.journal_root)
    if args.requeue_failed:
        summary["requeued"] = FileJobQueue(args.journal_root / "queue").requeue_failed(kind="vision")
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/infra src/ops tests && git commit -m "feat: migration helpers to backfill screen files and requeue dead-lettered vision jobs"
```

---

### Task 9: Docs, spec sync, rule proposal, and live verification

**Files:**
- Modify: `README.md` (architecture and outputs sections)
- Modify: `docs/superpowers/specs/2026-09-26-hierarchical-reports-design.md` (record deviations)
- Modify (only after approval): `rules/hourly-weekly-narrative-format.md`
- Live journal: `/home/amin/JarvisJournal` (migration + verification)

- [ ] **Step 1: Update the README**

In `README.md`, update the Architecture block near the top so it reads:

```text
Screenshot → vision model → raw/visual-DATE.jsonl + screens/DATE/HH/<time>.md   (one Markdown file per screenshot)
Hour's screen files + active windows → text model → hourly/DATE/HH.md
Day's hourly reports                 → text model → daily/DATE.md ("## LLM narrative" section)
Week's daily reports                 → text model → weekly/YYYY-Www.md
```

and add one paragraph under it: hourly, daily and weekly reports share one format (summary, On screen, Timeline, Patterns, Next actions) and differ only in depth; each report stores a hidden `<!-- input: … -->` stamp and is rebuilt only when its inputs change, so a failed run is retried automatically by the next run; near-identical screenshots get a file marked "Unchanged since HH:MM:SS"; there is no model-reported confidence anywhere. Remove any README text describing `Journal/queue-period/` retries for narratives, `minConfidence`, or `_LLM confidence_` (`grep -n "confidence\|queue-period\|synthesize_journal" README.md` to find them).

- [ ] **Step 2: Record deviations in the spec**

In `docs/superpowers/specs/2026-09-26-hierarchical-reports-design.md` make these edits so the spec matches what was built:
- Freshness/failure sections: retry is done by the input-hash stamp (a failed report leaves the file stale, so the next run retries); `queue-period/` is no longer used by reports.
- Rebuild order: every hour of `--date` with input is checked each run (unchanged hours cost no model call).
- Screen file name is `screens/DATE/HH/<HH-MM-SS-mmm>.md`.
- Migration CLI lives in `src/ops/migrate_screens.py` (`--backfill`, `--requeue-failed`).
- `narrative.compact_event` is not changed (reports no longer read raw events); the proxy example is already documented in the README.
- Results are filed under the screenshot's own date in `raw/visual-DATE.jsonl`.

- [ ] **Step 3: Full test run**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass. Commit docs: `git add README.md docs && git commit -m "docs: describe the hierarchical report chain"`.

- [ ] **Step 4: Propose the rule update (needs explicit approval — do not write the file first)**

Show Amin this draft and ask via AskUserQuestion (add it / skip / edit first). Only on "add it", replace the body of `rules/hourly-weekly-narrative-format.md` (keep its front matter but set `title: Hourly/daily/weekly reports share one screen-aware format` and keep `status: active`, `added: 2026-08-28`; do not change `added`):

> Hourly, daily and weekly journal files share one Markdown format — summary paragraph, `### On screen`, `### Timeline`, `### Patterns`, `### Next actions` — differing only in depth: hourly is fine-grained, daily groups by task, weekly stays general. `### On screen` records concrete details of what the vision model saw. Each level is built only from the level below: per-screenshot Markdown files → hourly (plus that hour's active windows) → daily → weekly. No model-reported confidence appears anywhere.
>
> **Why:** Amin wanted all report levels in one format with screen details, built as a compaction chain, and asked for confidence to be dropped from the project.
> **Scope:** `src/analysis/report_levels.py`, `src/analysis/report_render.py`, `src/analysis/synthesize_period.py`, `src/analysis/screen_markdown.py`, `src/analysis/analyze_screenshots.py`.

- [ ] **Step 5: Live migration and verification**

```bash
cd /home/amin/jarvis-activity-journal
.venv/bin/python -m src.ops.migrate_screens --journal-root /home/amin/JarvisJournal --backfill --requeue-failed
ls /home/amin/JarvisJournal/screens | head
```
Expected: JSON like `{"backfilled": N, "requeued": M}`; `screens/` has date folders.

Then run the chain once and inspect (this makes real Groq calls through the proxy configured in `settings.json`):

```bash
systemctl --user reset-failed 'jarvis-*.service'
systemctl --user start jarvis-vision-analysis.service
systemctl --user start jarvis-hourly.service
journalctl --user -u jarvis-vision-analysis.service -u jarvis-hourly.service --since "-5min" --no-pager | tail -30
cat /home/amin/JarvisJournal/hourly/$(date +%F)/$(date +%H).md
```
Expected: no failures; the hourly file has the five sections, no confidence line, and On-screen details; the daily file still contains `## LLM narrative`; the weekly file builds from the daily one. Check `grep -ril confidence /home/amin/JarvisJournal/hourly /home/amin/JarvisJournal/screens | head` returns nothing for freshly built files. If a call fails, read `health/*-synthesis.json` for the error before changing code.

- [ ] **Step 6: Final commit state**

`git status` should be clean apart from `src/jarvis_activity_journal.egg-info/` (pre-existing, untracked). Report the test count, the migration numbers, and any deviations from the spec to Amin.
