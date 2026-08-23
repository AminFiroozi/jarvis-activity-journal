# Activity session detection

`src.sessionize.detect_sessions(events)` consumes parsed JSONL event dictionaries and returns deterministic session dictionaries. It does not require SQLite and does not mutate the input events.

Each session contains:

- `id`: stable-in-call identifier such as `session-1`.
- `startAt` and `endAt`: the earliest and latest usable event timestamps.
- `classification`: `coding`, `browsing`, `communication`, `terminal`, `meeting`, `idle`, or `mixed`.
- `confidence`: a bounded evidence-strength score from `0.0` to `1.0`.
- `eventIds`: source event IDs, with an `event-N` fallback when an event has no ID.

Events are ordered by `observedAt`, then `timestamp`, then `localTimestamp`. Adjacent events remain in a session only when their gap is less than 15 minutes, their project identifiers do not conflict, and their application/evidence context is compatible. An application change between different activity classes starts a new session. An IDE and terminal can remain together when they share a project/context; coding is the resulting classification when coding evidence is at least as strong as terminal evidence.

Idle events (`active: false`, `idle: true`, a long `idleSeconds` value, or explicit idle evidence) always form their own idle session and break active work. Classification uses only fields present in the events: explicit activity labels take precedence, followed by application/process/window evidence. Multiple compatible, unrelated labels produce `mixed` rather than an inferred intent.
