---
title: Hourly/daily/weekly reports share one screen-aware format
status: active
added: 2026-08-28
---

Hourly, daily and weekly journal files share one Markdown format — summary paragraph, `### Timeline`, `### Patterns`. Reports are analysis only: they describe and interpret what was observed and contain no next actions or advice. Length grows with the period: a daily report may be longer than an hourly one, and a weekly longer than a daily. `### On screen` appears only in the per-screenshot files, which record concrete details of what the vision model saw. Each level is built only from the level below: per-screenshot Markdown files → hourly (plus that hour's active windows) → daily → weekly. No model-reported confidence appears anywhere.

**Why:** Amin wanted all report levels in one format built as a compaction chain, dropped confidence and Next actions, allowed longer reports at higher levels, and wanted On screen details only in per-screenshot files.
**Scope:** `src/analysis/report_levels.py`, `src/analysis/report_render.py`, `src/analysis/synthesize_period.py`, `src/analysis/screen_markdown.py`, `src/analysis/analyze_screenshots.py`.
