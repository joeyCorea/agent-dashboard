---
title: "claude --resume fails when session belongs to a different project"
category: runtime-errors
date: 2026-03-30
severity: high
tags:
  - claude-cli
  - session-management
  - subprocess
  - cwd
  - jsonl-parsing
component: session-resume
symptoms:
  - "No conversation found with session ID" error when opening sessions
  - Sessions from other projects fail to open from the dashboard
  - Only sessions belonging to the dashboard's own project open successfully
---

# `claude --resume` fails when session belongs to a different project

## Problem

Opening a session from the TUI dashboard fails with:

```
No conversation found with session ID: 739b0700-5f0c-4609-956d-b1308be51e2b
```

The dashboard discovers sessions across **all** projects, but `claude --resume` resolves sessions relative to the current working directory's project folder. Any session from a different project is not found.

## Root Cause

`main.py` ran `subprocess.run(["claude", "--resume", session_id])` without an explicit `cwd`, so it inherited the dashboard's own working directory. Claude Code maps CWD to a project slug under `~/.claude/projects/` and only searches for the session within that slug's directory.

## Investigation

### Attempt 1: `~/.claude/sessions/*.json` lookup (incomplete)

The `~/.claude/sessions/` directory contains JSON files with `sessionId` and `cwd` fields. A CWD lookup dictionary was built during startup to map session IDs to their original directories.

**Why it failed:** These files are **ephemeral process metadata** -- they exist only while a Claude process is running and are cleaned up after exit. For the majority of historical sessions, no mapping entry exists.

### Attempt 2: Reverse-mapping the project slug (rejected)

The project slug uses `-` as a separator (e.g., `c--Users-JosephCorea-tools-emtech-noema`), but `-` also appears in directory names (`emtech-noema`). The reverse mapping is ambiguous.

### Attempt 3: Extract `cwd` from JSONL messages (working)

Every user message in the JSONL session log contains a `cwd` field recording the working directory. Since `parse_jsonl()` already reads every line, extracting the first `cwd` value costs nothing and provides a persistent, reliable mapping.

## Solution

### 1. Add `project_dir` to Session dataclass (`src/parser.py`)

```python
@dataclass
class Session:
    # ... existing fields ...
    project_dir: Optional[str] = None  # original cwd for --resume
```

### 2. Extract `cwd` during JSONL parsing (`src/parser.py`)

```python
session_id = None
project_dir = None
for msg in lines:
    if not session_id and "sessionId" in msg:
        session_id = msg["sessionId"]
    if not project_dir and "cwd" in msg:
        project_dir = msg["cwd"]
    if session_id and project_dir:
        break
```

### 3. Return full Session object from UI (`src/ui.py`)

```python
# Before:
self.exit(result=session.session_id)
# After:
self.exit(result=session)
```

### 4. Pass `cwd` to subprocess (`main.py`)

```python
if session:
    cwd = session.project_dir if session.project_dir and Path(session.project_dir).is_dir() else None
    subprocess.run(["claude", "--resume", session.session_id], cwd=cwd)
```

The `Path.is_dir()` guard handles deleted directories gracefully -- falls back to inheriting the dashboard's CWD.

## Key Insight: Primary Artifact vs External Metadata

The fundamental mistake was treating a process-lifetime sidecar file (`sessions/*.json`) as persistent session metadata. The JSONL log is the **primary artifact** -- append-only, survives crashes, and contains the authoritative record. Build on the data source with the strongest durability guarantee.

**General principle:** If a file only exists while a process is running, never use it as the source of truth for a tool that runs after the process exits.

## Prevention Checklist

- [ ] Treat any `subprocess.run` call without explicit `cwd` as a defect if the child process is project-specific
- [ ] Before relying on a data source, ask: "Will this still exist in the failure case I'm debugging?"
- [ ] Prefer data embedded in the primary artifact (JSONL) over external metadata files
- [ ] Smoke-test with the originating process stopped, not just while running
- [ ] Design dashboards for the cold-start case -- sessions may be hours or days old

## Related Documentation

- [resume-wrong-cwd-bug.md](../resume-wrong-cwd-bug.md) -- original bug report and analysis
- [claude-code-session-tui-lessons.md](../claude-code-session-tui-lessons.md) -- Lesson #2: subprocess must be called from main.py after app fully exits
- [implementation-checklist.md](../implementation-checklist.md) -- Phase 3: subprocess integration patterns
- [clear-session-and-subagent-filtering.md](../clear-session-and-subagent-filtering.md) -- session discovery path depth guards
