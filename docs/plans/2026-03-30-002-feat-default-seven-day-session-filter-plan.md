---
title: Default to 7-Day Session Filter
type: feat
status: active
date: 2026-03-30
---

# Default to 7-Day Session Filter

Only show conversations whose last message was sent within the last 7 days by default, reducing noise from stale sessions.

## Acceptance Criteria

- [ ] `refresh_sessions()` filters sessions to only those with `last_message_timestamp` within 7 days of now
- [ ] Filter uses timezone-aware UTC comparison (`datetime.now(timezone.utc) - timedelta(days=7)`)
- [ ] Sessions with fallback naive timestamps are handled gracefully (treat as current to avoid silent exclusion)
- [ ] Empty state ("All caught up.") displays correctly when all sessions are older than 7 days
- [ ] Existing dismissal filtering still works as before (layer 2), date filter is layer 3

## Context

### Insert point

`src/ui.py:refresh_sessions()` (lines 190-203). Add the date filter after the dismissed-ID filter:

```python
from datetime import datetime, timedelta, timezone

def refresh_sessions(self):
    all_sessions = discover_sessions()
    dismissed_ids = read_dismissed_ids()
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    active_sessions = [
        s for s in all_sessions
        if s.session_id not in dismissed_ids
        and s.last_message_timestamp >= cutoff
    ]
    list_view = self.query_one("#session-list", SessionListView)
    list_view.update_sessions(active_sessions)
```

### Timezone gotcha

`Session.last_message_timestamp` is timezone-aware (UTC) when parsed from JSONL, but falls back to naive `datetime.now()` on parse failure (see `docs/solutions/timestamp-z-suffix-parsing.md`). The cutoff comparison will raise `TypeError` if one side is naive and the other aware. Handle by making the cutoff aware and wrapping fallback timestamps as aware too, or by catching the comparison error and defaulting to include the session.

### Testing

- Create sessions with timestamps at now-6d (included), now-8d (excluded), and now (included)
- Use dynamic timestamps relative to `datetime.now(timezone.utc)` — don't hardcode
- Follow existing class-based pattern: `TestSevenDayFilter`
- Reuse `_write_real_session()` helper with custom timestamps

## MVP

### src/ui.py

```python
from datetime import datetime, timedelta, timezone

DEFAULT_DAYS_FILTER = 7

def refresh_sessions(self):
    all_sessions = discover_sessions()
    dismissed_ids = read_dismissed_ids()
    cutoff = datetime.now(timezone.utc) - timedelta(days=DEFAULT_DAYS_FILTER)
    active_sessions = [
        s for s in all_sessions
        if s.session_id not in dismissed_ids
        and _is_within_cutoff(s, cutoff)
    ]
    list_view = self.query_one("#session-list", SessionListView)
    list_view.update_sessions(active_sessions)

def _is_within_cutoff(session, cutoff):
    ts = session.last_message_timestamp
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts >= cutoff
```

## Sources

- Institutional learning: `docs/solutions/timestamp-z-suffix-parsing.md` — timezone-aware comparison is mandatory
- Institutional learning: `docs/solutions/clear-session-and-subagent-filtering.md` — filter architecture (layer 3)
- Insert point: `src/ui.py:190-203`
