---
title: Configurable Days Filter with Input Widget
category: ui-bugs
date: 2026-03-30
tags:
  - session-filtering
  - textual-input
  - focus-management
  - keybinding
component: src/ui.py
severity: low
symptoms: |
  Users could not adjust the 7-day default filter. All sessions older than
  7 days were permanently hidden with no way to see them.
---

# Configurable Days Filter with Input Widget

## Problem

The 7-day default filter (see `seven-day-default-filter-mixed-timezone.md`)
was hardcoded. Users needed a way to adjust the filter at runtime — showing
sessions from a custom number of days, or showing all sessions.

## Solution

### Architecture

Extracted three pure functions from the app class for testability:

- `parse_filter_input(value: str) -> Optional[int]` — validates user input
- `filter_subtitle(days_filter: int) -> str` — generates subtitle text
- `filter_sessions(sessions, days_filter)` — combines dismissal + date filtering

The `refresh_sessions()` method was refactored to delegate to `filter_sessions()`,
making the cutoff parameterizable via `self._days_filter`.

### Input mechanism

Uses Textual's `Input` widget, hidden by default via CSS (`display: none`).
The `f` keybinding shows it, pre-fills with the current value, and focuses it.
On Enter, the input is parsed, the widget is hidden, and focus returns to the
session list.

```python
def action_open_filter(self):
    filter_input = self.query_one("#filter-input", Input)
    filter_input.add_class("visible")
    filter_input.value = str(self._days_filter)
    filter_input.focus()

def on_input_submitted(self, event: Input.Submitted):
    if event.input.id == "filter-input":
        days = parse_filter_input(event.value)
        if days is not None:
            self._days_filter = days
        event.input.remove_class("visible")
        event.input.value = ""
        self.query_one("#session-list", SessionListView).focus()
        self.sub_title = filter_subtitle(self._days_filter)
        self.refresh_sessions()
```

### Zero means "all"

When `_days_filter == 0`, `filter_sessions()` skips the date cutoff entirely.
The subtitle shows "All sessions" instead of "Last 0d".

## Gotchas

### Focus management with Input and ListView

The `Input` widget has a built-in `enter` handler (`on_input_submitted`).
This works naturally — when Input is focused, Enter triggers submission.
When Input is hidden and ListView is focused, the app-level `enter` binding
(with `priority=True`) handles session opening.

No `priority=True` needed on the `f` binding because ListView does not
have a built-in `f` handler.

### Invalid input is silently ignored

`parse_filter_input()` returns `None` for non-numeric, negative, or empty
input. The app keeps the current filter value. This is intentional — the
user sees no change and can press `f` again to correct their input.

## Prevention

- **Keep filter logic in pure functions** (`parse_filter_input`,
  `filter_sessions`) for easy unit testing without Textual app lifecycle.
- **Always return focus to the session list** after closing the input widget.
- **Pre-fill the input** with the current value so users can see and adjust
  the active filter.

## Related Files

- `src/ui.py` — `parse_filter_input()`, `filter_subtitle()`, `filter_sessions()`,
  `action_open_filter()`, `on_input_submitted()`
- `tests/test_ui_bindings.py` — `TestFilterBinding`, `TestConfigurableDaysFilter`
- `docs/solutions/seven-day-default-filter-mixed-timezone.md` — prerequisite feature
- `docs/solutions/enter-key-open-session.md` — Input widget enter handler context
