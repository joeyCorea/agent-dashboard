## Repository Research Summary -- claude-dashboard

### Technology & Infrastructure

- **Language:** Python 3.10+ (declared in `pyproject.toml` `requires-python`)
- **Framework:** Textual >= 0.40.0 (terminal UI framework built on Rich)
- **Build system:** Hatchling (`hatchling.build`)
- **Package manager:** uv (evidenced by `uv.lock` at root)
- **Test framework:** pytest >= 7.0 (optional dependency under `[project.optional-dependencies] test`)
- **Deployment model:** Single-user CLI tool, installed as `agent-dashboard` entry point (`main:main`)
- **API surface:** None -- this is a local TUI reading files from disk
- **Data stores:** Filesystem only (`~/.claude/projects/**/*.jsonl` for sessions, `~/.claude/session.log` for dismissals, `~/.claude/sessions/*.json` for CWD mapping)
- **Monorepo:** No -- single-package project

### Architecture & Structure

```
agent-dashboard/
  pyproject.toml        # project metadata, dependencies, pytest config
  main.py               # entry point: runs TUI, then launches `claude --resume` on exit
  src/
    __init__.py
    parser.py           # Session dataclass, discover_sessions(), parse_jsonl(), helpers
    ui.py               # Textual App, ListView, PreviewPane, all key bindings
    dismiss.py          # read_dismissed_ids(), dismiss_session() -- session.log I/O
  tests/
    test_parser.py      # parser unit/integration tests (timestamp, /clear, subagent, CWD)
    test_ui_bindings.py # binding configuration assertions (no Textual app pilot)
    test_dismiss.py     # dismissal log read/write + end-to-end filtering
  spec.md               # full product specification
```

**Data flow on refresh (the critical path for the 7-day filter feature):**

1. `PendingSessionsApp.refresh_sessions()` in `src/ui.py` (line 190)
2. Calls `discover_sessions()` from `src/parser.py` -- scans `~/.claude/projects/**/*.jsonl`
3. Calls `read_dismissed_ids()` from `src/dismiss.py` -- reads `~/.claude/session.log`
4. Filters: list comprehension removes sessions whose `session_id` is in `dismissed_ids`
5. Passes filtered list to `SessionListView.update_sessions()`

**Key design decisions:**
- All filtering happens in `refresh_sessions()` -- it is the single choke point between raw data and display
- `discover_sessions()` returns ALL sessions sorted by `last_message_timestamp` descending; it does not filter
- Filtering is purely subtractive (dismissed IDs removed via set membership)

---

### Session Dataclass (`src/parser.py` lines 14-26)

```python
@dataclass
class Session:
    session_id: str
    project_name: str
    title: str
    last_message_timestamp: datetime      # <-- the field to filter on
    last_assistant_message: str
    full_message_history: list[dict]
    status: str = "ready"                 # "in progress" or "ready"
    project_dir: Optional[str] = None     # original cwd for --resume
```

`last_message_timestamp` is a `datetime` object. It is timezone-aware when parsed from a `Z`-suffix ISO string (converted to `+00:00`). Falls back to naive `datetime.now()` when no timestamp is found.

### discover_sessions() (`src/parser.py` lines 61-95)

- Globs `~/.claude/projects/**/*.jsonl`
- Filters to depth-2 paths only (skips subagent logs in nested dirs)
- Calls `parse_jsonl()` per file, which also filters out `/clear` artifacts
- Populates `project_dir` from the CWD map
- Sorts by `last_message_timestamp` descending
- Returns the full list with no time-based filtering

### refresh_sessions() (`src/ui.py` lines 190-203)

```python
def refresh_sessions(self):
    all_sessions = discover_sessions()
    dismissed_ids = read_dismissed_ids()
    active_sessions = [
        s for s in all_sessions if s.session_id not in dismissed_ids
    ]
    list_view = self.query_one("#session-list", SessionListView)
    list_view.update_sessions(active_sessions)
```

This is the insertion point for the 7-day filter. The list comprehension already filters by dismissal; a datetime comparison can be added here.

---

### Testing Patterns (`tests/`)

**Framework:** pytest, run as `uv run pytest` or `pytest` (pythonpath configured in `pyproject.toml`)

**Patterns observed:**

1. **Class-based grouping** -- tests are organized into classes by feature/concern (e.g., `TestElapsedTimeFormatting`, `TestClearSessionFiltering`, `TestSubagentFileFiltering`, `TestBuildSessionCwdMap`)
2. **`tmp_path` + `monkeypatch`** -- standard pytest fixtures used everywhere. `Path.home()` is monkeypatched to `tmp_path` so tests write to isolated temp dirs, not the real `~/.claude/`
3. **Shared helpers** -- `_write_real_session()` and `_write_clear_session()` create realistic JSONL fixture files. Defined at module level and reused across test classes. Similar helpers duplicated across test files (e.g., `_write_real_session` appears in both `test_parser.py` and `test_dismiss.py`)
4. **Assertion messages** -- every `assert` includes a descriptive failure message explaining WHY the assertion matters (not just WHAT failed). These messages describe the bug that would be present if the assertion fails
5. **No mocking of internal functions** -- tests call real code paths (`discover_sessions()`, `parse_jsonl()`, `read_dismissed_ids()`) against fixture data on disk. The only mock is `Path.home()`
6. **Timestamp constant** -- `_TS = "2026-03-28T07:20:53.867Z"` used as a fixed timestamp in fixture helpers
7. **No Textual app pilot tests** -- UI tests only check binding configuration (class attributes), not runtime behavior

**Test for the 7-day filter should follow these patterns:**
- New class like `TestSevenDayDefaultFilter` in `test_parser.py` or a new file
- Use `tmp_path` + `monkeypatch` for isolation
- Use `_write_real_session()` helper (or a variant that accepts a custom timestamp)
- Test that sessions older than 7 days are excluded from the filtered list
- Test that sessions within 7 days still appear
- Test boundary (exactly 7 days ago)
- Include descriptive assertion failure messages

---

### Implementation Guidance for the 7-Day Default Filter

**Where to add the filter:** `refresh_sessions()` in `src/ui.py` (line 190). Add a datetime cutoff after the dismissed-ID filter:

```python
from datetime import datetime, timedelta, timezone

cutoff = datetime.now(timezone.utc) - timedelta(days=7)
active_sessions = [
    s for s in all_sessions
    if s.session_id not in dismissed_ids
    and s.last_message_timestamp >= cutoff
]
```

**Timezone consideration:** `last_message_timestamp` is timezone-aware (UTC) when parsed from real session files, but falls back to naive `datetime.now()` when no timestamp exists. The comparison must handle both. Options:
- Normalize all timestamps to UTC-aware in `parse_jsonl()` (cleaner)
- Use a comparison helper that handles naive vs aware

**Existing helpers already used in tests:**
- `_write_real_session()` uses a fixed timestamp `_TS = "2026-03-28T07:20:53.867Z"`. For the 7-day filter tests, a variant accepting a custom timestamp string is needed so tests can create sessions at specific ages.

**Key files to modify:**
- `/c/Users/JosephCorea/tools/claude-dashboard/src/ui.py` -- add time filter in `refresh_sessions()`
- `/c/Users/JosephCorea/tools/claude-dashboard/tests/test_parser.py` (or new test file) -- add filter tests
