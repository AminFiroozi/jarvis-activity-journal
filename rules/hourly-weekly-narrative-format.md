---
title: Hourly/weekly journals follow daily's narrative format
status: active
added: 2026-08-28
---

Hourly and weekly journal Markdown files use the same LLM-narrative style as `daily/<date>.md` — summary paragraph, `### Timeline`, `### Patterns`, `### Next actions`, `_LLM confidence: N_` — instead of the current deterministic session+evidence dump. The narrative replaces the evidence list entirely, matching daily's own format exactly. Hourly stays fine-grained/detailed; weekly stays general and summary-level, covering fewer, broader points.

**Why:** Amin said daily's format "looks cool" and asked hourly/weekly to follow it, with hourly more detailed and weekly more general.
**Scope:** `src/analysis/journalize.py` (`render_journal` and its callers), `src/analysis/build_journals.py`, `src/analysis/synthesize_journal.py` (or whatever shared narrative-writing module replaces/extends it for per-hour and per-week synthesis).
