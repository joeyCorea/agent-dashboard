---
title: Toggle Flat vs Grouped-by-Project View
category: ui-bugs
date: 2026-03-30
tags:
  - grouped-view
  - listview
  - index-tracking
  - keybinding
component: src/ui.py
severity: low
symptoms: |
  Users could not organize sessions by project. All sessions appeared in a
  single flat list sorted by recency, making it hard to see which projects
  had pending sessions.
---

# Toggle Flat vs Grouped-by-Project View

## Problem

The TUI displayed all sessions in a flat chronological list. Users with
sessions across many projects wanted to see them grouped by project name.

## Solution

### Architecture: Separator ListItems (Option A)

Used non-interactive `ListItem(Static(...))` elements as group headers
inserted between session items in the ListView. This is the simplest
approach for Textual's ListView — no nested containers, no custom widgets.

### Pure function for grouping logic

`group_sessions()` returns tagged tuples for testability:

```python
def group_sessions(sessions: list[Session]) -> list[tuple[str, Any]]:
    # Returns: [("header", "project-a"), ("session", Session), ...]
    groups = defaultdict(list)
    for s in sessions:
        groups[s.project_name].append(s)
    sorted_groups = sorted(
        groups.items(),
        key=lambda g: g[1][0].last_message_timestamp,
        reverse=True,
    )
    result = []
    for project_name, project_sessions in sorted_groups:
        result.append(("header", project_name))
        for s in project_sessions:
            result.append(("session", s))
    return result
```

### get_selected_session() uses isinstance

The critical change: switched from flat index into `self.sessions` to
walking `self.children` with `isinstance(child, SessionListItem)`. This
handles both flat and grouped views — header ListItems are not
SessionListItems and return None.

```python
def get_selected_session(self) -> Session | None:
    if self.index is None:
        return None
    children = list(self.children)
    if 0 <= self.index < len(children):
        child = children[self.index]
        if isinstance(child, SessionListItem):
            return child.session
    return None
```

## Gotchas

### Header items shift ListView index

ListView's `self.index` is a flat integer over all children. Inserting
header ListItems means index N no longer maps to session N. Any code that
assumes `index == session_position` breaks in grouped mode.

Fix: always resolve via `isinstance` check on the child at the current
index, never via positional lookup in the sessions list.

### Headers are navigable but not actionable

Users can navigate to header items with j/k. When a header is selected,
`get_selected_session()` returns None, and all actions (open, dismiss,
preview) gracefully no-op. This is acceptable UX — the header serves as
a visual separator.

## Prevention

- **Always use `isinstance` checks** when resolving ListView selection to
  a domain object, especially when the list contains mixed item types.
- **Extract grouping as a pure function** so the sorting/ordering logic
  is testable without Textual app lifecycle.

## Related Files

- `src/ui.py` — `group_sessions()`, `update_sessions()`, `get_selected_session()`,
  `action_toggle_group()`
- `tests/test_ui_bindings.py` — `TestGroupBinding`, `TestGroupSessions`
