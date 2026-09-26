---
title: Hourly/daily/weekly reports share one screen-aware format
status: active
added: 2026-08-28
---

Hourly, daily and weekly journal files share one Markdown format — summary paragraph, `### On screen`, `### Timeline`, `### Patterns` — differing only in depth: hourly is fine-grained, daily groups by task, weekly stays general. Reports are analysis only: they describe and interpret what was observed and contain no next actions or advice. `### On screen` records concrete details of what the vision model saw. Each level is built only from the level below: per-screenshot Markdown files → hourly (plus that hour's active windows) → daily → weekly. No model-reported confidence appears anywhere.

**Why:** Amin wanted all report levels in one format with screen details, built as a compaction chain, dropped confidence, and then asked for analysis only (no Next actions) while keeping Patterns.
**Scope:** `src/analysis/report_levels.py`, `src/analysis/report_render.py`, `src/analysis/synthesize_period.py`, `src/analysis/screen_markdown.py`, `src/analysis/analyze_screenshots.py`.
