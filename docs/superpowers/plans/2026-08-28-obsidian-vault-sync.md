# Obsidian Vault Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** mirror each day's synthesized activity journal into the JARVIS Obsidian vault as a real note, with auto-detected `[[wikilinks]]` to existing People/Projects/Skills notes.

**Architecture:** two new, independently-testable modules — a pure-text `vault_linker.py` (name index + link injection) and an I/O-owning `sync_vault.py` (reads the daily journal, calls the linker, writes the vault note) — plus a small, opt-in wiring change in `daily_summary.py` and a new `vaultRoot` config key.

**Tech Stack:** Python 3.10+, pytest, stdlib only (`pathlib`, `re`, `argparse`).

**Spec:** `docs/superpowers/specs/2026-08-28-obsidian-vault-sync-design.md`

## Global Constraints

- Every module is invoked as `python -m src.<subpackage>.<name>` — no bare-script imports, no try/except ImportError fallback patterns.
- Commits: conventional format (`feat:`/`fix:`/`test:`/`docs:`), plain everyday words, authored as `AminFiroozi <afiroozi007@gmail.com>` — never a Claude co-author trailer.
- Run `python -m pytest tests/ -q` after every task; all tests must pass before moving to the next task.
- Sync must never fail the pipeline: any exception during vault I/O is caught, logged, and `main()` still exits 0. Missing source `daily/<date>.md` is not an error either — return `None`, not raise.
- The feature is opt-in: `daily_summary.py` only invokes `sync_vault` when `config["vaultRoot"]` is set and truthy; absent/empty means the pipeline is unaffected for anyone without a configured vault path.
- Ambiguous name tokens (2+ vault notes sharing a token) are never auto-linked — leave the plain word untouched rather than guess.

---

### Task 1: Vault name index and link injection

**Files:**
- Create: `src/orchestration/vault_linker.py`
- Test: `tests/test_vault_linker.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `build_name_index(vault_root: pathlib.Path) -> dict[str, list[str]]` and `inject_links(text: str, index: dict[str, list[str]]) -> str`, both consumed by Task 2's `sync_vault.py`.

`build_name_index` scans `People/**/*.md`, `Projects/*.md`, `Skills/*.md` under the vault root, splits each filename's stem on PascalCase word boundaries (`DariushSeif` → `dariush`, `seif`, plus the whole stem lowercased `dariushseif`), and maps each lowercased token to the list of note base-names (without `.md`) that produced it. A token mapping to more than one base-name is ambiguous. `inject_links` scans `text` for word-boundary tokens, and for each token that is an unambiguous key in `index`, replaces its first occurrence per matched note with an aliased wikilink (`[[DariushSeif|Dariush]]`) — preserving the original casing as the visible alias, matching case-insensitively. Text already inside `[[...]]` brackets is never re-matched or re-wrapped.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_vault_linker.py`:

```python
import tempfile
import unittest
from pathlib import Path

from src.orchestration.vault_linker import build_name_index, inject_links


class VaultLinkerTests(unittest.TestCase):
    def _make_vault(self, root: Path) -> None:
        friends = root / "People" / "Friends"
        friends.mkdir(parents=True)
        (friends / "DariushSeif.md").write_text("", encoding="utf-8")
        (friends / "AlirezaRahimi.md").write_text("", encoding="utf-8")
        (friends / "AlirezaKarimi.md").write_text("", encoding="utf-8")
        projects = root / "Projects"
        projects.mkdir()
        (projects / "Mahoura.md").write_text("", encoding="utf-8")

    def test_build_name_index_splits_pascal_case_filenames(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._make_vault(root)

            index = build_name_index(root)

            self.assertEqual(index["dariush"], ["DariushSeif"])
            self.assertEqual(index["seif"], ["DariushSeif"])
            self.assertEqual(index["dariushseif"], ["DariushSeif"])
            self.assertEqual(index["mahoura"], ["Mahoura"])

    def test_build_name_index_flags_ambiguous_tokens(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._make_vault(root)

            index = build_name_index(root)

            self.assertCountEqual(index["alireza"], ["AlirezaRahimi", "AlirezaKarimi"])
            self.assertEqual(index["rahimi"], ["AlirezaRahimi"])

    def test_inject_links_wraps_single_match_with_alias(self):
        index = {"dariush": ["DariushSeif"]}

        result = inject_links("Chatted with Dariush about the project.", index)

        self.assertEqual(result, "Chatted with [[DariushSeif|Dariush]] about the project.")

    def test_inject_links_skips_ambiguous_tokens(self):
        index = {"alireza": ["AlirezaRahimi", "AlirezaKarimi"]}

        result = inject_links("Met Alireza today.", index)

        self.assertEqual(result, "Met Alireza today.")

    def test_inject_links_does_not_mangle_already_bracketed_text(self):
        index = {"dariush": ["DariushSeif"]}

        result = inject_links("[[DariushSeif|Dariush]] again about Dariush.", index)

        self.assertEqual(result, "[[DariushSeif|Dariush]] again about [[DariushSeif|Dariush]].")

    def test_inject_links_is_case_insensitive(self):
        index = {"dariush": ["DariushSeif"]}

        result = inject_links("DARIUSH called.", index)

        self.assertEqual(result, "[[DariushSeif|DARIUSH]] called.")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_vault_linker.py -v`
Expected: FAIL — `src.orchestration.vault_linker` does not exist yet (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `vault_linker.py`**

Create `src/orchestration/vault_linker.py`:

```python
"""Match narrative text against Obsidian vault note filenames and inject wikilinks."""

from __future__ import annotations

import pathlib
import re

_NAME_GLOBS = ("People/**/*.md", "Projects/*.md", "Skills/*.md")

_STEM_WORD_PATTERN = re.compile(r"[A-Z][a-z0-9]*|[a-z0-9]+")
_TEXT_WORD_PATTERN = re.compile(r"\[\[.*?\]\]|[A-Za-z][A-Za-z0-9]*")


def _split_tokens(stem: str) -> list[str]:
    tokens = [word.lower() for word in _STEM_WORD_PATTERN.findall(stem)]
    tokens.append(stem.lower())
    return list(dict.fromkeys(tokens))


def build_name_index(vault_root: pathlib.Path) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for pattern in _NAME_GLOBS:
        for path in sorted(vault_root.glob(pattern)):
            if not path.is_file():
                continue
            base_name = path.stem
            for token in _split_tokens(base_name):
                candidates = index.setdefault(token, [])
                if base_name not in candidates:
                    candidates.append(base_name)
    return index


def inject_links(text: str, index: dict[str, list[str]]) -> str:
    linked: set[str] = set()

    def _replace(match: re.Match) -> str:
        word = match.group(0)
        if word.startswith("[["):
            return word
        candidates = index.get(word.lower())
        if not candidates or len(candidates) != 1:
            return word
        base_name = candidates[0]
        if base_name in linked:
            return word
        linked.add(base_name)
        return f"[[{base_name}|{word}]]"

    return _TEXT_WORD_PATTERN.sub(_replace, text)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_vault_linker.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass, no regressions.

- [ ] **Step 6: Commit**

```bash
git add src/orchestration/vault_linker.py tests/test_vault_linker.py
git commit -m "feat(orchestration): add vault name index and wikilink injection"
```

---

### Task 2: Sync daily journal into the vault, wire into the pipeline

**Files:**
- Create: `src/orchestration/sync_vault.py`
- Modify: `src/orchestration/daily_summary.py:90-94`
- Modify: `config/settings.example.json`
- Test: `tests/test_sync_vault.py`

**Interfaces:**
- Consumes: `src.orchestration.vault_linker.build_name_index(vault_root: pathlib.Path) -> dict[str, list[str]]` and `inject_links(text: str, index: dict[str, list[str]]) -> str`, both from Task 1.
- Produces: `render_vault_note(date: str, content: str) -> str`, `sync_day(journal_root: pathlib.Path, vault_root: pathlib.Path, date: str) -> pathlib.Path | None`, and a CLI entry point `python -m src.orchestration.sync_vault --journal-root <path> --vault-root <path> --date <date>` — consumed by `daily_summary.py`'s new subprocess call.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sync_vault.py`:

```python
import sys
import tempfile
import unittest
from pathlib import Path

from src.orchestration.sync_vault import main, render_vault_note, sync_day


class SyncVaultTests(unittest.TestCase):
    def test_sync_day_returns_none_when_source_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal_root = root / "journal"
            vault_root = root / "vault"
            journal_root.mkdir()
            vault_root.mkdir()

            result = sync_day(journal_root, vault_root, "2026-08-28")

            self.assertIsNone(result)

    def test_sync_day_writes_note_with_frontmatter_and_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal_root = root / "journal"
            vault_root = root / "vault"
            (journal_root / "daily").mkdir(parents=True)
            (journal_root / "daily" / "2026-08-28.md").write_text(
                "# Automatic Activity Journal — 2026-08-28\n\nChatted with Dariush about the project.\n",
                encoding="utf-8",
            )
            friends = vault_root / "People" / "Friends"
            friends.mkdir(parents=True)
            (friends / "DariushSeif.md").write_text("", encoding="utf-8")

            result = sync_day(journal_root, vault_root, "2026-08-28")

            self.assertEqual(result, vault_root / "Journal" / "Daily" / "2026-08-28.md")
            written = result.read_text(encoding="utf-8")
            self.assertIn("date: 2026-08-28", written)
            self.assertIn("tags: [activity-journal, generated]", written)
            self.assertIn("[[DariushSeif|Dariush]]", written)

    def test_sync_day_overwrites_on_rerun(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal_root = root / "journal"
            vault_root = root / "vault"
            (journal_root / "daily").mkdir(parents=True)
            source = journal_root / "daily" / "2026-08-28.md"
            source.write_text("First version.\n", encoding="utf-8")

            first = sync_day(journal_root, vault_root, "2026-08-28")
            source.write_text("Second version.\n", encoding="utf-8")
            second = sync_day(journal_root, vault_root, "2026-08-28")

            self.assertEqual(first, second)
            second_text = second.read_text(encoding="utf-8")
            self.assertIn("Second version.", second_text)
            self.assertNotIn("First version.", second_text)

    def test_render_vault_note_shape(self):
        note = render_vault_note("2026-08-28", "Some content.")

        self.assertTrue(note.startswith("---\ndate: 2026-08-28\ntags: [activity-journal, generated]\n---\n\n"))
        self.assertIn("Some content.", note)

    def test_main_exits_zero_and_warns_on_write_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal_root = root / "journal"
            (journal_root / "daily").mkdir(parents=True)
            (journal_root / "daily" / "2026-08-28.md").write_text("Content.\n", encoding="utf-8")
            vault_root = root / "vault_is_a_file"
            vault_root.write_text("", encoding="utf-8")

            old_argv = sys.argv
            sys.argv = [
                "sync_vault",
                "--journal-root", str(journal_root),
                "--vault-root", str(vault_root),
                "--date", "2026-08-28",
            ]
            try:
                exit_code = main()
            finally:
                sys.argv = old_argv

            self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_sync_vault.py -v`
Expected: FAIL — `src.orchestration.sync_vault` does not exist yet.

- [ ] **Step 3: Implement `sync_vault.py`**

Create `src/orchestration/sync_vault.py`:

```python
"""Mirror the daily activity journal into the Obsidian vault, with auto-linked mentions."""

from __future__ import annotations

import argparse
import datetime as dt
import pathlib

from src.orchestration.vault_linker import build_name_index, inject_links


def render_vault_note(date: str, content: str) -> str:
    frontmatter = f"---\ndate: {date}\ntags: [activity-journal, generated]\n---\n\n"
    return frontmatter + content.strip() + "\n"


def sync_day(journal_root: pathlib.Path, vault_root: pathlib.Path, date: str) -> pathlib.Path | None:
    source = journal_root / "daily" / f"{date}.md"
    if not source.exists():
        return None
    content = source.read_text(encoding="utf-8")
    index = build_name_index(vault_root)
    linked = inject_links(content, index)
    note = render_vault_note(date, linked)
    target = vault_root / "Journal" / "Daily" / f"{date}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(note, encoding="utf-8")
    return target


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal-root", required=True, type=pathlib.Path)
    parser.add_argument("--vault-root", required=True, type=pathlib.Path)
    parser.add_argument("--date", default=dt.date.today().isoformat())
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = sync_day(args.journal_root, args.vault_root, args.date)
    except OSError as error:
        print(f"Vault sync failed: {error}")
        return 0
    if result is None:
        print("Vault sync: nothing to sync yet")
        return 0
    print(str(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_sync_vault.py -v`
Expected: all PASS.

- [ ] **Step 5: Wire into `daily_summary.py`**

In `src/orchestration/daily_summary.py`, find the end of `main()`:

```python
    subprocess.run([sys.executable, "-m", "src.analysis.build_llm_context", "--journal-root", str(args.journal_root), "--date", args.date], cwd=pathlib.Path(__file__).parents[2])
    result = subprocess.run([sys.executable, "-m", "src.analysis.synthesize_journal", "--journal-root", str(args.journal_root), "--config", str(args.config), "--date", args.date], cwd=pathlib.Path(__file__).parents[2])
    print(str(daily_path))
    return result.returncode
```

Replace with:

```python
    subprocess.run([sys.executable, "-m", "src.analysis.build_llm_context", "--journal-root", str(args.journal_root), "--date", args.date], cwd=pathlib.Path(__file__).parents[2])
    result = subprocess.run([sys.executable, "-m", "src.analysis.synthesize_journal", "--journal-root", str(args.journal_root), "--config", str(args.config), "--date", args.date], cwd=pathlib.Path(__file__).parents[2])

    config = json.loads(args.config.read_text(encoding="utf-8"))
    vault_root = config.get("vaultRoot")
    if vault_root:
        subprocess.run([sys.executable, "-m", "src.orchestration.sync_vault", "--journal-root", str(args.journal_root), "--vault-root", str(vault_root), "--date", args.date], cwd=pathlib.Path(__file__).parents[2])

    print(str(daily_path))
    return result.returncode
```

`json` is already imported at the top of `daily_summary.py` — no new import needed. The sync subprocess's exit code is intentionally not checked (sync failures never affect the pipeline's own exit code, per the Global Constraints above).

- [ ] **Step 6: Document the new config key**

In `config/settings.example.json`, add a `"vaultRoot"` key after `"repositoryPath"`:

```json
  "repositoryPath": "C:\\Path\\To\\jarvis-activity-journal",
  "vaultRoot": "C:\\Path\\To\\ObsidianVault",
```

(Leaving it unset or empty in a real `config/settings.json` keeps the sync step disabled — this is documentation of the key, not an activation.)

- [ ] **Step 7: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass, no regressions.

- [ ] **Step 8: Commit**

```bash
git add src/orchestration/sync_vault.py tests/test_sync_vault.py src/orchestration/daily_summary.py config/settings.example.json
git commit -m "feat(orchestration): sync daily journal into the Obsidian vault"
```

---

## Self-Review

**Spec coverage:** write method (direct filesystem, Task 2) ✓, vault location `Journal/Daily/<date>.md` (Task 2, `sync_day`) ✓, daily-only scope (both tasks only ever handle `daily/<date>.md`, no hourly/weekly path) ✓, fuzzy wikilink matching with ambiguity skip (Task 1) ✓, trigger chained onto `daily_summary.py` (Task 2 Step 5) ✓, non-fatal error handling (Task 2's `main()`) ✓, opt-in via `vaultRoot` config (Task 2 Step 5-6) ✓.

**Placeholder scan:** no TBD/TODO; every step has real, complete code.

**Type consistency:** `sync_day` returns `pathlib.Path | None`, matching both its test assertions and `main()`'s `if result is None` check. `build_name_index`/`inject_links` signatures in Task 1 match exactly how Task 2's `sync_vault.py` imports and calls them.

**Note left for whoever runs this plan:** after both tasks land and are reviewed, activating the feature for Amin's real setup means setting `"vaultRoot": "D:\\JARVIS"` in the *live* `config/settings.json` (not `settings.example.json`, and not part of either task's TDD steps — this is a runtime config activation, not code). Flag this to the user rather than doing it silently, since it's the first point this pipeline writes into the JARVIS vault automatically.
