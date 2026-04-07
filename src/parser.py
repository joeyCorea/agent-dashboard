"""
Session discovery and JSONL parsing.

Scans ~/.claude/projects/ for session files and extracts metadata.
Uses an mtime-based metadata cache to skip re-parsing unchanged files.
"""

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.cache import load_cache, save_cache


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


def _session_to_cache_entry(session: Session) -> dict:
    """Serialize a Session to a cache-storable dict."""
    d = asdict(session)
    d["filepath"] = str(d["filepath"])
    d["last_message_timestamp"] = session.last_message_timestamp.isoformat()
    return d


def _session_from_cache_entry(entry: dict) -> Session:
    """Deserialize a Session from a cache dict."""
    return Session(
        session_id=entry["session_id"],
        project_name=entry["project_name"],
        title=entry["title"],
        last_message_timestamp=datetime.fromisoformat(entry["last_message_timestamp"]),
        last_assistant_message=entry["last_assistant_message"],
        filepath=Path(entry["filepath"]),
        status=entry.get("status", "ready"),
        project_dir=entry.get("project_dir"),
    )


# Module-level cache dict, persisted across refreshes within a single app run.
_cache: dict | None = None


def discover_sessions() -> list[Session]:
    """
    Discover all sessions in ~/.claude/projects/ recursively.

    Uses an mtime-based cache to skip re-parsing unchanged files.

    Returns:
        List of Session objects, or empty list if directory doesn't exist.
    """
    global _cache

    projects_dir = Path.home() / ".claude" / "projects"

    if not projects_dir.exists():
        return []

    cache_path = Path.home() / ".claude" / "dashboard-cache.json"

    if _cache is None:
        _cache = load_cache(cache_path)

    sessions = []
    new_cache = {}

    # Find all .jsonl files, but only at the top level of each project directory.
    # Nested files (e.g. {session}/subagents/{agent}.jsonl) are subagent logs,
    # not user sessions, and must be excluded.
    for jsonl_file in projects_dir.glob("**/*.jsonl"):
        relative = jsonl_file.relative_to(projects_dir)
        if len(relative.parts) != 2:
            continue

        key = str(jsonl_file)
        try:
            file_mtime = jsonl_file.stat().st_mtime
        except OSError:
            continue

        # Use cached metadata if mtime unchanged
        cached = _cache.get(key)
        if cached and cached.get("mtime") == file_mtime:
            try:
                session = _session_from_cache_entry(cached["metadata"])
                sessions.append(session)
                new_cache[key] = cached
                continue
            except Exception:
                pass  # fall through to re-parse

        # Parse the file (new or modified)
        try:
            session = parse_jsonl(jsonl_file)
            if session:
                sessions.append(session)
                new_cache[key] = {
                    "mtime": file_mtime,
                    "metadata": _session_to_cache_entry(session),
                }
        except Exception as e:
            print(f"Warning: Failed to parse {jsonl_file}: {e}")

    # Update module-level and disk caches
    _cache = new_cache
    try:
        save_cache(cache_path, new_cache)
    except Exception:
        pass  # cache write failure is non-fatal

    # Sort by most recent activity first
    sessions.sort(key=lambda s: s.last_message_timestamp, reverse=True)

    return sessions


def parse_jsonl(filepath: Path) -> Optional[Session]:
    """
    Parse a single JSONL session file in a single pass.

    Reads each line once, extracting all needed metadata in one loop:
    session_id, cwd, title, timestamp, last assistant message, status,
    and clear-session detection.

    Args:
        filepath: Path to the .jsonl file

    Returns:
        Session object or None if parsing fails or session is a /clear artifact
    """
    session_id = None
    project_dir = None
    title = None
    first_user_text = None
    has_clear_command = False
    has_assistant = False
    last_timestamp = None
    last_assistant_msg = ""
    last_conversational_role = None
    has_any_line = False

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for raw_line in f:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue

                msg = json.loads(raw_line)
                has_any_line = True

                # Extract session_id and cwd (first occurrence of each)
                if not session_id and "sessionId" in msg:
                    session_id = msg["sessionId"]
                if not project_dir and "cwd" in msg:
                    project_dir = msg["cwd"]

                # custom-title from /rename always wins
                if msg.get("type") == "custom-title":
                    raw_custom = msg.get("customTitle", "").strip()
                    if raw_custom:
                        title = _truncate(raw_custom, 40)

                # ai-title (first one wins, unless custom-title overrides)
                if not title and msg.get("type") == "ai-title":
                    raw_title = msg.get("message", {}).get("content", "").strip()
                    if raw_title:
                        title = _truncate(raw_title, 40)

                message = msg.get("message", {})
                role = message.get("role")
                content = message.get("content", "")

                # Clear session detection: look for /clear command tag
                if isinstance(content, str) and "<command-name>/clear</command-name>" in content:
                    has_clear_command = True

                if role == "assistant":
                    has_assistant = True
                    # Track last assistant message for preview
                    text = _extract_text_from_content(content)
                    if text:
                        last_assistant_msg = _truncate(text.split("\n")[0], 70)

                if role == "user":
                    # Track first user message as title fallback
                    if first_user_text is None:
                        text = _extract_text_from_content(content)
                        if text:
                            first_user_text = _truncate(text.split("\n")[0], 40)

                # Track last conversational role for status
                if role in ("user", "assistant"):
                    last_conversational_role = role

                # Track last timestamp (keep overwriting — last one wins)
                if "timestamp" in msg:
                    try:
                        ts_str = msg["timestamp"]
                        # Python < 3.11 doesn't support 'Z' as UTC in fromisoformat;
                        # replace it with the equivalent '+00:00' offset.
                        if isinstance(ts_str, str) and ts_str.endswith("Z"):
                            ts_str = ts_str[:-1] + "+00:00"
                        last_timestamp = datetime.fromisoformat(ts_str)
                    except (ValueError, TypeError):
                        pass

    except Exception:
        return None

    if not has_any_line:
        return None

    # /clear-spawned sessions are artifacts, not pending conversations
    if has_clear_command and not has_assistant:
        return None

    if not session_id:
        return None

    # Extract project name from filepath
    # Path format: ~/.claude/projects/{project}/{sessionId}.jsonl
    relative_parts = filepath.relative_to(Path.home() / ".claude" / "projects").parts
    if len(relative_parts) >= 2:
        slug = relative_parts[0]
        project_name = slug.rsplit("--", 1)[-1] if "--" in slug else slug
    else:
        project_name = "-"

    # Title: ai-title > first user message > fallback
    if not title:
        title = first_user_text or "[Untitled]"

    if not last_timestamp:
        last_timestamp = datetime.now()

    # Status based on last conversational role
    status = "in progress" if last_conversational_role == "user" else "ready"

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
