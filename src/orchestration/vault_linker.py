"""Match narrative text against Obsidian vault note filenames and inject wikilinks."""

from __future__ import annotations

import pathlib
import re

_NAME_GLOBS = ("People/**/*.md", "Projects/*.md", "Skills/*.md")

_STEM_WORD_PATTERN = re.compile(r"[A-Z][a-z0-9]*|[a-z0-9]+")
_TEXT_WORD_PATTERN = re.compile(r"\[\[.*?\]\]|[A-Za-z][A-Za-z0-9]*")

_COMPANION_SUFFIXES = (" - Activity Mentions", " - Activity Log")


def _split_tokens(stem: str) -> list[str]:
    if any(separator in stem for separator in (" ", "-", "_")):
        return [stem.lower()]
    tokens = [word.lower() for word in _STEM_WORD_PATTERN.findall(stem)]
    tokens.append(stem.lower())
    tokens = [token for token in tokens if len(token) >= 3]
    return list(dict.fromkeys(tokens))


def _is_companion_note(stem: str) -> bool:
    return any(stem.endswith(suffix) for suffix in _COMPANION_SUFFIXES)


def build_note_paths(vault_root: pathlib.Path) -> dict[str, list[pathlib.Path]]:
    note_paths: dict[str, list[pathlib.Path]] = {}
    for pattern in _NAME_GLOBS:
        for path in sorted(vault_root.glob(pattern)):
            if not path.is_file():
                continue
            try:
                relative = path.relative_to(vault_root)
            except ValueError:
                continue
            if "History" in relative.parts:
                continue
            if _is_companion_note(path.stem):
                continue
            note_paths.setdefault(path.stem, []).append(path)
    return note_paths


def build_name_index(vault_root: pathlib.Path) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for base_name in build_note_paths(vault_root):
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
        if base_name.lower() == word.lower():
            return f"[[{base_name}]]"
        return f"[[{base_name}|{word}]]"

    return _TEXT_WORD_PATTERN.sub(_replace, text)
