---
title: 7-Day Default Session Filter with Mixed Timezone Handling
category: logic-errors
date: 2026-03-30
tags:
  - session-filtering
  - datetime-handling
  - timezone-aware
  - naive-datetime
  - refresh-sessions
component: src/ui.py
severity: medium
symptoms: |
  All historical sessions appear in the TUI regardless of age, making it
  difficult to locate recent pending sessions among stale conversations.
---

# 7-Day Default Session Filter with Mixed Timezone Handling

## Problem

The TUI displayed every discovered session with no time-based filtering.
Users had to scroll through weeks of old conversations to find recent ones.

Adding a simple date cutoff seemed straightforward, but the parser produces
**mixed timezone states**: successfully parsed timestamps are UTC-aware
(from the `Z` suffix conversion), while unparseable timestamps fall back to
naive `datetime.now()`. Comparing a tz-aware cutoff against a naive
timestamp raises `TypeError` in Python 3.

## Root Cause

`parse_jsonl()` in `src/parser.py` catches `ValueError`/`TypeError` on
timestamp parsing and silently falls back to `datetime.now()` (naive). The
`Z` suffix normalization (see `timestamp-z-suffix-parsing.md`) makes real
timestamps UTC-aware. Any date comparison in the UI layer must handle both
types without crashing.

## Solution

### 1. `is_within_cutoff()` — Timezone-safe comparison

Added to `src/ui.py` as a module-level function:

```python
from datetime import datetime, timedelta, timezone

DEFAULT_DAYS_FILTER = 7

def is_within_cutoff(session: Session, cutoff: datetime) -> bool:
    ts = session.last_message_timestamp
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts >= cutoff
```

Key decisions:
- **Naive timestamps → assume UTC**: Unparseable timestamps that fell back
  to `datetime.now()` are treated as current. Including false positives is
  better than silently hiding sessions.
- **`>=` (inclusive)**: Sessions exactly at the 7-day boundary are included.
- **Function is exported**: Allows tests to validate filtering logic
  independently of the full TUI lifecycle.

### 2. Layer 3 in `refresh_sessions()`

```python
def refresh_sessions(self):
    all_sessions = discover_sessions()

    # Layer 2: Filter out dismissed sessions
    dismissed_ids = read_dismissed_ids()
    active_sessions = [
        s for s in all_sessions if s.session_id not in dismissed_ids
    ]

    # Layer 3: Filter by date cutoff (default: last 7 days)
    cutoff = datetime.now(timezone.utc) - timedelta(days=DEFAULT_DAYS_FILTER)
    active_sessions = [
        s for s in active_sessions if is_within_cutoff(s, cutoff)
    ]

    list_view = self.query_one("#session-list", SessionListView)
    list_view.update_sessions(active_sessions)
```

## Three-Layer Filtering Architecture

| Layer | Where | Mechanism | What it catches |
|-------|-------|-----------|-----------------|
| 1 — Content check | `parse_jsonl()` | `_is_clear_session()` returns `None` | `/clear` artifacts |
| 2 — ID dismissal | `refresh_sessions()` | Session ID in `session.log` | User-dismissed sessions |
| 3 — Date cutoff | `refresh_sessions()` | `is_within_cutoff(s, cutoff)` | Sessions older than 7 days |

Layers run in order. Layer 1 fires during parsing; layers 2 and 3 fire
during UI refresh. Each is independently testable.

## Gotchas

### TypeError on mixed timezone comparison

```python
datetime.now() >= datetime.now(timezone.utc)
# TypeError: can't compare offset-naive and offset-aware datetimes
```

The error message says "between instances of 'datetime.datetime'" for both
sides, which is misleading. Always check `.tzinfo` before comparing.

### Boundary test timing races

Tests that create a timestamp at "exactly 7 days ago" and then compute a
cutoff a few milliseconds later will fail intermittently. `strftime`
truncates sub-second precision, widening the race window. Fix: add 1 second
of slack in boundary tests:

```python
# Instead of: timedelta(days=7)
seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7, seconds=-1)
```

### Silent fallback hides data quality issues

The parser's fallback to `datetime.now()` on unparseable timestamps means
sessions with bad timestamps appear "current" and always pass the filter.
This is a trade-off: false positives (showing too many sessions) are
preferable to false negatives (hiding valid sessions).

## Prevention

- **Always use `datetime.now(timezone.utc)` for cutoff calculations** in
  the UI layer — never naive `datetime.now()`.
- **Guard `.tzinfo` before any datetime comparison** where one side could
  be naive (the parser fallback path).
- **Use `>=` for inclusive boundary** comparisons to avoid off-by-one
  exclusions at the cutoff edge.

## Tests Added

`tests/test_parser.py` — `TestSevenDayFilter` class (5 tests):

- `test_session_within_7_days_is_included` — 6-day-old session passes
- `test_session_older_than_7_days_is_excluded` — 8-day-old session filtered
- `test_session_exactly_at_cutoff_is_included` — boundary with 1s slack
- `test_naive_timestamp_fallback_is_included` — handles mixed tz without TypeError
- `test_mixed_old_and_new_sessions_filtered_correctly` — integration test

Helper `_write_real_session_at()` creates sessions with custom timestamps
for dynamic time-based testing.

## Related Files

- `src/ui.py` — `is_within_cutoff()`, `refresh_sessions()`, `DEFAULT_DAYS_FILTER`
- `src/parser.py` — timestamp fallback at line 168-169
- `tests/test_parser.py` — `TestSevenDayFilter`, `_write_real_session_at()`
- `docs/solutions/timestamp-z-suffix-parsing.md` — upstream timezone fix
- `docs/solutions/clear-session-and-subagent-filtering.md` — layers 1 and 2
