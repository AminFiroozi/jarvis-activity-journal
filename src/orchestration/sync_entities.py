"""Judge daily entity noteworthiness and append companion notes to the Obsidian vault."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re

from src.analysis.entity_facts import build_evidence, extract_entity_facts, validate_facts
from src.infra.heartbeat import write_heartbeat
from src.orchestration.vault_linker import build_name_index, build_note_paths, inject_links
from src.providers.model_client import resolve_provider

_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CATEGORY_ROOTS = {"people": "People", "projects": "Projects"}


def _filter_by_category(paths: list[pathlib.Path], category: str, vault_root: pathlib.Path) -> list[pathlib.Path]:
    root_name = _CATEGORY_ROOTS[category]
    matches = []
    for path in paths:
        try:
            relative = path.relative_to(vault_root)
        except ValueError:
            continue
        if relative.parts and relative.parts[0] == root_name:
            matches.append(path)
    return matches


def _resolve_candidates(
    candidates: list[str] | None,
    note_paths: dict[str, list[pathlib.Path]],
    category: str,
    vault_root: pathlib.Path,
) -> pathlib.Path | None:
    if not candidates or len(candidates) != 1:
        return None
    matches = _filter_by_category(note_paths.get(candidates[0], []), category, vault_root)
    return matches[0] if len(matches) == 1 else None


def resolve_note_name(
    proposed: str,
    index: dict[str, list[str]],
    note_paths: dict[str, list[pathlib.Path]],
    category: str,
    vault_root: pathlib.Path,
) -> pathlib.Path | None:
    name = " ".join(str(proposed).split()).strip()
    if not name:
        return None
    lowered = name.lower()

    stem_matches = [stem for stem in note_paths if stem.lower() == lowered]
    if stem_matches:
        if len(stem_matches) != 1:
            return None
        matches = _filter_by_category(note_paths[stem_matches[0]], category, vault_root)
        return matches[0] if len(matches) == 1 else None

    resolved = _resolve_candidates(index.get(lowered), note_paths, category, vault_root)
    if resolved is not None:
        return resolved

    stripped = re.sub(r"[ _-]", "", name).lower()
    if stripped != lowered:
        resolved = _resolve_candidates(index.get(stripped), note_paths, category, vault_root)
        if resolved is not None:
            return resolved

    words = [word.lower() for word in re.split(r"[ _-]+", name) if len(word) >= 3]
    if len(words) >= 2:
        candidate_sets = [set(index.get(word, [])) for word in words]
        if all(candidate_sets):
            intersection = sorted(set.intersection(*candidate_sets))
            resolved = _resolve_candidates(intersection, note_paths, category, vault_root)
            if resolved is not None:
                return resolved

    return None


def companion_path(note_path: pathlib.Path, category: str) -> pathlib.Path:
    suffix = " - Activity Mentions" if category == "people" else " - Activity Log"
    return note_path.parent / f"{note_path.stem}{suffix}.md"


def render_companion_header(stem: str, category: str) -> str:
    label = "Activity Mentions" if category == "people" else "Activity Log"
    entity_type = "person" if category == "people" else "project"
    return (
        f'---\nentity: {stem}\ntype: {entity_type}\nup: "[[{stem}]]"\ntags: [activity-journal, generated]\n---\n\n'
        f"# {stem} — {label}\n\n"
        f"Auto-generated companion log for [[{stem}]]. Appended by the activity journal; the curated note is never modified.\n"
    )


def render_entry(date: str, note: str, evidence: list[str], confidence: float) -> str:
    lines = [f"## {date}", "", note.strip(), ""]
    if evidence:
        lines.append(f"_Evidence: {'; '.join(evidence)}_")
    lines.append(f"_Source: [[Journal/Daily/{date}|daily journal]] · confidence: {confidence}_")
    return "\n".join(lines).rstrip() + "\n"


def append_entry(path: pathlib.Path, stem: str, category: str, date: str, entry_body: str) -> pathlib.Path | None:
    heading_pattern = re.compile(rf"^## {re.escape(date)}\s*$", re.MULTILINE)
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if heading_pattern.search(existing):
            return None
        updated = existing.rstrip() + "\n\n" + entry_body
    else:
        updated = render_companion_header(stem, category) + "\n" + entry_body
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(updated, encoding="utf-8")
    return path


def _write_status(journal_root: pathlib.Path, date: str, status: dict) -> dict:
    status_path = journal_root / "raw" / f"entities-{date}.status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return status


def sync_entities(journal_root: pathlib.Path, vault_root: pathlib.Path, config: dict, date: str, dry_run: bool = False) -> dict:
    if not _DATE_PATTERN.match(date):
        return {"date": date, "status": "invalid-date", "written": [], "skipped": []}

    stage_config = config.get("entityUpdates") or {}
    if not stage_config.get("enabled"):
        return {"date": date, "status": "disabled", "written": [], "skipped": []}

    note_paths = build_note_paths(vault_root)
    index = build_name_index(vault_root)
    roster = {
        "people": sorted({stem for stem, paths in note_paths.items() if _filter_by_category(paths, "people", vault_root)}),
        "projects": sorted({stem for stem, paths in note_paths.items() if _filter_by_category(paths, "projects", vault_root)}),
    }

    evidence = build_evidence(journal_root, date, roster)
    if not evidence["narrative"] and not evidence["events"] and not evidence["projects"]:
        return _write_status(journal_root, date, {"date": date, "status": "no-events", "written": [], "skipped": []})
    if not roster["people"] and not roster["projects"]:
        return _write_status(journal_root, date, {"date": date, "status": "no-events", "written": [], "skipped": []})

    provider = resolve_provider(config, "entityUpdates")
    try:
        raw_payload = extract_entity_facts(provider, evidence, max_chars=int(stage_config.get("maxEvidenceChars", 8000)))
    except (ValueError, json.JSONDecodeError) as error:
        return _write_status(journal_root, date, {"date": date, "status": "failed", "written": [], "skipped": [], "error": str(error)})

    raw_path = journal_root / "raw" / f"entities-{date}.json"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    validated = validate_facts(raw_payload)
    min_confidence = float(stage_config.get("minConfidence", 0.0))
    max_per_day = int(stage_config.get("maxEntitiesPerDay", 5))

    written: list[dict] = []
    skipped: list[dict] = []
    for category in ("people", "projects"):
        resolved: dict[pathlib.Path, dict] = {}
        for entry in validated[category]:
            if entry["confidence"] < min_confidence:
                skipped.append({"name": entry["name"], "category": category, "reason": "below-min-confidence"})
                continue
            note_path = resolve_note_name(entry["name"], index, note_paths, category, vault_root)
            if note_path is None:
                skipped.append({"name": entry["name"], "category": category, "reason": "unresolved-or-ambiguous"})
                continue
            existing = resolved.get(note_path)
            if existing is None or entry["confidence"] > existing["confidence"]:
                if existing is not None:
                    skipped.append({"name": existing["name"], "category": category, "reason": "superseded-by-higher-confidence"})
                resolved[note_path] = entry
            else:
                skipped.append({"name": entry["name"], "category": category, "reason": "superseded-by-higher-confidence"})
        ranked = sorted(resolved.items(), key=lambda item: item[1]["confidence"], reverse=True)[:max_per_day]
        for note_path, entry in ranked:
            note_text = inject_links(entry["note"], index)
            entry_body = render_entry(date, note_text, entry["evidence"], entry["confidence"])
            target = companion_path(note_path, category)
            if dry_run:
                written.append({"name": note_path.stem, "category": category, "path": str(target)})
                continue
            result_path = append_entry(target, note_path.stem, category, date, entry_body)
            if result_path is None:
                skipped.append({"name": note_path.stem, "category": category, "reason": "already-present"})
            else:
                written.append({"name": note_path.stem, "category": category, "path": str(result_path)})

    return _write_status(journal_root, date, {"date": date, "status": "complete", "written": written, "skipped": skipped})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal-root", required=True, type=pathlib.Path)
    parser.add_argument("--config", required=True, type=pathlib.Path)
    parser.add_argument("--vault-root", required=True, type=pathlib.Path)
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _write_heartbeat_safely(journal_root: pathlib.Path, service: str, status: str, **kwargs) -> None:
    try:
        write_heartbeat(journal_root, service, status, **kwargs)
    except Exception:  # heartbeat failure must never crash main()
        pass


def main() -> int:
    args = parse_args()
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"Entity sync failed: {error}")
        return 0
    try:
        result = sync_entities(args.journal_root, args.vault_root, config, args.date, dry_run=args.dry_run)
    except Exception as error:  # sync must never fail the nightly pipeline
        _write_heartbeat_safely(args.journal_root, "entity-updates", "failed", error_message=str(error))
        print(f"Entity sync failed: {error}")
        return 0
    if result.get("status") == "complete":
        _write_heartbeat_safely(args.journal_root, "entity-updates", "success", items_processed=len(result.get("written", [])))
    elif result.get("status") == "failed":
        _write_heartbeat_safely(args.journal_root, "entity-updates", "failed", error_message=result.get("error", ""))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
