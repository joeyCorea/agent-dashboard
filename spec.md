# Spec: Claude Code Pending Sessions TUI

---

## Problem

When working across multiple Claude Code sessions, it's easy to lose track of which ones are waiting for your response. There's no ambient signal — you have to check each session manually.

---

## Goal

A keyboard-driven TUI that lists Claude Code sessions awaiting your reply, so you can quickly jump into the one that needs attention without hunting through multiple windows.

---

## Data Source

Claude Code stores session data locally:

- **Session metadata:** `~/.claude/projects/{project-name}/{sessionId}.jsonl`
- **Default context:** `~/.claude/projects/-/{sessionId}.jsonl` (or similar, for non-project conversations)

Each `.jsonl` file is a line-delimited JSON log. Each line is a message with:
- `type`: `"user"` | `"assistant"` | `"ai-title"` | etc.
- `message.role`: `"user"` | `"assistant"`
- `sessionId`: unique identifier for the session
- `timestamp`: ISO 8601 string
- `message.content`: the message text or structured content

---

## Core Logic: "Pending" Definition

Since Claude always responds, **all active sessions are considered "pending"** by default. A session is marked as **dismissed** when its `sessionId` appears in the dismissal log.

### Dismissal Log

**Location:** `~/.claude/session.log`

Simple text file, one `sessionId` per line. Sessions whose IDs appear here are hidden from the TUI.

### How Sessions Get Dismissed

1. **From within a Claude Code session:** User types `/clear` → `SessionEnd` hook fires → logs the `sessionId` to `~/.claude/session.log`
   - Hook configuration (in `~/.claude/settings.json`):
     ```json
     {
       "hooks": {
         "SessionEnd": [
           {
             "matcher": "clear",
             "hooks": [
               {
                 "type": "command",
                 "command": "python -c \"import sys,json; print(json.load(sys.stdin)['session_id'])\" >> ~/.claude/session.log"
               }
             ]
           }
         ]
       }
     }
     ```
   - The hook reads session context from stdin as JSON and appends the `session_id` value (one per line) to `~/.claude/session.log`

2. **From the TUI:** User presses `d` on a session → TUI appends `sessionId` to `~/.claude/session.log`

---

## UI: Pending Sessions List

A scrollable list of all non-dismissed sessions, sorted by most recent activity (timestamp descending).

Each row displays:
- **Project name** (derived from directory; "-" for default context)
- **Session title** (from `ai-title` field in the JSONL, or first user message, truncated to ~40 chars)
- **Time since last message** (e.g., "2h ago", "just now")
- **Last message preview** (first line, truncated to fit, from last `assistant` message)

Example:
```
┌─ Pending Claude Sessions (3) ────────────────────────────────────────┐
│                                                                       │
│  > c--tools-agent    [Refactor auth module]            2h ago        │
│    "I've outlined three approaches for splitting the..."             │
│                                                                       │
│    my-project        [API endpoint design]             5h ago        │
│    "Here's the full implementation. Ready to code?"                  │
│                                                                       │
│    -                 [Untitled]                        1d ago        │
│    "That looks good. What should we handle next?"                    │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
 [j/k] navigate  [Space] preview  [Enter/o] open  [d] dismiss  [r] refresh  [q] quit
```

### Empty State
If no sessions are pending: `All caught up.`

---

## Key Bindings

| Key | Action |
|-----|--------|
| `j` / `k` or `↑` / `↓` | Navigate list |
| `Enter` / `o` | Open session in Claude Code (`claude --resume {sessionId}`) |
| `Space` | Toggle inline preview pane |
| `d` | Dismiss session (append to `~/.claude/session.log`) |
| `r` | Refresh / re-scan conversation files |
| `q` / `Ctrl+C` | Quit |

---

## Preview Pane

Pressing `Space` on a session opens a preview panel below the list showing recent messages (last ~5 exchanges). Display as a scrollable conversation thread (you/Claude alternating). No reply capability from TUI.

```
┌─ Preview: c--tools-agent / Refactor auth module ──────────────────────┐
│  You:    Can you suggest how to split the auth module?                │
│                                                                        │
│  Claude: I've outlined three approaches for splitting the module...   │
│  1. Extract into a dedicated auth/ directory...                       │
│  2. Keep co-located but split by concern...                           │
│  3. Full service extraction with an HTTP boundary...                  │
│                                                                        │
│  You:    Let's go with option 2.                                      │
│                                                                        │
│  Claude: Good choice. Here's how to refactor...                       │
└────────────────────────────────────────────────────────────────────────┘
 [Esc] close preview  [↑/↓] scroll  [o] open in Claude Code
```

---

## Opening a Session

Pressing `o` or `Enter` runs:

```bash
claude --resume {sessionId}
```

This opens the session in Claude Code, returning focus to the user. They can now:
- Reply to Claude
- Use `/clear` to dismiss when done (triggers the `SessionEnd` hook)
- Work as normal

---

## Refresh Behavior

- On launch: scan all `.jsonl` files in `~/.claude/projects/` and subdirectories
- On `r` key: re-scan
- No auto-refresh (user manually restarts TUI when needed)

---

## Implementation Notes

**Language:** Python 3.10+

**TUI Library:** [Rich](https://rich.readthedocs.io/) (for rendering) + [Textual](https://textual.textualize.io/) (for interactive TUI framework)

**Package Manager:** [uv](https://docs.astral.sh/uv/) for running and dependency management

**Project Structure:**
```
agent-dashboard/
├── pyproject.toml          # uv project config
├── spec.md                 # this file
├── main.py                 # entry point
└── src/
    ├── parser.py           # JSONL parsing, session loading
    ├── ui.py               # Textual app and views
    └── dismiss.py          # Dismissal log management
```

**Parsing:**
- Scan `~/.claude/projects/` recursively for `.jsonl` files
- For each file, read all lines and identify the `sessionId` and `ai-title`
- Extract the last `assistant` message for preview
- Compute elapsed time from the last message's `timestamp`

**Dismissal Logic:**
- Read `~/.claude/session.log` on startup and after each dismiss
- Filter out any session whose `sessionId` appears in the log
- When user presses `d`, append `sessionId\n` to the file

---

## Hook Configuration

Users will need to add a `SessionEnd` hook to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionEnd": [
      {
        "matcher": "clear",
        "hooks": [
          {
            "type": "command",
            "command": "python -c \"import sys,json; print(json.load(sys.stdin)['session_id'])\" >> ~/.claude/session.log"
          }
        ]
      }
    ]
  }
}
```

Claude Code passes session context to the hook via stdin as a JSON object. The inline Python reads that JSON, extracts `session_id`, and appends it to `~/.claude/session.log`. The `matcher: "clear"` ensures the hook only fires when `/clear` is used.

---

## Out of Scope (v1)

- Replying from within the TUI
- Searching/filtering sessions
- Starred or pinned sessions
- Custom session ordering
- Archiving vs. deletion distinction

---

## Implementation Clarifications

### 1. Hook Argument Passing

**Decision:** Session ID passed via stdin as JSON — `{"session_id": "..."}` (and other fields)

**Rationale:**
- Claude Code's hook mechanism passes context to hook commands via stdin as a JSON object
- The `session_id` field is extracted with an inline Python one-liner; no external script needed
- The `matcher` field on the hook entry scopes the hook to `/clear` only, avoiding spurious writes

### 2. CLI Syntax for Resuming Sessions

**Decision:** `claude --resume {sessionId}`

Confirmed. This opens the session in Claude Code with full context restored.

### 3. Dismissal State Storage

**Options:**

| Option | Approach | Pros | Cons |
|--------|----------|------|------|
| **A** (Recommended) | Single text file: `~/.claude/session.log` | Simple, transparent, auditable, human-readable | Append-only (grows over time, needs occasional cleanup) |
| **B** | Per-session marker: `.dismissed` file in each session dir | Atomic, easy to undo (delete marker), scattered state | Harder to audit globally, file system sprawl |
| **C** | Structured JSON: `~/.claude/dismissed-sessions.json` | Can include metadata (time, reason), structured | JSON parsing overhead, more complex |
| **D** | Organized text: `~/.claude/state/dismissed.txt` | Same as A but organized | Just organizational (functionally identical to A) |

**Recommendation:** **Option A** (`~/.claude/session.log`)

**Why:**
- Simplicity: one plain text file, one session ID per line
- Transparency: users can inspect and manually edit if needed (e.g., undo a dismissal)
- Auditability: full history of all dismissed sessions
- Low overhead: no parsing, just line-by-line reads
- Unix philosophy: simple tools, simple formats
- If growth is a concern, users can archive old entries (rotate the log)

The dismissal log is the source of truth: on every TUI start and refresh, read this file and filter those session IDs from the active list.
