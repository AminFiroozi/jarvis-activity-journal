"""Match narrative text against Obsidian vault note filenames and inject wikilinks."""

from __future__ import annotations

import pathlib
import re

_NAME_GLOBS = ("People/**/*.md", "Projects/*.md", "Skills/*.md")

_STEM_WORD_PATTERN = re.compile(r"[A-Z][a-z0-9]*|[a-z0-9]+")
_TEXT_WORD_PATTERN = re.compile(r"\[\[.*?\]\]|[A-Za-z][A-Za-z0-9]*")


def _split_tokens(stem: str) -> list[str]:
    if any(separator in stem for separator in (" ", "-", "_")):
        return [stem.lower()]
    tokens = [word.lower() for word in _STEM_WORD_PATTERN.findall(stem)]
    tokens.append(stem.lower())
    tokens = [token for token in tokens if len(token) >= 3]
    return list(dict.fromkeys(tokens))


def build_name_index(vault_root: pathlib.Path) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for pattern in _NAME_GLOBS:
        for path in sorted(vault_root.glob(pattern)):
            if not path.is_file():
                continue
            if "History" in path.parts:
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
        if base_name.lower() == word.lower():
            return f"[[{base_name}]]"
        return f"[[{base_name}|{word}]]"

    return _TEXT_WORD_PATTERN.sub(_replace, text)
