# Spec Review: CWD Bug Fix for `claude --resume`

**Date:** 2026-03-30
**Spec:** Pass session's original CWD to `subprocess.run()` when resuming a session

---

## Codebase Context

Key files examined:

- `/main.py` -- receives `session_id` string from `app.run()`, calls `subprocess.run(["claude", "--resume", session_id])` with no `cwd`
- `/src/parser.py` -- `Session` dataclass has no `project_dir` field; `discover_sessions()` globs `~/.claude/projects/**/*.jsonl`; the project slug is already extracted from the file path but only used for a display-friendly `project_name` (last segment after `--`)
- `/src/ui.py` -- `action_open_session()` calls `self.exit(result=session.session_id)` returning only a string
- `/src/dismiss.py` -- uses session IDs only, no path concern
- `~/.claude/sessions/*.json` -- confirmed structure: `{"pid":..., "sessionId":"...", "cwd":"C:\\Users\\...", ...}` (one JSON object per line, NOT newline-delimited -- multiple objects concatenated in a single file)
- `~/.claude/projects/` -- slug format is `{drive-letter}--{path-segments-joined-by-dash}`, e.g., `C--Users-JosephCorea-tools-claude-dashboard` maps to `C:\Users\JosephCorea\tools\claude-dashboard`

---

## User Flows

### Flow 1: Open session (happy path)

1. User launches dashboard (`uv run main.py` or equivalent)
2. TUI discovers sessions, displays them
3. User navigates to a session, presses Enter/o
4. TUI exits, returns session ID + CWD to `main.py`
5. `main.py` runs `claude --resume <id>` with `cwd=<project_dir>`
6. Claude resumes the session in the correct project context

### Flow 2: Session whose original directory no longer exists

1. User opens a session whose `cwd` pointed to a since-deleted or renamed directory
2. `subprocess.run()` receives a nonexistent `cwd` and raises `FileNotFoundError`

### Flow 3: Session with no discoverable CWD

1. A JSONL file exists in `~/.claude/projects/` but neither the slug nor `~/.claude/sessions/*.json` yields a usable CWD
2. The `project_dir` field is `None` or empty
3. `main.py` must decide what to pass to `subprocess.run()`

---

## Gaps

### Critical

**1. Slug-to-path reverse mapping is ambiguous and lossy on Windows.**

The spec proposes deriving `project_dir` from the JSONL file path slug (e.g., `C--Users-JosephCorea-tools-claude-dashboard`). The encoding rule is: replace path separators with `-`. But `-` also appears in legitimate directory names (`claude-dashboard`, `emtech-noema`). There is no way to distinguish `tools-claude-dashboard` (one directory) from `tools/claude/dashboard` (three directories) by looking at the slug alone.

**This rules out the slug-based approach as a reliable primary source.** The `~/.claude/sessions/*.json` files contain an explicit `"cwd"` field and are the only reliable source.

Why it matters: if you get the path wrong, `claude --resume` either fails with "not found" (same bug you're fixing) or resumes in the wrong project context, which is worse -- it silently operates on the wrong codebase.

**2. The sessions JSON files have a non-standard format.**

The spec assumes `~/.claude/sessions/*.json` contains `{"sessionId": "...", "cwd": "..."}`. Inspecting the actual files, each `.json` file contains **multiple JSON objects concatenated without newline delimiters** (not valid JSON, not JSONL). The parser must handle this: split on `}{` boundaries, or read as a stream, or treat the entire file as a single JSON object (which would fail). If this isn't handled, `json.loads()` will throw on multi-object files.

Additionally, there can be **multiple entries per file** (e.g., `34100.json` and `27060.json` both reference session `739b0700-...` with different PIDs). The parser needs to handle duplicate session IDs across entries and decide which CWD to use (likely the most recent by `startedAt`).

### Important

**3. No fallback behavior specified when CWD lookup fails.**

The spec does not say what happens when:
- The session's CWD cannot be determined (no matching entry in `~/.claude/sessions/`)
- The CWD directory has been deleted or renamed
- The session JSON files are missing entirely (e.g., cleaned up by the user)

Current behavior (passing no `cwd`) is broken, but it at least doesn't crash. The fix must define a fallback. Options: (a) fall back to the dashboard's own CWD (current broken behavior, but at least it runs), (b) show an error in the TUI before exiting, (c) prompt the user.

**4. The `Session` dataclass change affects `full_message_history` memory.**

Each `Session` already stores the complete JSONL content in `full_message_history`. Adding `project_dir` is fine, but the real concern is the implementation approach: if the fix reads `~/.claude/sessions/*.json` during `discover_sessions()`, it must iterate all session JSON files for every session to build a sessionId-to-CWD lookup. With many sessions, this adds I/O. Consider building the lookup map once and passing it through.

**5. The `action_open_session` return type change is a breaking interface change.**

The spec says to return "the full Session object (or a tuple of session_id + cwd) instead of just the session ID string." Currently `app.run()` returns a string. Changing it to return a `Session` object is cleaner but changes the contract. Since `main.py` is the only consumer, this is safe, but the spec should be explicit about which approach to use rather than leaving it as "or."

### Minor

**6. Case sensitivity in slug matching.**

The project slugs have inconsistent casing: `C--Users-JosephCorea-tools-claude-dashboard` vs. `c--Users-JosephCorea-tools-emtech-noema` (uppercase `C` vs. lowercase `c` for the drive letter). If the slug-based approach is used as a fallback, case-insensitive comparison is required on Windows.

**7. The `project_name` display field uses `rsplit("--", 1)[-1]` which discards context.**

This is pre-existing, not introduced by this fix, but worth noting: two projects at different paths ending in the same directory name (e.g., `tools/dashboard` and `apps/dashboard`) would display the same `project_name`. Since `project_dir` will now be available, the display could be improved -- but that's a separate enhancement.

---

## Questions

### 1. Should the `~/.claude/sessions/*.json` files be the sole source for CWD?

**Stakes:** The slug-to-path reverse mapping is fundamentally unreliable due to the `-` ambiguity. Using it produces silent wrong-directory bugs that are worse than the original failure.

**Default assumption:** Use `~/.claude/sessions/*.json` as the sole source. Fall back to `None` if not found.

### 2. What should happen when the resolved CWD directory does not exist on disk?

**Stakes:** `subprocess.run(cwd=...)` raises `FileNotFoundError`, crashing the dashboard. This is a regression from the current behavior (which at least attempts to launch Claude).

**Default assumption:** Check `os.path.isdir(cwd)` before passing it. If it doesn't exist, fall back to not passing `cwd` (current behavior) and let Claude's own error handling take over. Optionally log a warning.

### 3. What should the return type from `app.run()` be -- `Session` object or `tuple`?

**Stakes:** Low -- both work. But the spec should pick one to avoid implementation ambiguity.

**Default assumption:** Return the `Session` object. It's already constructed, carries all needed fields, and avoids creating a new data structure.

### 4. How should the parser handle the concatenated JSON format in session files?

**Stakes:** The current session files are not valid JSON or JSONL. A naive `json.loads(file.read())` will fail. A naive line-by-line JSONL read will also fail since multiple objects can be on one line.

**Default assumption:** Read the entire file content and split on `}\s*{` boundaries, wrapping each chunk in braces, then parse individually. Or use `json.JSONDecoder().raw_decode()` in a loop.

### 5. Should the CWD lookup be indexed by session ID or by PID filename?

**Stakes:** The session JSON filenames are PIDs (e.g., `2172.json`), not session IDs. A session can appear in multiple PID files (e.g., resumed across multiple Claude processes). The lookup must scan all files and match by `sessionId` field.

**Default assumption:** Build a `dict[str, str]` mapping sessionId to CWD by scanning all `~/.claude/sessions/*.json` files once at discovery time. When multiple entries exist for the same sessionId, use the one with the latest `startedAt`.

---

## Recommended Next Steps

1. **Answer Question 1 first** -- confirm `~/.claude/sessions/*.json` as the CWD source. This determines the entire implementation approach. The slug-based approach in the spec should be dropped or demoted to a last-resort fallback only.

2. **Prototype the session JSON parser** (Question 4) -- the concatenated-JSON format is the main implementation risk. Write a small utility function and test it against the actual files in `~/.claude/sessions/` before integrating.

3. **Add `project_dir: Optional[str]` to `Session`** with a `None` default so existing code doesn't break. Build the sessionId-to-CWD lookup map in `discover_sessions()` and populate it during session construction.

4. **Change `action_open_session` to return the `Session` object** (Question 3). Update `main.py` to extract `session.session_id` and `session.project_dir` from the result.

5. **Add a guard in `main.py`** for missing/deleted directories (Question 2):
   ```python
   cwd = session.project_dir if session.project_dir and os.path.isdir(session.project_dir) else None
   subprocess.run(["claude", "--resume", session.session_id], cwd=cwd)
   ```

6. **Write an integration test** that exercises the end-to-end flow: mock a `.claude/sessions/*.json` file, mock a JSONL session file, call `discover_sessions()`, verify `project_dir` is populated, and verify it gets passed through to the subprocess call.
