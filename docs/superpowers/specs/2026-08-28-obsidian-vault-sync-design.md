# Obsidian Vault Sync — Design

**Goal:** mirror each day's synthesized activity journal into the JARVIS Obsidian vault (`D:\JARVIS`) as a real note, with auto-detected `[[wikilinks]]` to existing People/Projects/Skills notes, so the activity journal becomes part of the vault's knowledge graph instead of living only in `Journal/daily/*.md` inside the pipeline repo.

**Non-goals:** hourly/weekly sync (daily only, per decision below), MCP-based writes (Obsidian isn't guaranteed running when this runs), fuzzy matching beyond name-token overlap (no ML/embedding-based entity resolution), editing existing vault notes other than the generated daily note itself.

## Decisions (from brainstorming)

- **Write method:** direct filesystem write, not Obsidian MCP. The pipeline runs unattended via Task Scheduler; MCP requires Obsidian open with the Local REST API plugin. Matches how the pipeline already writes its own `Journal/` output.
- **Vault location:** new top-level `D:\JARVIS\Journal\Daily\<date>.md` — mirrors the pipeline's own `Journal/daily/` folder name, kept separate from People/Projects/Skills/Topics.
- **Sync scope:** daily only. Hourly is too granular for a vault note; weekly can be derived from daily notes later if wanted.
- **Wikilink strategy:** fuzzy match — vault note filenames are split into name tokens (PascalCase boundaries), narrative text is scanned case-insensitively for those tokens, and a match becomes an aliased link (`[[DariushSeif|Dariush]]`) so the rendered prose stays natural. An ambiguous token (matches 2+ different notes) is left unlinked and logged, never guessed.
- **Trigger:** chained onto `src/orchestration/daily_summary.py`, as one more subprocess step after `synthesize_journal.py` completes.

## Architecture

```
daily_summary.py (existing)
  ├─ retention
  ├─ analyze_screenshots
  ├─ render_daily_scaffold → Journal/daily/<date>.md
  ├─ build_llm_context
  ├─ synthesize_journal → upserts "## LLM narrative" into Journal/daily/<date>.md
  └─ sync_vault (NEW)         ← this design
        reads Journal/daily/<date>.md
        builds a name index from the vault (People/*/*.md, Projects/*.md, Skills/*.md)
        injects wikilinks into a copy of the content
        writes D:\JARVIS\Journal\Daily\<date>.md (frontmatter + linked content)
```

New module: `src/orchestration/sync_vault.py`, invoked as `python -m src.orchestration.sync_vault --journal-root <path> --vault-root <path> --date <date>`.

Two internal units, each independently testable:

1. **`src/orchestration/vault_linker.py`** — pure text transform, no I/O beyond an index the caller builds.
   - `build_name_index(vault_root: Path) -> dict[str, list[str]]`: scans `People/**/*.md`, `Projects/*.md`, `Skills/*.md`, splits each filename's stem on PascalCase boundaries and as a whole (`DariushSeif.md` → tokens `dariush`, `seif`, `dariushseif`, all lowercased), and maps each token to the list of note base-names (without extension) it could refer to (usually one; more than one means ambiguous).
   - `inject_links(text: str, index: dict[str, list[str]]) -> str`: tokenizes `text` on word boundaries, and for each word whose lowercased form is a key in `index` with exactly one candidate, replaces the first occurrence per note per call with `[[<candidate>|<original word>]]`. Ambiguous tokens (2+ candidates) and already-linked text are left untouched. Case-preserving on the visible text (the alias), case-insensitive on the match.

2. **`src/orchestration/sync_vault.py`** — I/O and orchestration.
   - `render_vault_note(date: str, content: str) -> str`: prepends YAML frontmatter (`date`, `tags: [activity-journal, generated]`) to the linked content.
   - `sync_day(journal_root: Path, vault_root: Path, date: str) -> Path | None`: reads `journal_root/daily/<date>.md`; if missing, returns `None` (nothing to sync yet, not an error). Builds the name index, injects links, renders the note, writes it to `vault_root/Journal/Daily/<date>.md` (full overwrite), returns the written path.
   - `main()`: CLI wrapper; catches all exceptions from `sync_day`, prints a warning, and exits `0` regardless — sync failure must never fail the nightly job that already produced a valid daily journal.

## Data flow

1. `daily_summary.py` finishes writing `Journal/daily/<date>.md` (scaffold + LLM narrative, already existing behavior).
2. `sync_vault.main()` runs, reads that same file's full text.
3. `build_name_index` walks the vault's People/Projects/Skills folders (cheap — a few hundred filenames, no file content read).
4. `inject_links` transforms the daily note's body text (frontmatter of the *source* file, if any, is not treated as vault-note content — only the rendered Markdown body flows through).
5. `render_vault_note` wraps it with the vault note's own frontmatter.
6. Written to `D:\JARVIS\Journal\Daily\<date>.md`, overwriting any prior sync of that date.

## Error handling

- Missing source `daily/<date>.md` → `sync_day` returns `None`, `main()` prints "nothing to sync yet" and exits 0 (not an error — this can legitimately happen if `synthesize_journal` itself failed upstream and `daily_summary.py`'s existing non-fatal-per-stage pattern already surfaces that separately).
- Vault root unreachable / permission error / any other exception during read or write → caught in `main()`, printed as a warning, exit 0. The activity journal itself already succeeded; a vault-write hiccup is visibility-only, never a pipeline failure.
- Ambiguous name tokens are never linked — silently correct behavior, not an error, but worth a one-line log so ambiguity is discoverable if the vault grows and matches multiply over time.

## Testing

- `tests/test_vault_linker.py`: `build_name_index` against a temp directory with sample `People/Friends/DariushSeif.md`-style files, asserting correct token → candidate mapping including a deliberately ambiguous case (two notes sharing a first-name token). `inject_links` against known input/index pairs: single match links correctly with alias, ambiguous token stays plain text, already-bracketed text is not double-linked, case-insensitivity works both directions.
- `tests/test_sync_vault.py`: `sync_day` against temp `journal_root`/`vault_root` directories — missing source file returns `None` and writes nothing; present source file produces a written note with correct frontmatter, linked body, and correct path; re-running for the same date overwrites rather than duplicating. `main()`'s exception-swallowing behavior (a deliberately broken vault_root, e.g. a file where a directory is expected) exits 0 and prints a warning rather than raising.

## Orchestration change

`daily_summary.py`'s `main()` gets one more step after the `synthesize_journal` call, before the final `print`/`return`: read a new top-level `"vaultRoot"` key from `config/settings.json` (absent/empty means the feature is opt-in and off by default, so the pipeline is unaffected for anyone without a configured vault path); when set, run `subprocess.run([sys.executable, "-m", "src.orchestration.sync_vault", "--journal-root", str(args.journal_root), "--vault-root", vault_root, "--date", args.date], cwd=...)`. `daily_summary.py`'s own return code stays governed by `synthesize_journal`'s result, per the error-handling section above — the new subprocess call's exit code is intentionally not checked, and the call is skipped entirely (not run with an empty path) when `vaultRoot` is unset.
