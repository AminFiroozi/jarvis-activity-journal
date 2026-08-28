# Product Rules

One file per durable rule — a decision, correction, or constraint meant to hold for the rest of this project's life, not just one task. Plain slug filenames (`rules/<slug>.md`), alphabetical.

Each file:

```markdown
---
title: <short title>
status: active
added: <YYYY-MM-DD>
---

<the rule, one or two sentences, imperative>

**Why:** <the incident or reasoning behind it>
**Scope:** <what part of the project this governs>
```

Claude does not add rules unilaterally — only on explicit approval, proposed interactively (draft shown, confirmed via a UI choice) when a rule-worthy moment comes up during a session. See `CLAUDE.md` for the suggestion-flow trigger.

Rules here are binding: once added, they must be followed for this project until marked `status: retired` (kept in place with the status change, not deleted, so the history stays visible).
