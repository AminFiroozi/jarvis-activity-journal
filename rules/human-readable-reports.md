---
title: Human-readable text in hourly/weekly/daily reports
status: active
added: 2026-08-28
---

Hourly, weekly, and daily journal output must read as plain human text — prose sentences, local time, real app/activity descriptions — never raw event IDs, ISO8601-with-microseconds timestamps, or backtick-coded evidence dumps.

**Why:** the deterministic hourly/weekly renderer (`journalize.py`) originally rendered sessions as `Evidence: \`event-24\`, \`event-25\`, ...` and evidence lines as `` `unknown` — 2026-08-28T03:30:21.3515520Z — foreground-window — explorer`` — technically correct but unreadable to a human skimming the file. The user asked for this fixed and to make it a standing rule so it doesn't regress.
**Scope:** `src/analysis/journalize.py` (`render_journal`), `src/analysis/sessionize.py` (session fields consumed by it), `src/orchestration/daily_summary.py`'s deterministic scaffold, and any future report renderer in this project.
