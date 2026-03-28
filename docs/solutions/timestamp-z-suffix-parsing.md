# Bug Fix: Timestamps with 'Z' Suffix Parsed Incorrectly in Python 3.10

## Problem

All sessions showed "just now" for their elapsed time, regardless of actual age.

## Root Cause

Claude Code session JSONL files store timestamps in ISO 8601 format with a `Z`
suffix to indicate UTC:

```
"timestamp": "2026-03-28T07:20:53.869Z"
```

Python 3.10's `datetime.fromisoformat()` does **not** support the `Z` suffix as
a UTC indicator. It only accepts the `+00:00` form. When `fromisoformat()` was
called with a `Z`-suffixed string it raised `ValueError`, which was caught and
silently ignored. The parser then fell back to `datetime.now()`, making every
session appear to have just been active — and `format_elapsed_time()` correctly
returned `"just now"` for that current timestamp.

**Python 3.11+** added support for `Z` in `fromisoformat()`, but this project
targets Python 3.10.

## Fix

In `src/parser.py`, inside `parse_jsonl()`, normalise the timestamp string
before calling `fromisoformat()`:

```python
ts_str = msg["timestamp"]
# Python < 3.11 doesn't support 'Z' as UTC in fromisoformat;
# replace it with the equivalent '+00:00' offset.
if isinstance(ts_str, str) and ts_str.endswith("Z"):
    ts_str = ts_str[:-1] + "+00:00"
last_timestamp = datetime.fromisoformat(ts_str)
```

This is a one-line normalisation that is backward-compatible and requires no
additional dependencies.

## Why format_elapsed_time() Appeared to Work

The unit tests for `format_elapsed_time()` use naive `datetime.now()` objects
subtracted by `timedelta`. Those tests always passed because the function logic
is correct. The formatter was never the bug — the issue was upstream in how
timestamps were extracted from real JSONL files.

## Tests Added

`tests/test_parser.py` — `TestTimestampParsing` class:

- `test_parse_jsonl_with_z_suffix_two_hours_ago` — parse a JSONL file whose
  timestamps use `Z` suffix and verify elapsed time shows `"2h ago"`, not
  `"just now"`.
- `test_parse_jsonl_with_z_suffix_one_day_ago_not_just_now` — same scenario
  for a day-old session.

Both tests use `monkeypatch` to redirect `Path.home()` to a temp directory so
they are hermetic and don't depend on real session data.

## Gotchas

- `datetime.fromisoformat()` with `+00:00` returns a timezone-aware datetime.
  `format_elapsed_time()` already handles timezone-aware timestamps via
  `datetime.now(timestamp.tzinfo)`, so no further changes are needed there.
- The `Z` suffix is the only non-standard case observed in real Claude Code
  session files. Millisecond precision (`2026-03-28T07:20:53.869Z`) is also
  present; replacing `Z` with `+00:00` handles both forms.

## Future Improvements

- [ ] Use file `mtime` as secondary fallback when no timestamp field is present in JSONL (currently falls back to `datetime.now()`, making old sessions without timestamps appear current)
- [ ] Log a warning when the fallback is used, so it's visible in debugging
- [ ] Consider timezone-aware handling throughout — `fromisoformat()` with `+00:00` returns a tz-aware datetime; `datetime.now()` is naive. Mixed-awareness comparisons will raise `TypeError`.

## Related Files

- `src/parser.py` — fix in `parse_jsonl()` (search for `endswith("Z")`)
- `tests/test_parser.py` — `TestTimestampParsing` class
