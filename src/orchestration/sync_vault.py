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
