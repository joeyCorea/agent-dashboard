---
title: "Fix MarkupError crash from unescaped Rich BBCode in session list rendering"
category: ui-bugs
date: 2026-03-30
severity: high
tags:
  - textual
  - rich-markup
  - rendering
  - crash
  - escape
  - bbcode
component: src/ui.py
symptoms:
  - "App crashes with MarkupError: closing tag '[/code]' does not match any open tag"
  - "Crash occurs when rendering SessionListItem or PreviewPane containing square brackets in session content"
  - "Intermittent — only triggers when session data contains bracket sequences that resemble Rich BBCode tags"
root_cause: "Textual render() interprets returned strings as Rich BBCode markup; unescaped session content containing square brackets (e.g. [/code], [bold]) is parsed as malformed tags, causing MarkupError"
---

# Fix MarkupError crash from unescaped Rich BBCode in session list rendering

## Problem Description

The claude-dashboard Textual TUI crashed with a `MarkupError` when rendering session list items whose content contained Rich markup-like sequences:

```
MarkupError: closing tag '[/code]' does not match any open tag
```

The crash was intermittent — it only occurred when a session's title, preview text, or message content happened to contain square bracket sequences that Rich interprets as BBCode tags (e.g., `[/code]`, `[bold]`, `[red]text[/red]`). This is common in Claude Code sessions, which frequently discuss code formatting, Rich/Textual APIs, or include code blocks.

The traceback path:
```
widget.py:4464 in _render → visualize(self, self.render(), markup=self._render_markup)
  → SessionListItem.render() returns f-string with unescaped dynamic content
    → Rich parses "[/code]" in session preview as a closing BBCode tag
      → MarkupError (no matching open tag)
```

## Root Cause Analysis

Textual widgets process the string returned by `render()` as **Rich markup** by default. The `_render` method in Textual's `Widget` base class calls `visualize(self, self.render(), markup=self._render_markup)`, which passes the string through Rich's markup parser.

Two render methods in `src/ui.py` interpolated dynamic, user-generated content directly into f-strings without escaping:

1. **`SessionListItem.render()`** — session title, project name, and `last_assistant_message` preview
2. **`PreviewPane.render()`** — project name, title, and per-message content lines

Any session data containing `[`, `]`, or sequences like `[/code]`, `[bold]`, `[@click=...]` would be interpreted as Rich markup control tags.

**This is analogous to SQL injection or XSS** — user content is being interpreted as control language because it was not escaped at the rendering boundary.

## Investigation Steps

1. Identified the crash from a Textual traceback pointing to `SessionListItem` in the `_render` → `visualize` path.
2. Read `src/ui.py:111-133` and found `render()` returns f-strings with dynamic content from `self.session.title`, `self.session.project_name`, and `self.session.last_assistant_message`.
3. Confirmed `PreviewPane.render()` at `src/ui.py:204-238` has the same pattern — message `first_line` content is interpolated without escaping.
4. Determined that `rich.markup.escape()` is the correct fix — it escapes square brackets so Rich treats them as literal text rather than markup tags.

## Solution

### Import

```python
from rich.markup import escape
```

### SessionListItem.render()

**Before (broken):**
```python
def render(self) -> str:
    # ...
    if self.grouped:
        main_line = f"  [{self.session.title:40}] {status:>11} {elapsed:>10}"
    else:
        main_line = f"  {self.session.project_name:15} [{self.session.title:40}] {status:>11} {elapsed:>10}"
    # ...
    return f"{main_line}\n    \"{preview}\""
```

**After (fixed):**
```python
def render(self) -> str:
    # ...
    title = escape(self.session.title)
    if self.grouped:
        main_line = f"  {title:40}  {status:>11} {elapsed:>10}"
    else:
        main_line = f"  {escape(self.session.project_name):15} {title:40}  {status:>11} {elapsed:>10}"
    # ...
    return f"{main_line}\n    \"{escape(preview)}\""
```

Note: The literal `[` `]` brackets wrapping the title were also removed — they were themselves susceptible to Rich interpretation when combined with title content.

### PreviewPane.render()

```python
lines = ["Preview: {} / {}\n".format(
    escape(self.session.project_name), escape(self.session.title))]
# ...
first_line = escape(first_line)
if role == "user":
    lines.append("You:    {}".format(first_line))
elif role == "assistant":
    lines.append("Claude: {}".format(first_line))
```

## Files Changed

- `src/ui.py` — Added `from rich.markup import escape`, applied `escape()` to all dynamic content in `SessionListItem.render()` and `PreviewPane.render()`

## Prevention Checklist

- **Before returning from any `render()` method**, verify every interpolated variable containing user/external data is wrapped in `escape()`.
- **Grep for `def render(self)` returning f-strings** — any f-string interpolation of dynamic content without `escape()` is a potential crash.
- **Never trust data from JSONL session files, filenames, or CLI output.** These regularly contain brackets (`[1/2]`, `[error]`, `[/code]`).
- **When adding new widgets that display session data**, import `escape` and apply it to all dynamic strings before they reach Rich's markup parser.
- **Prefer `Text()` objects with `no_wrap=True`** over markup strings when content is dynamic — `Text("literal string")` does not parse markup.

## Patterns to Watch For

- **`return f"[` in a render method** where bracket content comes from a variable — almost always a bug
- **String `.format()` calls inside render methods** with user data — same risk as f-strings
- **`Static(user_provided_string)` in `compose()` methods** — Static widgets also parse Rich markup
- **Escaping applied inconsistently** — some render methods escape, others in the same file do not

## Related Documentation

- [TUI lessons learned](../../../docs/solutions/claude-code-session-tui-lessons.md) — Widget lifecycle, structured content handling
- [Cold start optimization](../performance-issues/tui-cold-start-lazy-loading.md) — PreviewPane lazy loading (same render path)
- [Implementation checklist](../../../docs/solutions/implementation-checklist.md) — Phase 4 content rendering (should add escape step)
