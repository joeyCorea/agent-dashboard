---
title: Toggle Flat List vs Grouped by Project
type: feat
status: active
date: 2026-03-30
---

# Toggle Flat List vs Grouped by Project

Allow the user to toggle between a flat chronological list (current default) and a view grouped by project name.

## Acceptance Criteria

- [ ] New keybinding `g` toggles between flat and grouped view
- [ ] Grouped view shows sessions organized under project name headers
- [ ] Project headers are visually distinct (not selectable as sessions)
- [ ] Within each group, sessions remain sorted by recency (most recent first)
- [ ] Groups themselves are sorted by most recent session in each group
- [ ] Navigation (j/k, open, dismiss, preview) works correctly in grouped view
- [ ] Footer shows current view mode
- [ ] View preference persists during the session (survives refresh)
- [ ] Empty state still displays correctly in both modes

## Context

### Architecture approach

The grouping is a **display concern** — the underlying data (`active_sessions` list) stays the same. The toggle controls how `SessionListView.update_sessions()` renders the list.

Two approaches:

**Option A — Separator ListItems (simpler):** Insert non-interactive `ListItem(Static("project-name"))` as group headers between session items. `get_selected_session()` must skip these. This is the recommended approach for Textual's ListView.

**Option B — Nested containers:** Replace ListView with a Vertical containing per-project ListViews. More complex, breaks existing navigation.

**Recommendation: Option A.**

### Key changes

1. **`PendingSessionsApp`**: Add `_grouped: bool = False` instance attribute, toggled by `g` keybinding
2. **`SessionListView.update_sessions()`**: Accept a `grouped: bool` parameter. When True, sort sessions into `defaultdict(list)` by `project_name`, insert `Static` header items between groups
3. **`SessionListView.get_selected_session()`**: Skip non-`SessionListItem` entries when resolving index to session
4. **New CSS**: Style group headers distinctly (e.g., bold, different color)
5. **Binding**: Add `Binding("g", "toggle_group", "Group", show=True)`

### Risks

- **Index tracking**: ListView's `self.index` is a flat integer. Inserting header items shifts the mapping between index and session. `get_selected_session()` must be updated to only count `SessionListItem` children.
- **Empty groups**: After dismissal + date filtering, a project might have 0 sessions — skip the header entirely.
- **Preview pane**: Must still work — it reads from `get_selected_session()`, so fixing that method covers this.

### Testing

- Test that grouped view shows correct headers in correct order
- Test that `get_selected_session()` skips header items
- Test that toggling preserves selected session (or resets to top)
- Test grouping with 1 project, multiple projects, and 0 sessions

## MVP

### src/ui.py — SessionListView.update_sessions

```python
from collections import defaultdict

def update_sessions(self, sessions: list[Session], grouped: bool = False):
    self.sessions = sessions
    self.clear()

    if not sessions:
        self.append(ListItem(Static("All caught up.")))
        return

    if not grouped:
        for session in sessions:
            self.append(SessionListItem(session))
        return

    # Group by project
    groups = defaultdict(list)
    for s in sessions:
        groups[s.project_name].append(s)

    # Sort groups by most recent session
    sorted_groups = sorted(groups.items(), key=lambda g: g[1][0].last_message_timestamp, reverse=True)

    for project_name, project_sessions in sorted_groups:
        # Header item (not a SessionListItem — skipped by get_selected_session)
        header = ListItem(Static(f"  --- {project_name} ---"))
        header.add_class("group-header")
        self.append(header)
        for session in project_sessions:
            self.append(SessionListItem(session))
```

### src/ui.py — get_selected_session fix

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

## Sources

- Textual ListView docs: headers as non-interactive ListItems is a known pattern
- Institutional learning: `docs/solutions/claude-code-session-tui-lessons.md` — widget lifecycle, key binding priority
- Insert point: `src/ui.py:49-66` (SessionListView), `src/ui.py:128-140` (BINDINGS)
