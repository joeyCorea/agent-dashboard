---
title: "Dashboard cold start optimization: lazy-load JSONL message history and async session discovery"
category: performance-issues
date: 2026-03-30
severity: medium
tags:
  - cold-start
  - lazy-loading
  - textual
  - jsonl-parsing
  - memory-optimization
  - async-workers
  - tui-performance
component: src/parser.py, src/ui.py
symptoms:
  - ~10 second cold start delay before UI renders
  - UI completely blocked during session discovery and JSONL parsing
  - High memory usage from storing full message histories for all sessions
  - Delay most noticeable after periods of inactivity (cold OS cache)
root_cause: "refresh_sessions() synchronously parsed every ~/.claude/projects/**/*.jsonl file and stored complete message histories in memory for all sessions, blocking UI render until finished"
---

# Dashboard cold start optimization: lazy-load JSONL message history and async session discovery

## Problem Description

The Python Textual TUI dashboard (claude-dashboard) suffered from ~10s cold start time, making the application feel unresponsive on launch. Users had to wait for the entire data pipeline to complete before seeing any UI. The lag was most noticeable after not having used the dashboard for a while (cold OS disk cache), and faster during repeated use in quick succession (warm cache).

## Root Cause Analysis

Two compounding issues caused the slow startup:

1. **Eager loading of message history:** The `Session` dataclass stored `full_message_history: list[dict]`, meaning every session's entire JSONL file was fully parsed and held in memory at startup -- even though only the `PreviewPane` (hidden by default, toggled with Space) ever consumed this data, and only the last 10 messages at that.

2. **Synchronous blocking of the event loop:** `on_mount()` called `refresh_sessions()` synchronously, which in turn called `discover_sessions()` -> `parse_jsonl()` for every session file under `~/.claude/projects/`. The Textual event loop was blocked until all files were read and parsed, preventing any UI rendering.

A minor secondary finding: `_build_session_cwd_map()` in `parser.py:28` was defined and tested but never called anywhere in production code (dead code).

## Investigation Steps

1. Traced the startup flow: `main.py` -> `app.run()` -> `on_mount()` -> `refresh_sessions()` -> `discover_sessions()` -> `parse_jsonl()` x N files
2. Identified that `full_message_history` was only consumed by `PreviewPane.render()`, which reads `self.session.full_message_history[-10:]`
3. Confirmed that `on_mount()` blocks the Textual event loop until `refresh_sessions()` completes -- no `@work` decorator or async pattern was used anywhere in the codebase
4. Estimated bottleneck contribution: Textual import (~40-60% of cold start), JSONL parsing (~30-50%), with zero caching as an amplifier
5. Found dead code: `_build_session_cwd_map()` defined and tested but never called

## Solution

**Tier 1: Progressive Rendering + Lazy Loading**

Two complementary changes that eliminate both root causes:

### 1. Lazy loading of message history (`src/parser.py`)

Replaced the eagerly-loaded `full_message_history: list[dict]` field on the `Session` dataclass with a `filepath: Path` field. Introduced a standalone `load_message_history(filepath)` function that reads and parses the JSONL on demand.

```python
@dataclass
class Session:
    # ... other fields ...
    filepath: Path          # was: full_message_history: list[dict]
    status: str = "ready"
    project_dir: Optional[str] = None


def load_message_history(filepath: Path) -> list[dict]:
    """Load and return all parsed JSONL lines from a session file on demand."""
    lines = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    lines.append(json.loads(line))
    except Exception:
        return []
    return lines
```

`parse_jsonl()` now stores only the filepath:

```python
return Session(
    # ... other fields ...
    filepath=filepath,      # was: full_message_history=lines
    status=status,
    project_dir=project_dir,
)
```

### 2. Async background loading (`src/ui.py`)

Split `refresh_sessions()` into a background worker and a main-thread UI update:

```python
from textual import work

class PendingSessionsApp(App):

    def on_mount(self):
        # ... set up filter, title, etc. ...
        self._load_sessions()  # non-blocking

    @work(thread=True)
    def _load_sessions(self):
        """Load sessions in a background thread for non-blocking startup."""
        all_sessions = discover_sessions()
        active_sessions = filter_sessions(all_sessions, self._days_filter)
        self.call_from_thread(self._update_session_list, active_sessions)

    def _update_session_list(self, sessions: list[Session]):
        """Update the UI with loaded sessions (called on the main thread)."""
        list_view = self.query_one("#session-list", SessionListView)
        list_view.update_sessions(sessions, grouped=self._grouped)
        list_view.focus()

    def refresh_sessions(self):
        """Refresh the session list from disk."""
        self._load_sessions()
```

### 3. PreviewPane lazy read (`src/ui.py`)

Updated `PreviewPane.render()` to load message history on demand:

```python
class PreviewPane(Static):
    def render(self) -> str:
        if not self.session:
            return ""
        # Load message history on demand (lazy loading)
        full_history = load_message_history(self.session.filepath)
        messages = full_history[-10:]
        # ... format and return preview text ...
```

## Files Changed

- `src/parser.py` -- Session dataclass (`filepath` replaces `full_message_history`), added `load_message_history()`
- `src/ui.py` -- `@work(thread=True)` on `_load_sessions()`, PreviewPane uses `load_message_history()`
- `tests/test_ui_bindings.py` -- Updated `_make_session()` helper to use `filepath=Path("dummy.jsonl")`
- `tests/test_lazy_loading.py` -- New: 7 tests covering Session fields, parse_jsonl filepath, load_message_history edge cases

## Prevention Checklist

- Before adding any field to a dataclass, ask: "Is this field needed for the default view, or only for a secondary/detail view?" If secondary, store a reference (filepath, ID) instead of the full payload.
- Never perform file I/O or heavy parsing inside `on_mount()`, `compose()`, or `__init__()` of a Textual widget. Use `@work(thread=True)` or `self.run_worker()` instead.
- When loading collections, load summary/metadata first; defer detail loading until the user explicitly requests it.
- Review any PR that adds a new field to a frequently-instantiated object (Session, Row, etc.) for eager-loading of expensive data.

## Patterns to Watch For

- **`open()` / `json.load()` / `readlines()` in a constructor** for a model instantiated in bulk -- sign of eager materialization
- **Synchronous calls in `on_mount()` or `compose()`** that do I/O without `@work` -- blocks the Textual event loop
- **Dataclass fields of type `list[dict]` populated at construction** -- should be `Optional` and loaded on demand, or replaced with a path/key
- **"Just load everything, it's small"** -- data that is small today (10 sessions) becomes large tomorrow (10,000)

## Related Documentation

- [Optimization plan](../../docs/plans/2026-03-30-001-perf-dashboard-cold-start-optimization-plan.md) -- Full 4-tier plan (Tier 3 not yet implemented)
- [TUI lessons learned](../../../docs/solutions/claude-code-session-tui-lessons.md) -- Widget lifecycle, async/sync boundaries, `@work` patterns
- [Clear session filtering](../../../docs/solutions/clear-session-and-subagent-filtering.md) -- `_is_clear_session` detection logic (now folded into single-pass parser)
- [Timestamp Z suffix parsing](../../../docs/solutions/timestamp-z-suffix-parsing.md) -- Preserved in single-pass parser rewrite

## Tier 2: Single-Pass Parser (Implemented 2026-03-30)

Rewrote `parse_jsonl()` to extract all metadata in a single pass through the JSONL lines, instead of the previous approach that walked the parsed lines 4-6 times via separate helper functions.

### What changed

- `parse_jsonl()` now reads the file line by line, parsing each line as JSON once, and extracts all fields (session_id, cwd, title, timestamp, last assistant message, status, clear-session detection) in that single loop
- Removed 4 helper functions folded into the single pass: `_is_clear_session`, `_determine_status`, `_extract_title`, `_extract_last_assistant_message`
- Removed dead code: `_build_session_cwd_map()` (was defined and tested but never called in production)
- Removed 6 tests for `_build_session_cwd_map`; remaining 47 tests all pass
- `parser.py` went from 367 lines to 277 lines (24% reduction)

### Key design decisions

- **Timestamp: last one wins.** The old code walked reversed lines to find the last timestamp. The single-pass approach keeps overwriting `last_timestamp` on each line, so the final value is naturally the last one.
- **Title priority preserved.** `ai-title` type entries take precedence (first one wins via `if not title` guard). First user message text is tracked separately as `first_user_text` for the fallback.
- **Clear session detection unchanged.** Still checks `has_clear_command AND NOT has_assistant` after the loop completes -- the logic requires seeing all lines before deciding.
- **Z suffix handling preserved.** The `Z` → `+00:00` replacement for Python 3.10 compat is inline in the timestamp extraction block.

### Prevention note

When adding new metadata extraction to `parse_jsonl`, add it to the single loop body rather than creating a new helper that re-walks the lines. The single-pass pattern must be maintained.

## Future Work (Tier 3)

- **Tier 3: Metadata cache with mtime invalidation** -- Cache parsed metadata to `~/.claude/dashboard-cache.json`, only re-parse files whose mtime changed
