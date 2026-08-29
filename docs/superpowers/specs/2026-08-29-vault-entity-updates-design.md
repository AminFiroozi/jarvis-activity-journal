# Vault Entity Companion Notes — Design

**Goal:** when the pipeline observes genuinely new info about a person or project, update the Obsidian vault — not just link to it from the daily journal mirror (already shipped in `sync_vault.py`). Add a once-nightly, opt-in stage that asks a text model "did anything noteworthy happen today involving someone or something in this vault's roster?", validates every proposed name against the vault's real notes with zero fuzzy matching, and appends at most one dated paragraph per resolved entity to a companion note.

**Non-goals:** writing into the curated `People/<Name>.md` or `Projects/<Name>.md` files themselves (companion notes only, no exceptions); changing `project_evidence.py`'s collection granularity or adding diff/commit-body capture; hourly-cadence entity updates; fuzzy/edit-distance/prefix/substring name matching of any kind.

## Why companion notes, not direct edits (research findings)

- **People notes** (`D:\JARVIS\People\**\*.md`, excluding `History/`) are hand-curated narrative — Key Facts, Connections, Relationship Arc/Timeline, derived aggregate stats (message counts, peak months) that need recomputation, not appending. Zero append-log convention anywhere. JARVIS's own manual "Profile Auto-Update Protocol" (`D:\JARVIS\CLAUDE.md`) already excludes People from its automated-update table (Skills/Projects/Topics/Amin.md only).
- **Projects notes** (`D:\JARVIS\Projects\*.md`) mostly use static, topically-named sections (`## Team`, `## Tech Stack`, `## Status`), occasionally date-stamped and edited in place. The one append-log exception, `Mahoura.md`'s 86-entry "## Recent Work (timestamp)" log, comes from many manual coding sessions actually working in that repo — not the vault-wide convention, and not a fit for thin, mechanical git-snapshot telemetry.
- `project_evidence.py` is a point-in-time snapshot poller (latest branch/commit-hash/commit-subject/dirty-file-count per poll) with no project-name-to-vault-note mapping and no diff/commit-body — far thinner than Mahoura's hand-written summaries.

## Decisions (confirmed with Amin)

- **People**: never write into a person's curated note. Companion note only: `People/<Group>/<Stem> - Activity Mentions.md`, same folder as the person's own note.
- **Projects**: never write into the curated `Projects/<Name>.md`. Companion note only: `Projects/<Stem> - Activity Log.md`.
- **Signal threshold**: an LLM judges noteworthiness over the whole day's evidence and writes a real paragraph — not a mechanical dump of every git snapshot or every mention. Most days should produce nothing for most entities.
- **Cadence**: once nightly (in `daily_summary.py`, after `synthesize_journal` and `sync_vault`), not hourly — noteworthiness is better judged over a full day's evidence than an hourly slice.
- **Linking mechanism**: a `[[Stem]]` wikilink in the companion note's own frontmatter/header — this surfaces the companion note in the curated note's Obsidian backlinks pane automatically, satisfying "linked back from the main note" with zero writes into the curated file.

## Architecture

Same two-layer split already used for `synthesize_journal.py`/`sync_vault.py`:

```
daily_summary.py (existing)
  ... retention → analyze_screenshots → scaffold → build_llm_context → synthesize_journal ...
  └─ if vaultRoot set:
        sync_vault           (existing, unchanged — daily journal mirror)
        sync_entities (NEW)
              reads: raw/journal-<date>.json (daily narrative) + raw/*.jsonl (events)
              calls: entity_facts.extract_entity_facts() → {"people":[...], "projects":[...]}
              resolves each proposed name against the vault's REAL note files (exact/token match only)
              appends ≤1 dated paragraph per resolved entity to its companion note
```

- `src/analysis/narrative.py` (NEW) — shared evidence primitives moved (not copied) out of `synthesize_journal.py`: `local_time`, `truncate`, `compact_event`, `parse_model_json`, `read_events(journal_root, date, compact=compact_event, limit=150)`, `fit_evidence(events, max_chars)`. `synthesize_journal.py` re-imports these names so its own existing tests pass unmodified — proof the extraction is behavior-preserving.
- `src/analysis/entity_facts.py` (NEW) — model-facing, no vault knowledge:
  - `compact_entity_event(event) -> dict | None` — delegates to `narrative.compact_event`, plus a `source == "git-project"` branch narrative's compactor doesn't handle.
  - `summarize_projects(events) -> list[dict]` — collapses a day's repeated `project_evidence.py` snapshots into one record per `projectPath`: branches seen, distinct `(hash, message)` commits seen, max `changedFileCount`. Derived consumer-side; `project_evidence.py` itself is untouched.
  - `build_evidence(journal_root, date, roster) -> dict` — `{"date", "narrative", "projects", "events", "roster"}`; `narrative` read from `Journal/raw/journal-<date>.json`, falling back to the daily file's `## LLM narrative` section, else `None`.
  - `extract_entity_facts(provider, evidence, max_chars=8000) -> dict` — one `call_chat_completions` call, `narrative.parse_model_json` on the result.
  - `validate_facts(payload) -> dict` — shape-only filtering (drop non-dicts, blank/missing `name`, notes under ~40 chars). Name *resolution* is deliberately not this module's job.
- `src/orchestration/sync_entities.py` (NEW) — vault-facing, mirrors `sync_vault.py`'s structure and contract exactly:
  - `resolve_note_name(proposed, index, note_paths, category) -> pathlib.Path | None` — **the security boundary.** In order, first hit wins: (1) exact stem match case-insensitive; (2) whole-token lookup in the vault's name index, exactly 1 candidate; (3) separator-stripped lookup (`"Dariush Seif"` → `dariushseif`, matching the whole-stem token `vault_linker`'s tokenizer already produces for `DariushSeif.md`); (4) word-intersection for multi-word proposals, exactly 1 candidate in the intersection. Anything else (0 or 2+ candidates at any step) is dropped — **no fuzzy/edit-distance/prefix/substring matching, ever.** A category gate rejects a resolved path outside the expected `People/`/`Projects/` root, and generated companion-note stems are excluded from the index entirely so the pipeline can never target its own output.
  - `companion_path(note_path, category) -> pathlib.Path` — built only from `note_path.parent`/`note_path.stem` (an already-resolved, already-existing file) plus a fixed suffix. No path component ever comes from model output.
  - `render_companion_header`, `render_entry`, `append_entry(path, stem, category, date, entry_body) -> pathlib.Path | None` — idempotent: checks for an existing `## <date>` heading before writing; returns `None` (skip, not replace) if already present, so re-running the same date is a byte-for-byte no-op and a user's hand-edit is never silently clobbered.
  - `sync_entities(journal_root, vault_root, config, date, dry_run=False) -> dict`, CLI `main()` — never lets an exception escape, always exits 0, matches `sync_vault.py`'s contract exactly. `--dry-run` writes the status JSON but nothing under the vault.
- `src/orchestration/vault_linker.py` (MODIFY, additive) — add `build_note_paths(vault_root) -> dict[str, list[pathlib.Path]]` (stem → real note file paths, honoring the same `_NAME_GLOBS`/`History`-exclusion `build_name_index` already uses); refactor `build_name_index` onto it as a thin wrapper. Exclude generated companion-note stems (ending ` - Activity Mentions` / ` - Activity Log`) from both functions.

## LLM contract

One call per day, not split people/projects — the judgment and evidence payload are both cross-cutting (a fact can be about a person *and* a project at once), and splitting would duplicate the expensive evidence payload and double rate-limit exposure for no real benefit.

System prompt requires: silence is the default and correct answer most days ("most days, most entities warrant nothing — empty lists are the correct answer far more often than not"); never restate telemetry (a branch name, dirty-file count, or commit hash alone is not noteworthy); use only names from the supplied roster, copied verbatim — omit a fact if you can't tell which roster entry it's about, never invent a name; one factual paragraph per entry; no invented intent, no verbatim message text, no secrets (mirrors `synthesize_journal.PROMPT` and `rules/capture-chat-topic-and-correspondent.md`). Output:

```json
{
  "people": [{"name": "DariushSeif", "note": "one factual paragraph", "evidence": ["observed fact"], "confidence": 0.0}],
  "projects": [{"name": "Mahoura", "note": "one factual paragraph", "evidence": ["observed fact"], "confidence": 0.0}]
}
```

`evidence` forces grounding (an anti-hallucination filter); `confidence` matches the house style (`_LLM confidence:_` in `upsert_narrative`) and enables an optional `minConfidence` gate. Both parsed tolerantly — a weak local model omitting them still works (missing `confidence` treated as `0.0`, `minConfidence` defaults to `0.0`, i.e. off).

Validation pipeline (every stage can only remove entries, never add): model JSON → `parse_model_json` → `validate_facts` (shape) → `resolve_note_name` per entry, category-gated → dedupe by resolved stem keeping highest confidence → `minConfidence` filter → sort by confidence desc → cap to `maxEntitiesPerDay` per category → `inject_links` on the paragraph (free cross-linking to other vault notes it mentions) → idempotent append.

## Companion note format

```markdown
---
entity: DariushSeif
type: person
up: "[[DariushSeif]]"
tags: [activity-journal, generated]
---

# DariushSeif — Activity Mentions

Auto-generated companion log for [[DariushSeif]]. Appended by the activity journal; the curated note is never modified.

## 2026-08-28

<one paragraph, wikilink-injected>

_Evidence: fact; fact_
_Source: [[Journal/Daily/2026-08-28|daily journal]] · confidence: 0.7_
```

Read-modify-write via `write_text` (not `open("a")`) so the duplicate-date check, header creation, and formatting are one atomic decision — files are small, the job is single-threaded and nightly. Out-of-order backfill (running an older date after a newer one) appends out of chronological order; accepted trade-off, the heading carries the date and sorted insertion isn't worth the complexity for a nightly job.

## Orchestration change

In `src/orchestration/daily_summary.py`, inside the existing `if vault_root:` block (right after the `sync_vault` subprocess call — placed after `synthesize_journal` since it consumes `raw/journal-<date>.json`, and after `sync_vault` so `Journal/Daily/<date>.md` exists before entity notes link to it):

```python
subprocess.run([sys.executable, "-m", "src.orchestration.sync_entities", "--journal-root", str(args.journal_root), "--config", str(args.config), "--vault-root", str(vault_root), "--date", args.date], cwd=pathlib.Path(__file__).parents[2])
```

Same pattern `sync_vault` already uses — return code ignored, `main()`'s own return code stays governed only by `synthesize_journal`. Inside `sync_entities.main()`: `entityUpdates.enabled == false` or no `activeProvider` configured → print a one-line skip notice, exit 0 — the stage is doubly opt-in (vault configured *and* this stage explicitly enabled) without an extra gate in `daily_summary.py` itself.

Observability: `write_heartbeat(journal_root, "entity-updates", "success"|"failed", items_processed=n)` (existing `src.infra.heartbeat` module, already used by every other collector) so `doctor.py` picks it up for free; `Journal/raw/entities-<date>.json` (raw model response) and `Journal/raw/entities-<date>.status.json` (`{"date", "status", "written": [...], "skipped": [{"name", "category", "reason"}], "error"}`) mirroring the existing `journal-<date>.json`/`.status.json` pattern. The `skipped` list matters — silently dropped names are the expected, correct failure mode and need somewhere to surface for manual inspection.

## Config

New stage in `config/settings.example.json`, alongside `journalSynthesis`:

```json
"entityUpdates": {
  "enabled": false,
  "activeProvider": "local-text",
  "minConfidence": 0.0,
  "maxEntitiesPerDay": 5,
  "maxEvidenceChars": 8000
}
```

`enabled: false` by default, matching the `screenshotAnalyzer.enabled: false` precedent — this stage writes interpersonal content into a personal vault, more privacy-sensitive than the daily-journal mirror, so it must be an explicit opt-in. `activeProvider` defaults to `local-text` (on-device) for the same reason — cloud providers remain available but require deliberately switching this specific stage's config, independent of `journalSynthesis`'s own provider choice. `maxEntitiesPerDay` is the hard blast-radius cap: even a badly-behaved model cannot create more than 5 people + 5 project companion notes in one night.

## Testing

**Automated (temp dirs, no network):**
- Resolution: exact-stem; single-token; ambiguous-drop (real vault collision pairs — `ErfanMoayed`/`ErfanTajik`, `Agha Ansari`/`AghaAnsari`); unknown-name drop; category-mismatch drop (a project proposal that would otherwise resolve to a `Skills/*.md` note); companion notes excluded as resolution targets.
- Create → append (second date) → re-run same date → byte-identical (idempotency).
- **Curated note byte-unchanged after a full run** — the single most important regression guard for this feature.
- Malformed model payloads (non-dict entries, blank name, too-short note) → dropped, zero files created; `maxEntitiesPerDay` cap; `minConfidence` filter; `--dry-run` writes status JSON but nothing under the vault; invalid date (`\d{4}-\d{2}-\d{2}$` mismatch) → nothing written, no directories created; `main()` exits 0 on any failure (unwritable vault root, malformed config, etc.).
- End-to-end via `unittest.mock.patch` on `call_chat_completions` returning canned fenced JSON — asserts the full path from model string to written files, no network (same idiom `tests/test_daily_summary.py` already uses for `sync_vault`).
- `narrative.py`'s moved functions behave identically to their pre-move versions; `synthesize_journal.py`'s existing tests pass unmodified after the extraction.

**Manual, requires a real model (documented, not part of the automated suite):**
- `--dry-run` against several real past dates — success looks like empty lists on most days.
- Attribution accuracy, prose quality, and whether the configured local model reliably honors the JSON+roster shape.
