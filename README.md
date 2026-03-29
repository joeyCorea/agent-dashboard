# Claude Code Pending Sessions TUI

When working across multiple Claude Code sessions, it's easy to lose track of which ones are waiting for your response. 

There's no ambient signal — you have to check each session manually.

I created a keyboard-driven terminal UI to track and manage Claude Code sessions awaiting your response.

## Installation

```bash
pip install textual
```

Or use `uv`:

```bash
uv run main.py
```

## Usage

```bash
python main.py
```

This launches an interactive TUI that displays:
- All active Claude Code sessions sorted by most recent activity
- Project name, session title, time elapsed, and last message preview
- A scrollable list with keyboard navigation

<img width="1236" height="514" alt="image" src="https://github.com/user-attachments/assets/ab57d567-4f8f-4f09-afd0-0210d58f6a03" />


## Key Bindings

| Key | Action |
|-----|--------|
| `j` / `k` or `↑` / `↓` | Navigate list |
| `Space` | Toggle preview pane (shows last ~5 message exchanges) |
| `o` / `Enter` | Open session in Claude Code |
| `d` | Dismiss session (hide from list) |
| `r` | Refresh / re-scan conversation files |
| `q` / `Ctrl+C` | Quit |

## How It Works

### Session Discovery
- Scans `~/.claude/projects/` for `.jsonl` session files
- Parses Claude Code session metadata (ID, title, messages, timestamps)
- Displays active sessions in reverse chronological order

### Dismissal
- Sessions can be marked as dismissed by pressing `d`
- Dismissed session IDs are stored in `~/.claude/session.log`
- Dismissed sessions are hidden from the TUI
- Can also be dismissed from within Claude Code via `/clear` command with proper hook setup

### Session Structure
```
~/.claude/projects/
├── {project-name}/
│   └── {sessionId}.jsonl    # Session messages (line-delimited JSON)
├── -/
│   └── {sessionId}.jsonl    # Default context sessions
└── (etc.)
```

## Hook Configuration

To automatically dismiss sessions when using `/clear` in Claude Code, add a `SessionEnd` hook to `~/.claude/settings.json`:

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

The hook fires on `/clear`, reads the session ID from stdin (passed by Claude Code as JSON), and appends it to `~/.claude/session.log`. The TUI reads that file on startup and on refresh to exclude dismissed sessions.

## Project Structure

```
agent-dashboard/
├── pyproject.toml          # Project configuration
├── spec.md                 # Specification
├── README.md               # This file
├── main.py                 # Entry point
└── src/
    ├── __init__.py
    ├── parser.py           # Session discovery and JSONL parsing
    ├── dismiss.py          # Dismissal log management
    └── ui.py               # Textual TUI application
```

## Supported Claude Code Message Formats

The parser handles multiple message content formats:
- **String content**: Plain text messages
- **Structured content**: Lists of objects with type/text fields (used for text, thinking, images, etc.)

## Future Enhancements (Out of Scope v1)

- Replying from within the TUI
- Searching/filtering sessions
- Starred or pinned sessions
- Custom session ordering
- Archiving vs. deletion distinction
