# Claude Code Session TUI Implementation - Lessons Learned

## Project Overview
Implemented a keyboard-driven TUI application to list and manage Claude Code sessions awaiting user response.

**Key Tech Stack:**
- Python 3.10+
- Textual (TUI framework)
- Rich (rendering, included with Textual)
- uv (package manager)

---

## Critical Discoveries

### 1. Claude Code's Message Format is Structured, Not Plain Text

**Problem:** Initial JSONL parsing assumed messages were plain strings:
```python
content = msg.get("message", {}).get("content", "")
first_line = content.split("\n")[0]  # ❌ FAILS if content is a list
```

**Discovery:** Claude Code supports **structured message content** with multiple types:
```json
{
  "message": {
    "role": "assistant",
    "content": [
      {"type": "text", "text": "Hello..."},
      {"type": "thinking", "thinking": "Let me analyze..."},
      {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "..."}}
    ]
  }
}
```

**Solution:** Created a helper function to extract text from both formats:
```python
def _extract_text_from_content(content):
    """Extract plain text from message content.

    Content can be either a string or a list of structured objects.
    """
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(block["text"])
        return " ".join(texts).strip()

    return ""
```

**Lesson:** Always check actual data format in production files. Don't assume based on spec.

---

### 2. Textual App.run() is Asynchronous — Terminal Restore Timing is Critical

**Problem:** Launching a subprocess immediately after `self.exit()` caused the subprocess to inherit a corrupted terminal state (alternate screen buffer, raw mode still active from Textual).

```python
def action_open_session(self):
    self.exit()
    subprocess.run(["claude", "--resume", session.session_id])  # ❌ Terminal still in TUI mode
```

**Result:** Claude Code would open but be unresponsive — overlaid with TUI artifacts.

**Discovery:** `self.exit()` is **asynchronous** and schedules shutdown. Control returns before the terminal is actually restored.

**Solution:** Return data from the app and launch subprocess in `main.py` AFTER the app fully exits:

```python
# main.py
def main():
    app = PendingSessionsApp()
    session_id = app.run()  # Blocks until fully shut down

    if session_id:
        subprocess.run(["claude", "--resume", session_id])  # ✅ Terminal fully restored
```

```python
# src/ui.py
def action_open_session(self):
    session = self.get_selected_session()
    if session:
        self.exit(result=session.session_id)  # Pass data, don't launch subprocess here
```

**Lesson:** Textual's `app.run()` method blocks until complete shutdown. Use it as a sync point. Don't call subprocess inside async handlers.

---

### 3. Textual Widget Initialization Requires Careful Timing

**Problem:** Called `append()` inside `__init__()` before the widget was fully mounted:

```python
class SessionListView(ListView):
    def __init__(self, sessions):
        super().__init__()
        self.sessions = sessions
        self.update_sessions(sessions)  # ❌ Calls append() before mounted

    def update_sessions(self, sessions):
        self.clear()
        self.append(ListItem(...))  # MountError: Can't mount before widget is attached
```

**Discovery:** Widgets can't mount children until they're attached to the DOM.

**Solution:** Defer population until after mount via `on_mount()` or provide no-op initial state:

```python
class SessionListView(ListView):
    def __init__(self, sessions=None, **kwargs):
        super().__init__(**kwargs)
        self.sessions = sessions or []
        # Don't call update_sessions here - wait for mount

# Then refresh later in the app's on_mount():
def on_mount(self):
    self.refresh_sessions()
```

**Lesson:** Respect Textual's lifecycle. Don't populate views during `__init__()`. Use `on_mount()` or deferred updates instead.

---

### 4. Custom Widget Init Must Accept **kwargs for ID and Other Attributes

**Problem:** Custom widgets that override `__init__()` broke when passed `id=` from parent:

```python
class PreviewPane(Static):
    def __init__(self, session=None):
        super().__init__()  # ❌ Doesn't accept id kwarg
        self.session = session

# In compose:
yield PreviewPane(id="preview-pane")  # TypeError: unexpected keyword argument 'id'
```

**Solution:** Accept and pass through all kwargs:

```python
class PreviewPane(Static):
    def __init__(self, session=None, **kwargs):
        super().__init__(**kwargs)  # ✅ Passes id and other attributes to parent
        self.session = session
```

**Lesson:** Always use `**kwargs` in custom Textual widget `__init__()` methods.

---

### 5. Directory Structure Matters for Package Building

**Problem:** `uv run main.py` initially failed with vague hatchling error about "Unable to determine which files to ship inside the wheel."

```toml
# ❌ Original pyproject.toml - missing build config
[project]
name = "agent-dashboard"
```

**Solution:** Specify which packages/directories to include:

```toml
# ✅ Fixed pyproject.toml
[tool.hatch.build.targets.wheel]
packages = ["src"]
```

**Lesson:** When using source layout (code in `src/`), explicitly configure the build system.

---

### 6. Session Title Extraction Needs Fallback Logic

**Problem:** Some sessions have no `ai-title` and the first message might be metadata/system content (e.g., `<local-command-caveat>` tags).

**Solution:** Implement robust fallback hierarchy:

```python
def _extract_title(lines):
    # 1. Try ai-title type
    for msg in lines:
        if msg.get("type") == "ai-title":
            title = msg.get("message", {}).get("content", "").strip()
            if title:
                return _truncate(title, 40)

    # 2. Fallback to first user message
    for msg in lines:
        if msg.get("message", {}).get("role") == "user":
            content = msg.get("message", {}).get("content", "")
            text = _extract_text_from_content(content)
            if text:
                first_line = text.split("\n")[0]
                return _truncate(first_line, 40)

    # 3. Default
    return "[Untitled]"
```

**Lesson:** Real-world data is messy. Build in multiple fallback levels and sensible defaults.

---

### 7. Textual Widget Bindings Silently Override App Bindings

**Problem:** Rebound `enter` at the app level (`BINDINGS`) to a new action, but the key still did nothing. No error, no warning.

**Root cause:** `ListView` (and other interactive widgets) have their own built-in `enter` binding. Widget-level bindings are evaluated before app-level bindings. The widget consumed the keypress silently, and the app binding never fired.

**Solution:** Add `priority=True` to the app-level binding:

```python
# ❌ Silently ignored — ListView's built-in handler fires first
Binding("enter", "open_session", "Open"),

# ✅ priority=True overrides the widget-level handler
Binding("enter", "open_session", "Open", priority=True),
```

**Lesson:** If an app-level key binding appears to do nothing (no error, no response), a widget is almost certainly consuming it first. The fix is `priority=True`. Common widgets with built-in `enter` handling: `ListView`, `DataTable`, `Tree`, `Input`.

---

## Architecture Patterns

### Clean Module Separation
```
src/
├── parser.py     # Data extraction (stateless)
├── dismiss.py    # File I/O (minimal side effects)
└── ui.py         # UI logic (uses parser + dismiss)
```

**Why this works:** UI layer is isolated from data/file operations. Easy to test and modify independently.

### Handling Async/Sync Boundaries
- **Textual app methods** (actions, event handlers) are sync, but run in async context
- **Don't spawn blocking subprocess inside handlers** — use `self.exit(result=...)` and handle in caller
- **`app.run()` is blocking** — use it as a sync point to coordinate with subprocess launches

---

## Testing Strategy

**What worked well:**
1. **Unit test modules independently** before integrating into Textual app
   ```python
   # Test parser without UI
   from src.parser import discover_sessions, format_elapsed_time
   sessions = discover_sessions()
   ```

2. **Mock data for TUI testing**
   - Create test JSONL files with known structure
   - Don't rely on running actual Claude Code sessions

3. **Syntax validation early**
   ```bash
   python -m py_compile src/*.py main.py
   ```

**What to avoid:**
- Don't test Textual UI with timeouts/subprocess in CI (requires interactive terminal)
- Don't assume message format — always validate on real data

---

## File System Considerations

### Claude Code Session Discovery
- **Location:** `~/.claude/projects/` and subdirectories
- **File format:** `.jsonl` (line-delimited JSON)
- **Naming:** `{sessionId}.jsonl`
- **Special case:** Default context sessions under `projects/-/`

### Cross-Platform Path Handling
Use `pathlib.Path`:
```python
projects_dir = Path.home() / ".claude" / "projects"
for jsonl_file in projects_dir.glob("**/*.jsonl"):
    # Cross-platform, handles ~ expansion
```

**Don't** use string concatenation or `os.path.join()` for consistency across platforms.

---

## Common Pitfalls & Solutions

| Problem | Root Cause | Solution |
|---------|-----------|----------|
| "Can't mount widget before attached" | Called `append()` in `__init__()` | Defer to `on_mount()` or use update method later |
| Session opens frozen/unresponsive | Subprocess inherits TUI terminal state | Exit app fully before calling subprocess |
| "AttributeError: 'list' has no attribute 'split'" | Assumed message content is always string | Use helper to extract text from structured content |
| Parsing failures on real data | Assumed spec matched implementation | Always test on real session files early |
| App-level key binding silently ignored | Focused widget has a built-in handler for that key | Add `priority=True` to the app `Binding` |
| Widget `id=` parameter rejected | Didn't pass `**kwargs` to parent `__init__()` | Always use `def __init__(self, ..., **kwargs)` |

---

## Recommendations for Future Agents

1. **Start with data inspection** — read actual session files from `~/.claude/projects/` before designing parser
2. **Test parser independently** — get JSONL parsing 100% right before touching UI
3. **Use Textual's built-in widgets first** — extend only when needed
4. **Handle subprocess carefully** — always respect terminal state management
5. **Plan module separation** — keep UI, data, and I/O concerns separate
6. **Document message format assumptions** — Claude Code uses structured content; be explicit about handling both string and list formats

---

## Code Artifacts Worth Preserving

**Reusable utility: Text extraction from structured content**
```python
def _extract_text_from_content(content):
    """Extract plain text from message content.

    Handles both:
    - String: plain text message
    - List: structured content blocks (text, thinking, images, etc.)
    """
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(block["text"])
        return " ".join(texts).strip()
    return ""
```

Use this in any future Claude Code integrations that parse JSONL.

---

## Final Thoughts

This project revealed that **Claude Code's internal formats are richer than the public spec suggests**. The structured message content is a good design choice for extensibility, but requires robust parsing.

The trickiest part wasn't the UI — it was the terminal state management. Always remember: **Textual uses alternate screen buffer + raw mode**. Any subprocess launched while that's active inherits a broken terminal. Use app lifecycle methods to coordinate.
