# Roadmap

Ideas agreed but not yet designed or scheduled. Each item gets its own brainstorm, spec and plan before any code.

## Tracked people and projects, updated hourly

Work with an explicitly defined set of people and projects, and refresh what the journal has learned about each of them after every hourly update.

- **Defined set:** a list of people and projects the journal cares about, kept in one place the user edits. Today the roster is derived from the Obsidian vault note names (`sync_entities.py`), so nothing works without a vault.
- **Hourly refresh:** after each hourly report is built, update the learned information for any tracked person or project that shows up in it. Today `entityUpdates` runs once a day from the daily narrative and appends a dated entry.
- **Learned info, not a log:** each entity keeps a current summary (who or what it is, recent activity, open threads) that later hours revise, rather than only a dated list of entries.
- **Builds on:** the hierarchical report chain (`docs/superpowers/specs/2026-09-26-hierarchical-reports-design.md`). The hourly report and the per-screenshot files are the source of what to learn.

Open questions for its brainstorm: where the defined set lives (config file or vault), how an entity's summary is revised without drifting or inventing facts, and how chat correspondents map to tracked people while message text stays out of the record.
