# Solutions Index

Check here before investigating a bug — the root cause and fix may already be documented.

## Problem → Document

| Problem | Document |
|---------|----------|
| Sessions show "just now" for elapsed time | [timestamp-z-suffix-parsing.md](./timestamp-z-suffix-parsing.md) |
| Dismissed sessions still appear in TUI | [dismissal-log-filename-mismatch.md](./dismissal-log-filename-mismatch.md) |
| `/clear` sessions or `(no messages)` entries appearing | [clear-session-and-subagent-filtering.md](./clear-session-and-subagent-filtering.md) |
| Subagent JSONL files appearing as sessions | [clear-session-and-subagent-filtering.md](./clear-session-and-subagent-filtering.md) |
| Enter key (or any key binding) silently ignored | [enter-key-open-session.md](./enter-key-open-session.md) |
| Subprocess frozen / unresponsive after TUI closes | [claude-code-session-tui-lessons.md](./claude-code-session-tui-lessons.md) |

## All Documents

| Document | What it covers |
|----------|----------------|
| [implementation-checklist.md](./implementation-checklist.md) | Phase-by-phase checklist for Textual TUI + Claude Code integrations |
| [claude-code-session-tui-lessons.md](./claude-code-session-tui-lessons.md) | 7 critical discoveries, architecture patterns, common pitfalls table |
| [timestamp-z-suffix-parsing.md](./timestamp-z-suffix-parsing.md) | **Definitive fix**: Python 3.10 `fromisoformat()` rejects `Z` suffix — normalise to `+00:00` |
| [clear-session-and-subagent-filtering.md](./clear-session-and-subagent-filtering.md) | Filtering `/clear` artifacts and subagent JSONL files from session list |
| [dismissal-log-filename-mismatch.md](./dismissal-log-filename-mismatch.md) | Hook writes `session.log` (singular); code must use the same filename |
| [enter-key-open-session.md](./enter-key-open-session.md) | `priority=True` required for app bindings to override widget-level handlers |

## Notes for agents

- **Line numbers** in solution docs are approximate at time of writing — verify against current code before acting.
- When fixing a new issue, add a row to this index and create a solution doc following the structure of existing files.
- If your fix covers the same topic as an existing doc, update that doc rather than creating a new one.
