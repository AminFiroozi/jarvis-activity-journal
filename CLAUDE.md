# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project rules

`rules/` holds durable product rules for this project — one file per rule, plain slug filename. Read it at the start of a session touching this repo, and always before changing the area a rule governs. **Rules in `rules/` are binding — follow them.**

**Suggesting new rules:** if during a session you spot a decision, correction, or constraint that should hold for the rest of this project's life (not just the current task), don't silently add it. Propose it interactively — show the draft rule text (title, the rule, why, scope) and ask via a UI choice (add it / skip / edit first). Only write to `rules/<slug>.md` on explicit approval. See `rules/README.md` for the file format.
