---
title: Configurable Days Filter Input
type: feat
status: active
date: 2026-03-30
---

# Configurable Days Filter Input

Allow the user to enter a custom number of days for the session age filter, replacing or adjusting the 7-day default.

## Acceptance Criteria

- [ ] New keybinding `f` opens an input prompt for number of days
- [ ] Input accepts positive integers; invalid input is ignored (filter unchanged)
- [ ] Entering `0` or empty string shows all sessions (no date filter)
- [ ] After input, session list refreshes immediately with new cutoff
- [ ] Current filter value is shown in the header/footer (e.g., "Last 7d" or "All")
- [ ] Filter value persists during the session (survives `r` refresh)
- [ ] Default value is 7 days (from plan 002)

## Context

### Depends on

Plan 002 (7-day default filter) must be implemented first — this feature extends it by making the `DEFAULT_DAYS_FILTER` constant user-adjustable at runtime.

### Input mechanism

Textual provides `self.push_screen()` for modal input, but simpler: use `app.query_one(Input)` with a togglable Input widget, or use Textual's built-in `Screen` approach.

**Recommended: Textual Input widget.** Add a hidden `Input` widget that appears on `f` keypress, captures a number, and hides on Enter/Escape.

### Key changes

1. **`PendingSessionsApp`**: Add `_days_filter: int = 7` instance attribute
2. **New widget**: `FilterInput` — an `Input` widget that appears on `f`, accepts digits, hides on Enter
3. **`refresh_sessions()`**: Use `self._days_filter` instead of `DEFAULT_DAYS_FILTER`. When `_days_filter == 0`, skip date filtering
4. **Footer/subtitle**: Show current filter in app subtitle (e.g., `self.sub_title = f"Last {self._days_filter}d"`)
5. **Binding**: Add `Binding("f", "open_filter", "Filter", show=True)`

### Risks

- **Focus management**: When Input widget appears, it must capture focus. When it closes, focus must return to the session list. Textual's focus system needs careful handling.
- **Input validation**: Must handle non-numeric input, negative numbers, very large numbers gracefully.
- **Key conflict**: The `f` key must not conflict with the Input widget's own key handling. Use `priority=True` or toggle the binding when Input is active.

### Testing

- Test that entering `3` filters to last 3 days
- Test that entering `0` shows all sessions
- Test that entering empty string keeps current filter
- Test that non-numeric input is rejected
- Test that filter persists across `refresh_sessions()` calls

## MVP

### src/ui.py — FilterInput widget

```python
from textual.widgets import Input

class FilterInput(Input):
    DEFAULT_CSS = """
    FilterInput {
        dock: top;
        display: none;
        height: 3;
        border: solid $accent;
    }
    FilterInput.visible {
        display: block;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(placeholder="Days to filter (0 = all):", **kwargs)
```

### src/ui.py — PendingSessionsApp changes

```python
def action_open_filter(self):
    filter_input = self.query_one("#filter-input", FilterInput)
    filter_input.add_class("visible")
    filter_input.value = str(self._days_filter)
    filter_input.focus()

def on_input_submitted(self, event: Input.Submitted):
    if event.input.id == "filter-input":
        try:
            days = int(event.value)
            if days >= 0:
                self._days_filter = days
        except ValueError:
            pass  # Keep current filter
        event.input.remove_class("visible")
        event.input.value = ""
        self.query_one("#session-list", SessionListView).focus()
        self.sub_title = f"Last {self._days_filter}d" if self._days_filter > 0 else "All sessions"
        self.refresh_sessions()
```

## Sources

- Depends on: `docs/plans/2026-03-30-002-feat-default-seven-day-session-filter-plan.md`
- Textual Input widget docs for focus management
- Institutional learning: `docs/solutions/claude-code-session-tui-lessons.md` — widget initialization patterns
- Insert point: `src/ui.py:128-140` (BINDINGS), `src/ui.py:190-203` (refresh_sessions)
