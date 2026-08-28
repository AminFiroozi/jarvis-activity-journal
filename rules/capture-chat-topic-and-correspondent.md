---
title: Capture chat topic, correspondent, and gist for messaging screenshots
status: active
added: 2026-08-28
---

When a screenshot shows a chat/messaging page, the vision analysis must capture the topic being discussed, who the conversation is with (contact or group name), and a short non-verbatim gist of the conversation — not just "chatting" with no detail. Message text still isn't transcribed verbatim; this is a summary-level relaxation of the prior "capture nothing" stance, not a switch to full transcription.

**Why:** Amin asked for this — the previous "messaging" context instruction ("Do not transcribe message bodies, names, contact details... or other private content") threw away exactly the detail that makes a chat entry useful in the journal.
**Scope:** `config/prompts.json`'s `contexts.messaging` instructions (and `base.instructions`' blanket "omit... message bodies" line, which needs to allow topic/correspondent/gist through while still barring verbatim message text, passwords, tokens, and other secrets).
