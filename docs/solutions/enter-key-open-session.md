# Enter Key: Open Session (not Toggle Preview)

## Issue

The `Enter` key was bound to `toggle_preview` (show/hide the inline preview pane). The user wanted `Enter` to open the session in Claude Code — the same action as `o`.

## Why the first fix didn't work

Changing the binding action (`toggle_preview` → `open_session`) in `BINDINGS` was not enough. `Enter` still did nothing.

**Root cause:** `ListView` has a built-in `enter` binding at the widget level. In Textual, widget-level bindings are evaluated before app-level bindings. Because `SessionListView` extends `ListView`, it inherited that handler — and it consumed the keypress before the app binding ever fired.

This is a silent failure: no error, no warning. The app binding is simply ignored.

## Fix

Add `priority=True` to the app-level binding. This tells Textual to check the app binding first, before any focused widget gets a chance to consume the key.

```python
# Before — binding is silently swallowed by ListView's built-in enter handler
Binding("enter", "toggle_preview", "Preview", show=True),

# After — priority=True overrides the widget-level handler
Binding("enter", "open_session", "Open", show=False, priority=True),
Binding("space", "toggle_preview", "Preview", show=True),
```

## Lesson

When an app-level key binding appears to do nothing (no error, just silence), the cause is almost always a widget consuming it first. Check whether the focused widget has a built-in handler for that key. The fix is `priority=True` on the binding.

Common Textual widgets with built-in `enter` handling: `ListView`, `DataTable`, `Tree`, `Input`.
