---
title: Capture chat topic, correspondent, and a detailed non-verbatim account for messaging screenshots
status: active
added: 2026-08-28
---

When a screenshot shows a chat/messaging page — in a messaging app or in a browser — the vision analysis must capture who the conversation is with (contact or group name), the topic, and a detailed, precise non-verbatim account of what is visible: who said what in order, questions, requests, decisions, deadlines, numbers, ticket IDs, file names, link domains, and what is unanswered. Message text is still never transcribed verbatim, and passwords, tokens, phone numbers and handles are still omitted.

**Why:** Amin first asked for topic, correspondent and a short gist instead of "capture nothing"; he then asked chat screenshots to collect more detail and be more precise, because a short gist threw away useful specifics.
**Scope:** `config/prompts.json`'s `contexts.messaging` instructions and `base.instructions` (which must apply the chat guidance in every context, including browsers, while still barring verbatim message text, passwords, tokens, and other secrets), and the report prompts in `src/analysis/report_levels.py`.
