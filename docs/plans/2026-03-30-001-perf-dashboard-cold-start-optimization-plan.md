---
title: "perf: Dashboard cold start optimization"
type: refactor
status: active
date: 2026-03-30
---

# perf: Dashboard cold start optimization

## Overview

The claude-dashboard TUI takes ~10 seconds on cold start. The lag is most noticeable after not having used the dashboard for a while; repeated use in quick succession is faster (OS disk cache + Python bytecode cache warm up). This plan targets reducing cold start to under 3 seconds through a combination of caching, lazy loading, async rendering, and parser optimization.

## Problem Statement

The current startup flow is entirely synchronous and does maximum work upfront:

```
main.py
└── app.run()
    └── on_mount()          # synchronous — blocks UI render
        └── refresh_sessions()
            ├── discover_sessions()        # globs + reads + parses ALL .jsonl files
            │   └── parse_jsonl() × N      # each file walked 4+ times
            │       ├── _is_clear_session()           # walk 1: all lines
            │       ├── extract session_id/cwd        # walk 2: lines until found
            │       ├── _extract_title()               # walk 3: all lines
            │       ├── find last timestamp            # walk 4: reversed lines
            │       ├── _extract_last_assistant_message() # walk 5: reversed lines
            │       └── _determine_status()            # walk 6: reversed lines
            └── filter_sessions()
                └── read_dismissed_ids()   # disk I/O
```

**Bottlenecks (estimated contribution):**

| Bottleneck | % of cold start | Why |
|---|---|---|
| Textual import | 40-60% | Heavy UI framework, many submodules |
| JSONL parsing | 30-50% | Every session file fully read + parsed; lines walked 4-6 times each |
| No caching | amplifier | All work repeated from scratch every launch |
| Synchronous on_mount | UX | UI doesn't render until all parsing completes |

**Additional findings from code review:**
- `full_message_history` (all parsed JSONL lines) is stored in every `Session` object but only used by `PreviewPane`, which is **hidden by default** (`self.visible = False`)
- `_build_session_cwd_map()` in `parser.py:28` is defined and tested but **never called in production code** — dead code
- `filter_sessions()` re-reads `~/.claude/session.log` from disk on every call (startup + every refresh)

## Proposed Solution

Four optimization tiers, ordered by impact and independence:

### Tier 1: Async/Progressive Rendering (Highest UX impact, lowest risk)

Show the UI shell immediately, load sessions in the background using Textual's built-in worker system.

**Changes:**
- `src/ui.py`: Make `refresh_sessions()` async using `@work` decorator
- `src/ui.py`: Add a loading indicator while sessions load
- `src/ui.py:on_mount()`: Call worker instead of blocking

```python
# src/ui.py — on_mount becomes non-blocking
def on_mount(self):
    self._days_filter = self._initial_days
    self._grouped = True
    self.title = "Claude Code Pending Sessions"
    self.sub_title = filter_subtitle(self._days_filter)
    self._load_sessions()  # non-blocking worker

@work(thread=True)
def _load_sessions(self):
    all_sessions = discover_sessions()
    active_sessions = filter_sessions(all_sessions, self._days_filter)
    self.call_from_thread(self._update_ui, active_sessions)

def _update_ui(self, sessions):
    list_view = self.query_one("#session-list", SessionListView)
    list_view.update_sessions(sessions, grouped=self._grouped)
```

**Benefit:** UI appears instantly. Parsing happens in background thread. Perceived startup drops to <1s even if total parse time is unchanged.

### Tier 2: Lazy Loading of Message History (Highest memory + parse savings)

Stop storing `full_message_history` in every Session. Load it on-demand when the preview pane is toggled.

**Changes:**
- `src/parser.py:Session`: Replace `full_message_history: list[dict]` with `filepath: Path` (store source file path instead)
- `src/parser.py:parse_jsonl()`: Stop returning all parsed lines in the Session. Extract only metadata (title, timestamp, status, last_assistant_message, session_id, project_dir)
- `src/parser.py`: Add `load_message_history(filepath: Path) -> list[dict]` function for on-demand loading
- `src/ui.py:PreviewPane`: Call `load_message_history()` when preview is toggled instead of reading from `session.full_message_history`

**Benefit:** Avoids parsing and storing full message content for all sessions. Only the selected session's history is loaded when the user requests it.

### Tier 3: Single-Pass Parser (Reduce per-file work by ~4x)

Replace the multiple-walk approach with a single pass that extracts all needed fields at once.

**Changes to `src/parser.py:parse_jsonl()`:**

```python
# src/parser.py — single-pass extraction
def parse_jsonl(filepath: Path) -> Optional[Session]:
    session_id = None
    project_dir = None
    title = None
    has_clear_command = False
    has_assistant = False
    last_timestamp = None
    last_assistant_msg = ""
    last_conversational_role = None
    first_user_text = None

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            msg = json.loads(line)

            # Extract session_id and cwd (first occurrence)
            if not session_id and "sessionId" in msg:
                session_id = msg["sessionId"]
            if not project_dir and "cwd" in msg:
                project_dir = msg["cwd"]

            # ai-title (first one wins)
            if not title and msg.get("type") == "ai-title":
                raw = msg.get("message", {}).get("content", "").strip()
                if raw:
                    title = _truncate(raw, 40)

            message = msg.get("message", {})
            role = message.get("role")
            content = message.get("content", "")

            # Track clear session detection
            if isinstance(content, str) and "<command-name>/clear</command-name>" in content:
                has_clear_command = True

            if role == "assistant":
                has_assistant = True
                text = _extract_text_from_content(content)
                if text:
                    last_assistant_msg = _truncate(text.split("\n")[0], 70)

            if role == "user":
                if first_user_text is None:
                    text = _extract_text_from_content(content)
                    if text:
                        first_user_text = _truncate(text.split("\n")[0], 40)

            if role in ("user", "assistant"):
                last_conversational_role = role

            # Timestamp (keep last one)
            if "timestamp" in msg:
                try:
                    ts_str = msg["timestamp"]
                    if isinstance(ts_str, str) and ts_str.endswith("Z"):
                        ts_str = ts_str[:-1] + "+00:00"
                    last_timestamp = datetime.fromisoformat(ts_str)
                except (ValueError, TypeError):
                    pass

    # Post-loop decisions
    if has_clear_command and not has_assistant:
        return None
    if not session_id:
        return None
    if not title:
        title = first_user_text or "[Untitled]"

    # ... build and return Session
```

**Benefit:** Each file is read once and each line is parsed once. Eliminates 4-5 redundant passes.

### Tier 4: Metadata Cache with mtime Invalidation (Eliminates re-parsing unchanged files)

Cache parsed session metadata to a JSON file. On startup, only re-parse files whose mtime has changed.

**Changes:**
- `src/cache.py` (new file): Cache manager
  - Cache file location: `~/.claude/dashboard-cache.json`
  - Schema: `{ "version": 1, "sessions": { "<filepath>": { "mtime": <float>, "metadata": {...} } } }`
  - On startup: load cache, glob for JSONL files, compare mtimes, only parse changed/new files
  - After parsing: write updated cache
- `src/parser.py:discover_sessions()`: Accept optional cache dict, use cached metadata for unchanged files

```python
# src/cache.py
import json
from pathlib import Path

CACHE_PATH = Path.home() / ".claude" / "dashboard-cache.json"
CACHE_VERSION = 1

def load_cache() -> dict:
    try:
        data = json.loads(CACHE_PATH.read_text())
        if data.get("version") == CACHE_VERSION:
            return data.get("sessions", {})
    except Exception:
        pass
    return {}

def save_cache(sessions: dict):
    CACHE_PATH.write_text(json.dumps({
        "version": CACHE_VERSION,
        "sessions": sessions,
    }))

def needs_reparse(filepath: Path, cache: dict) -> bool:
    key = str(filepath)
    if key not in cache:
        return True
    return filepath.stat().st_mtime != cache[key]["mtime"]
```

**Benefit:** After first run, subsequent cold starts only parse new/modified session files. For a user with 200 sessions where 5 changed, this skips 97.5% of file parsing.

**Edge cases:**
- Cache corruption → catch exception, delete cache, full re-parse
- Schema migration → `CACHE_VERSION` bump triggers full re-parse
- Deleted session files → filter out cache entries for files that no longer exist on disk

## Technical Considerations

### Architecture impacts
- Tier 2 changes the `Session` dataclass interface (removes `full_message_history`, adds `filepath`). All consumers of `Session.full_message_history` must be updated — currently only `PreviewPane`.
- Tier 4 adds a new module (`src/cache.py`) and a new file on disk (`~/.claude/dashboard-cache.json`).

### Performance implications
- **Tier 1** gives instant perceived improvement with zero algorithmic change
- **Tiers 2+3** reduce per-file CPU work by ~4-5x
- **Tier 4** reduces I/O to only changed files — biggest win for repeat cold starts
- Combined: cold start should drop from ~10s to 1-3s depending on session count

### Risk assessment
- **Tier 1 (async):** Low risk. Textual workers are a supported pattern. Worst case: loading indicator shows briefly.
- **Tier 2 (lazy load):** Low risk. Clean interface change. Preview pane already handles None session.
- **Tier 3 (single-pass):** Medium risk. Parser logic rewrite — needs thorough testing against existing test suite.
- **Tier 4 (cache):** Medium risk. New state on disk. Cache invalidation bugs could show stale data. Mitigated by manual refresh (`r` key) always doing full re-parse.

## Acceptance Criteria

### Functional Requirements
- [ ] Dashboard UI shell renders in <1 second on cold start
- [ ] All sessions eventually appear (within 3s on cold start)
- [ ] Preview pane still works (loads history on demand)
- [ ] Refresh (`r` key) still picks up new/changed sessions
- [ ] Dismiss still works
- [ ] Filter still works
- [ ] All existing tests pass
- [ ] No regression in session data accuracy

### Non-Functional Requirements
- [ ] Cold start total time < 3 seconds (measured with `time uv run python main.py --days 0`)
- [ ] Warm start total time < 1.5 seconds
- [ ] Memory usage reduced (no more storing full history for all sessions)

## Implementation Phases

### Phase 1: Progressive Rendering + Lazy Loading (Tiers 1 & 2)

**Files:** `src/ui.py`, `src/parser.py`

1. Add `filepath` field to `Session` dataclass, remove `full_message_history`
2. Add `load_message_history(filepath)` function to `parser.py`
3. Update `PreviewPane` to call `load_message_history()` on toggle
4. Convert `refresh_sessions()` to use `@work(thread=True)`
5. Add loading state to `SessionListView`
6. Update existing tests

**Effort:** Small. Clean changes to existing files.

### Phase 2: Single-Pass Parser (Tier 3)

**Files:** `src/parser.py`, `tests/test_parser.py`

1. Rewrite `parse_jsonl()` to single-pass (as shown above)
2. Remove now-unused helper functions: `_is_clear_session`, `_determine_status`, `_extract_title`, `_extract_last_assistant_message` (their logic folds into the single pass)
3. Clean up dead code: `_build_session_cwd_map()` (never called in production)
4. Update/expand test suite to cover the rewritten parser

**Effort:** Medium. Parser rewrite needs careful testing.

### Phase 3: Metadata Cache (Tier 4)

**Files:** `src/cache.py` (new), `src/parser.py`, `tests/test_cache.py` (new)

1. Create `src/cache.py` with load/save/invalidation logic
2. Modify `discover_sessions()` to accept and use cache
3. Write cache after discovery completes
4. Manual refresh (`r` key) bypasses cache (full re-parse)
5. Add cache tests

**Effort:** Medium. New module, but self-contained.

## Cleanup Opportunities (While We're Here)

- Remove dead code: `_build_session_cwd_map()` — defined at `parser.py:28`, tested, but never called in production
- The dismissed IDs file (`session.log`) is re-read on every `filter_sessions()` call — could be cached per-refresh cycle

## Success Metrics

| Metric | Before | Target |
|---|---|---|
| Cold start (UI visible) | ~10s | <1s |
| Cold start (sessions loaded) | ~10s | <3s |
| Warm start (sessions loaded) | ~3-5s | <1.5s |
| Memory per session | all JSONL lines | metadata only (~200 bytes) |

## Sources & References

- Textual workers documentation: https://textual.textualize.io/guide/workers/
- `src/parser.py` — current parser with multi-pass approach
- `src/ui.py:313-327` — synchronous `on_mount` → `refresh_sessions` flow
- `src/ui.py:197-230` — `PreviewPane` only consumer of `full_message_history`
