"""
Dismissal log management.

Handles reading and writing to ~/.claude/sessions.log
"""

from pathlib import Path


def _get_dismissal_log_path() -> Path:
    """Get the path to the dismissal log."""
    return Path.home() / ".claude" / "session.log"


def read_dismissed_ids() -> set[str]:
    """
    Read all dismissed session IDs from the dismissal log.

    Returns:
        Set of dismissed session IDs (empty set if log doesn't exist)
    """
    log_path = _get_dismissal_log_path()

    if not log_path.exists():
        return set()

    dismissed = set()
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                session_id = line.strip()
                if session_id:
                    dismissed.add(session_id)
    except Exception as e:
        print(f"Warning: Failed to read dismissal log: {e}")

    return dismissed


def dismiss_session(session_id: str) -> None:
    """
    Append a session ID to the dismissal log.

    Args:
        session_id: The session ID to dismiss
    """
    log_path = _get_dismissal_log_path()

    # Ensure parent directory exists
    log_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{session_id}\n")
    except Exception as e:
        print(f"Error: Failed to dismiss session: {e}")


def restore_session(session_id: str) -> None:
    """
    Remove a session ID from the dismissal log, restoring it to the active list.

    Args:
        session_id: The session ID to restore
    """
    log_path = _get_dismissal_log_path()

    if not log_path.exists():
        return

    try:
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        remaining = [line for line in lines if line.strip() != session_id]

        with open(log_path, "w", encoding="utf-8") as f:
            f.writelines(remaining)
    except Exception as e:
        print(f"Error: Failed to restore session: {e}")
