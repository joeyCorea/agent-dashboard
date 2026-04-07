# Bug: "No conversation found with session ID" when opening from dashboard

## Symptom

When opening a session from the dashboard with Enter/o, Claude Code reports:

```
No conversation found with session ID: 739b0700-5f0c-4609-956d-b1308be51e2b
```

## Root Cause

`claude --resume {sessionId}` resolves the session JSONL file **relative to the current working directory**. It looks for the file under `~/.claude/projects/{project-slug-for-cwd}/{sessionId}.jsonl`. If the dashboard was launched from a different directory than the one the session belongs to, the lookup fails.

### How the flow works today

1. `parser.py` / `discover_sessions()` scans **all** projects under `~/.claude/projects/` recursively -- it finds sessions from every project.
2. User selects a session and presses Enter/o.
3. `ui.py` / `action_open_session()` calls `self.exit(result=session.session_id)`.
4. `main.py` receives the session ID and runs `subprocess.run(["claude", "--resume", session_id])`.
5. Claude Code receives the session ID but looks for it **only** in the project directory corresponding to the subprocess's cwd (inherited from the dashboard process).

### Why it fails

The session `739b0700-...` belongs to `media_agent` (stored under `C--Users-JosephCorea-tools-media-agent/`). But the dashboard was launched from `claude-dashboard`. Claude Code looks under `C--Users-JosephCorea-tools-claude-dashboard/` and finds no matching session.

### Proof

```
# Fails (wrong cwd):
cd ~/tools/claude-dashboard
claude --resume 739b0700-5f0c-4609-956d-b1308be51e2b
# => No conversation found with session ID: 739b0700-...

# Works (correct cwd):
cd ~/tools/media_agent
claude --resume 739b0700-5f0c-4609-956d-b1308be51e2b
# => Resumes successfully
```

## Fix

The fix must ensure that `claude --resume` is invoked from the correct working directory for the session being opened. Two approaches:

### Option A (Recommended): Change cwd in subprocess call

The `Session` dataclass already stores `project_name` derived from the filepath. Extend it to also store the **original project directory path** (the full path to the `.jsonl` file's parent), then derive the real working directory from it. Alternatively, use `~/.claude/sessions/*.json` which contains a `cwd` field for each session.

In `main.py`, change:

```python
subprocess.run(["claude", "--resume", session_id])
```

to:

```python
subprocess.run(["claude", "--resume", session_id], cwd=session_cwd)
```

### Option B: Store the original cwd on the Session dataclass

Add a `cwd` field to `Session` that is populated either from:
- The `sessions/*.json` file that maps session IDs to their working directories, or
- The project slug in the filepath, reverse-mapped back to the original path (less reliable).

## Files involved

- `/main.py` (line 18) -- where `subprocess.run` is called without explicit cwd
- `/src/parser.py` -- `Session` dataclass and `discover_sessions()` / `parse_jsonl()`
- `/src/ui.py` (line 254) -- `action_open_session()` exits with only the session_id string
- `~/.claude/sessions/*.json` -- contains `cwd` field per session (source of truth for working directory)
