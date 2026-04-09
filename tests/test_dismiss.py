"""Tests for dismissal log reading and session filtering.

The endSession hook writes dismissed session IDs to ~/.claude/session.log.
read_dismissed_ids() must read from that same file so that hook-dismissed
sessions are excluded from the TUI.
"""

import json
from pathlib import Path

from src.dismiss import read_dismissed_ids, dismiss_session, restore_session
from src.parser import discover_sessions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TS = "2026-03-28T07:20:53.867Z"


def _write_real_session(session_id: str, project_dir: Path) -> Path:
    """Create a normal JSONL session file with at least one assistant message."""
    jsonl_file = project_dir / f"{session_id}.jsonl"
    with open(jsonl_file, "w") as f:
        f.write(json.dumps({"sessionId": session_id, "timestamp": _TS,
                            "message": {"role": "user", "content": "help me refactor"}}) + "\n")
        f.write(json.dumps({"sessionId": session_id, "timestamp": _TS,
                            "message": {"role": "assistant", "content": "Sure, here is how."}}) + "\n")
    return jsonl_file


# ---------------------------------------------------------------------------
# Tests — read_dismissed_ids reads from the correct file
# ---------------------------------------------------------------------------

class TestReadDismissedIds:
    """read_dismissed_ids() must read from session.log (singular), the file
    that the endSession hook writes to."""

    def test_reads_ids_from_session_log(self, tmp_path, monkeypatch):
        """IDs written to session.log by the hook must appear in the returned set."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        session_log = tmp_path / ".claude" / "session.log"
        session_log.parent.mkdir(parents=True)
        session_log.write_text("406c34e6-ff81-4c80-9841-19069e476f0b\n")

        dismissed = read_dismissed_ids()
        assert "406c34e6-ff81-4c80-9841-19069e476f0b" in dismissed, (
            "read_dismissed_ids() did not find the UUID in session.log — "
            "it may be reading from the wrong filename."
        )

    def test_dismiss_session_writes_to_same_file_hook_uses(self, tmp_path, monkeypatch):
        """dismiss_session() (TUI 'd' key) must write to the same file that
        read_dismissed_ids() reads, so both hook and TUI dismissals land in
        one place."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        (tmp_path / ".claude").mkdir(parents=True)

        dismiss_session("test-uuid-abc")
        dismissed = read_dismissed_ids()
        assert "test-uuid-abc" in dismissed, (
            "dismiss_session() wrote to a different file than read_dismissed_ids() reads."
        )


# ---------------------------------------------------------------------------
# Tests — restore_session removes IDs from the dismissal log
# ---------------------------------------------------------------------------

class TestRestoreSession:
    """restore_session() must remove the given session ID from session.log."""

    def test_restore_removes_id_from_log(self, tmp_path, monkeypatch):
        """After restoring, the session ID must no longer appear in dismissed set."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        (tmp_path / ".claude").mkdir(parents=True)

        dismiss_session("uuid-to-restore")
        assert "uuid-to-restore" in read_dismissed_ids()

        restore_session("uuid-to-restore")
        assert "uuid-to-restore" not in read_dismissed_ids(), (
            "restore_session() did not remove the ID from the dismissal log."
        )

    def test_restore_preserves_other_ids(self, tmp_path, monkeypatch):
        """Restoring one session must not remove other dismissed sessions."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        (tmp_path / ".claude").mkdir(parents=True)

        dismiss_session("keep-dismissed")
        dismiss_session("to-restore")
        dismiss_session("also-keep")

        restore_session("to-restore")
        remaining = read_dismissed_ids()
        assert "keep-dismissed" in remaining
        assert "also-keep" in remaining
        assert "to-restore" not in remaining

    def test_restore_nonexistent_id_is_noop(self, tmp_path, monkeypatch):
        """Restoring an ID that isn't in the log should not error or corrupt the file."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        (tmp_path / ".claude").mkdir(parents=True)

        dismiss_session("existing-id")
        restore_session("nonexistent-id")
        assert "existing-id" in read_dismissed_ids()

    def test_restore_when_no_log_file_is_noop(self, tmp_path, monkeypatch):
        """Restoring when no session.log exists should not error."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        (tmp_path / ".claude").mkdir(parents=True)
        # No session.log created — should not raise
        restore_session("any-id")


# ---------------------------------------------------------------------------
# Tests — end-to-end: hook-dismissed session excluded from TUI list
# ---------------------------------------------------------------------------

class TestHookDismissedSessionFiltering:
    """A session whose ID the endSession hook wrote to session.log must not
    appear in the active session list that the TUI displays."""

    def test_hook_dismissed_session_excluded(self, tmp_path, monkeypatch):
        """Session in session.log must be filtered out of discover + dismiss pipeline."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        session_id = "406c34e6-ff81-4c80-9841-19069e476f0b"
        proj_dir = tmp_path / ".claude" / "projects" / "my-project"
        proj_dir.mkdir(parents=True)
        _write_real_session(session_id, proj_dir)

        # Simulate the hook having written the UUID to session.log
        session_log = tmp_path / ".claude" / "session.log"
        session_log.write_text(f"{session_id}\n")

        # Reproduce the filtering logic from PendingSessionsApp.refresh_sessions()
        all_sessions = discover_sessions()
        dismissed_ids = read_dismissed_ids()
        active_sessions = [
            s for s in all_sessions if s.session_id not in dismissed_ids
        ]

        assert not any(s.session_id == session_id for s in active_sessions), (
            f"Session {session_id!r} still appears in active sessions despite "
            f"being listed in session.log. dismissed_ids={dismissed_ids}"
        )

    def test_restored_session_reappears(self, tmp_path, monkeypatch):
        """A session that was dismissed and then restored must appear in the active list."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        session_id = "406c34e6-ff81-4c80-9841-19069e476f0b"
        proj_dir = tmp_path / ".claude" / "projects" / "my-project"
        proj_dir.mkdir(parents=True)
        _write_real_session(session_id, proj_dir)

        # Dismiss the session
        dismiss_session(session_id)
        dismissed = read_dismissed_ids()
        assert session_id in dismissed

        # Restore it
        restore_session(session_id)

        all_sessions = discover_sessions()
        dismissed_ids = read_dismissed_ids()
        active_sessions = [
            s for s in all_sessions if s.session_id not in dismissed_ids
        ]

        assert any(s.session_id == session_id for s in active_sessions), (
            f"Session {session_id!r} should reappear after being restored."
        )

    def test_non_dismissed_session_still_appears(self, tmp_path, monkeypatch):
        """Sessions NOT in session.log must still appear in the active list."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        proj_dir = tmp_path / ".claude" / "projects" / "my-project"
        proj_dir.mkdir(parents=True)
        _write_real_session("active-session-123", proj_dir)

        # session.log exists but contains a DIFFERENT uuid
        session_log = tmp_path / ".claude" / "session.log"
        session_log.write_text("some-other-dismissed-uuid\n")

        all_sessions = discover_sessions()
        dismissed_ids = read_dismissed_ids()
        active_sessions = [
            s for s in all_sessions if s.session_id not in dismissed_ids
        ]

        assert any(s.session_id == "active-session-123" for s in active_sessions), (
            "An active session was incorrectly filtered out."
        )
