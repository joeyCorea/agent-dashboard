"""
Session discovery and JSONL parsing.

Scans ~/.claude/projects/ for session files and extracts metadata.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class Session:
    """Represents a Claude Code session."""

    session_id: str
    project_name: str
    title: str
    last_message_timestamp: datetime
    last_assistant_message: str
    filepath: Path
    status: str = "ready"  # "in progress" or "ready"
    project_dir: Optional[str] = None  # original cwd for --resume


def load_message_history(filepath: Path) -> list[dict]:
    """Load and return all parsed JSONL lines from a session file on demand.

    Args:
        filepath: Path to the .jsonl session file

    Returns:
        List of parsed message dicts, or empty list on error
    """
    lines = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    lines.append(json.loads(line))
    except Exception:
        return []
    return lines


def _build_session_cwd_map() -> dict[str, str]:
    """Scan ~/.claude/sessions/*.json and return {session_id: cwd}.

    These files contain concatenated JSON objects (not valid JSON, not JSONL).
    We use raw_decode() to parse multiple objects from each file.
    """
    sessions_dir = Path.home() / ".claude" / "sessions"
    if not sessions_dir.exists():
        return {}

    cwd_map: dict[str, str] = {}
    decoder = json.JSONDecoder()

    for json_file in sessions_dir.glob("*.json"):
        try:
            raw = json_file.read_text(encoding="utf-8")
            idx = 0
            while idx < len(raw):
                remaining = raw[idx:].lstrip()
                if not remaining:
                    break
                obj, end = decoder.raw_decode(remaining)
                idx += (len(raw) - idx) - len(remaining) + end
                sid = obj.get("sessionId")
                cwd = obj.get("cwd")
                if sid and cwd:
                    cwd_map[sid] = cwd
        except Exception:
            continue

    return cwd_map


def discover_sessions() -> list[Session]:
    """
    Discover all sessions in ~/.claude/projects/ recursively.

    Returns:
        List of Session objects, or empty list if directory doesn't exist.
    """
    projects_dir = Path.home() / ".claude" / "projects"

    if not projects_dir.exists():
        return []

    sessions = []

    # Find all .jsonl files, but only at the top level of each project directory.
    # Nested files (e.g. {session}/subagents/{agent}.jsonl) are subagent logs,
    # not user sessions, and must be excluded.
    for jsonl_file in projects_dir.glob("**/*.jsonl"):
        relative = jsonl_file.relative_to(projects_dir)
        if len(relative.parts) != 2:
            continue
        try:
            session = parse_jsonl(jsonl_file)
            if session:
                sessions.append(session)
        except Exception as e:
            # Log but continue on parse errors
            print(f"Warning: Failed to parse {jsonl_file}: {e}")

    # Sort by most recent activity first
    sessions.sort(key=lambda s: s.last_message_timestamp, reverse=True)

    return sessions


def parse_jsonl(filepath: Path) -> Optional[Session]:
    """
    Parse a single JSONL session file.

    Args:
        filepath: Path to the .jsonl file

    Returns:
        Session object or None if parsing fails
    """
    lines = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    lines.append(json.loads(line))
    except Exception:
        return None

    if not lines:
        return None

    # Sessions spawned by /clear are artifacts, not pending conversations.
    # They contain the /clear slash command in a user message and have no
    # assistant reply — skip them so they don't pollute the TUI list.
    if _is_clear_session(lines):
        return None

    # Extract session ID and cwd from the first message that has them
    session_id = None
    project_dir = None
    for msg in lines:
        if not session_id and "sessionId" in msg:
            session_id = msg["sessionId"]
        if not project_dir and "cwd" in msg:
            project_dir = msg["cwd"]
        if session_id and project_dir:
            break

    if not session_id:
        return None

    # Extract project name from filepath
    # Path format: ~/.claude/projects/{project}/{sessionId}.jsonl
    # or: ~/.claude/projects/-/{sessionId}.jsonl
    relative_parts = filepath.relative_to(Path.home() / ".claude" / "projects").parts
    if len(relative_parts) >= 2:
        # The directory name is a slug like "c--tools-agent-dashboard"
        # where "--" encodes path separators. Use the last segment for a
        # cleaner display name (e.g. "agent-dashboard").
        slug = relative_parts[0]
        project_name = slug.rsplit("--", 1)[-1] if "--" in slug else slug
    else:
        project_name = "-"

    # Find ai-title or fallback to first user message
    title = _extract_title(lines)

    # Get last message timestamp
    last_timestamp = None
    for msg in reversed(lines):
        if "timestamp" in msg:
            try:
                ts_str = msg["timestamp"]
                # Python < 3.11 doesn't support 'Z' as UTC in fromisoformat;
                # replace it with the equivalent '+00:00' offset.
                if isinstance(ts_str, str) and ts_str.endswith("Z"):
                    ts_str = ts_str[:-1] + "+00:00"
                last_timestamp = datetime.fromisoformat(ts_str)
                break
            except (ValueError, TypeError):
                pass

    if not last_timestamp:
        last_timestamp = datetime.now()

    # Extract last assistant message for preview
    last_assistant_msg = _extract_last_assistant_message(lines)

    # Determine session status based on the last conversational message role.
    # If the last role is "user", the agent is still formulating its response.
    # If the last role is "assistant", the agent has finished and is waiting.
    status = _determine_status(lines)

    return Session(
        session_id=session_id,
        project_name=project_name,
        title=title,
        last_message_timestamp=last_timestamp,
        last_assistant_message=last_assistant_msg,
        filepath=filepath,
        status=status,
        project_dir=project_dir,
    )


def _is_clear_session(lines: list[dict]) -> bool:
    """Return True if this file was spawned by a /clear command.

    When a user types /clear in Claude Code, a new session file is created
    containing a file-history-snapshot, the /clear slash command logged as a
    user message, and a system result entry.  No assistant message is written.
    These are not real pending sessions — they are housekeeping artifacts.

    Detection: at least one user message whose content contains the /clear
    command tag AND no assistant message anywhere in the file.
    """
    has_clear_command = False
    has_assistant = False
    for msg in lines:
        content = msg.get("message", {}).get("content", "")
        if isinstance(content, str) and "<command-name>/clear</command-name>" in content:
            has_clear_command = True
        if msg.get("message", {}).get("role") == "assistant":
            has_assistant = True
    return has_clear_command and not has_assistant


def _determine_status(lines: list[dict]) -> str:
    """Determine whether the agent is still formulating or has finished.

    Walks backwards through the message history to find the last message
    with a conversational role (user or assistant).  If the last such role
    is "user", the agent hasn't replied yet → "in progress".  Otherwise
    → "ready".
    """
    for msg in reversed(lines):
        role = msg.get("message", {}).get("role")
        if role in ("user", "assistant"):
            return "in progress" if role == "user" else "ready"
    return "ready"


def _extract_title(lines: list[dict]) -> str:
    """
    Extract session title from ai-title field or first user message.

    Args:
        lines: List of message dictionaries from JSONL

    Returns:
        Title string, truncated to ~40 chars. Defaults to "[Untitled]"
    """
    # First, look for ai-title
    for msg in lines:
        if msg.get("type") == "ai-title":
            title = msg.get("message", {}).get("content", "").strip()
            if title:
                return _truncate(title, 40)

    # Fallback to first user message
    for msg in lines:
        if msg.get("message", {}).get("role") == "user":
            content = msg.get("message", {}).get("content", "")
            text = _extract_text_from_content(content)
            if text:
                # Get first line only
                first_line = text.split("\n")[0]
                return _truncate(first_line, 40)

    return "[Untitled]"


def _extract_last_assistant_message(lines: list[dict]) -> str:
    """
    Extract the last assistant message for preview.

    Args:
        lines: List of message dictionaries from JSONL

    Returns:
        First line of last assistant message, or empty string
    """
    for msg in reversed(lines):
        if msg.get("message", {}).get("role") == "assistant":
            content = msg.get("message", {}).get("content", "")
            text = _extract_text_from_content(content)
            if text:
                # Get first line only
                first_line = text.split("\n")[0]
                return _truncate(first_line, 70)

    return ""


def _extract_text_from_content(content) -> str:
    """
    Extract plain text from message content.

    Content can be either a string or a list of structured objects.

    Args:
        content: Either a string or a list of dicts with type/text fields

    Returns:
        Plain text string
    """
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        # Collect text from structured content blocks
        texts = []
        for block in content:
            if isinstance(block, dict):
                # Extract text blocks (ignore thinking, images, etc.)
                if block.get("type") == "text" and "text" in block:
                    texts.append(block["text"])
        return " ".join(texts).strip()

    return ""


def _truncate(text: str, max_len: int) -> str:
    """Truncate text with ellipsis if it exceeds max_len."""
    if len(text) > max_len:
        return text[:max_len - 3] + "..."
    return text


def format_elapsed_time(timestamp: datetime) -> str:
    """
    Format elapsed time from timestamp to now.

    Args:
        timestamp: datetime object

    Returns:
        Human-readable elapsed time string (e.g., "2h ago", "just now")
    """
    now = datetime.now(timestamp.tzinfo) if timestamp.tzinfo else datetime.now()
    elapsed = now - timestamp

    seconds = int(elapsed.total_seconds())

    if seconds < 60:
        return "just now"
    elif seconds < 3600:
        minutes = seconds // 60
        return f"{minutes}m ago"
    elif seconds < 86400:
        hours = seconds // 3600
        return f"{hours}h ago"
    elif seconds < 604800:
        days = seconds // 86400
        return f"{days}d ago"
    else:
        weeks = seconds // 604800
        return f"{weeks}w ago"
