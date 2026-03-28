"""Tests for session parser and time formatting."""

import json
import pytest
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from src.parser import format_elapsed_time, parse_jsonl, discover_sessions


class TestElapsedTimeFormatting:
    """Test suite for elapsed time formatting."""

    def test_elapsed_time_just_now(self):
        """Times less than 1 minute old should show 'just now'."""
        timestamp = datetime.now() - timedelta(seconds=30)
        result = format_elapsed_time(timestamp)
        assert result == "just now", f"Expected 'just now', got '{result}'"

    def test_elapsed_time_minutes(self):
        """Times between 1-59 minutes old should show minutes."""
        timestamp = datetime.now() - timedelta(minutes=30)
        result = format_elapsed_time(timestamp)
        assert result == "30m ago", f"Expected '30m ago', got '{result}'"

    def test_elapsed_time_one_minute(self):
        """Time exactly 1 minute old should show '1m ago'."""
        timestamp = datetime.now() - timedelta(minutes=1)
        result = format_elapsed_time(timestamp)
        assert result == "1m ago", f"Expected '1m ago', got '{result}'"

    def test_elapsed_time_hours(self):
        """Times between 1-23 hours old should show hours."""
        timestamp = datetime.now() - timedelta(hours=2)
        result = format_elapsed_time(timestamp)
        assert result == "2h ago", f"Expected '2h ago', got '{result}'"

    def test_elapsed_time_one_hour(self):
        """Time exactly 1 hour old should show '1h ago'."""
        timestamp = datetime.now() - timedelta(hours=1)
        result = format_elapsed_time(timestamp)
        assert result == "1h ago", f"Expected '1h ago', got '{result}'"

    def test_elapsed_time_days(self):
        """Times between 1-6 days old should show days."""
        timestamp = datetime.now() - timedelta(days=3)
        result = format_elapsed_time(timestamp)
        assert result == "3d ago", f"Expected '3d ago', got '{result}'"

    def test_elapsed_time_one_day(self):
        """Time exactly 1 day old should show '1d ago'."""
        timestamp = datetime.now() - timedelta(days=1)
        result = format_elapsed_time(timestamp)
        assert result == "1d ago", f"Expected '1d ago', got '{result}'"

    def test_elapsed_time_weeks(self):
        """Times 7+ days old should show weeks."""
        timestamp = datetime.now() - timedelta(weeks=2)
        result = format_elapsed_time(timestamp)
        assert result == "2w ago", f"Expected '2w ago', got '{result}'"

    def test_elapsed_time_one_week(self):
        """Time exactly 1 week old should show '1w ago'."""
        timestamp = datetime.now() - timedelta(weeks=1)
        result = format_elapsed_time(timestamp)
        assert result == "1w ago", f"Expected '1w ago', got '{result}'"

    def test_elapsed_time_boundary_59_seconds(self):
        """At 59 seconds, should still show 'just now'."""
        timestamp = datetime.now() - timedelta(seconds=59)
        result = format_elapsed_time(timestamp)
        assert result == "just now", f"Expected 'just now', got '{result}'"

    def test_elapsed_time_boundary_60_seconds(self):
        """At 60 seconds (1 minute), should show '1m ago'."""
        timestamp = datetime.now() - timedelta(seconds=60)
        result = format_elapsed_time(timestamp)
        assert result == "1m ago", f"Expected '1m ago', got '{result}'"

    def test_elapsed_time_boundary_hour(self):
        """At 59 minutes, should show minutes, not hours."""
        timestamp = datetime.now() - timedelta(minutes=59)
        result = format_elapsed_time(timestamp)
        assert result == "59m ago", f"Expected '59m ago', got '{result}'"

    def test_elapsed_time_boundary_day(self):
        """At 23 hours 59 minutes, should show hours, not days."""
        timestamp = datetime.now() - timedelta(hours=23, minutes=59)
        result = format_elapsed_time(timestamp)
        assert "h ago" in result, f"Expected hours format, got '{result}'"

    def test_elapsed_time_boundary_week(self):
        """At 6 days 23 hours, should show days, not weeks."""
        timestamp = datetime.now() - timedelta(days=6, hours=23)
        result = format_elapsed_time(timestamp)
        assert "d ago" in result, f"Expected days format, got '{result}'"


class TestTimestampParsing:
    """Test that session timestamps with 'Z' suffix are parsed correctly.

    Claude Code session files use ISO 8601 timestamps with a 'Z' suffix
    (e.g. '2026-03-28T07:20:53.869Z'). Python 3.10's datetime.fromisoformat()
    does not support the 'Z' suffix — only '+00:00' — so without a fix the
    parser silently skips all timestamps and falls back to datetime.now(),
    causing every session to display 'just now'.
    """

    def _make_session_file(self, timestamp_str: str, home_dir: Path) -> Path:
        """Create a JSONL session file under <home>/.claude/projects/my-project/."""
        projects_dir = home_dir / ".claude" / "projects" / "my-project"
        projects_dir.mkdir(parents=True)
        jsonl_file = projects_dir / "abc123.jsonl"
        lines = [
            {
                "sessionId": "abc123",
                "timestamp": timestamp_str,
                "message": {"role": "user", "content": "hello"},
            },
            {
                "sessionId": "abc123",
                "timestamp": timestamp_str,
                "message": {"role": "assistant", "content": "hi there"},
            },
        ]
        with open(jsonl_file, "w") as f:
            for line in lines:
                f.write(json.dumps(line) + "\n")
        return jsonl_file

    def test_parse_jsonl_with_z_suffix_two_hours_ago(self, tmp_path, monkeypatch):
        """parse_jsonl should correctly extract a timestamp with a 'Z' suffix.

        Before the fix, fromisoformat() threw ValueError on 'Z' suffix in Python
        3.10, so last_timestamp fell back to datetime.now() and elapsed time
        was always reported as 'just now'.
        """
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        two_hours_ago = datetime.now(timezone.utc) - timedelta(hours=2)
        ts_str = two_hours_ago.strftime("%Y-%m-%dT%H:%M:%SZ")

        jsonl_file = self._make_session_file(ts_str, tmp_path)
        session = parse_jsonl(jsonl_file)

        assert session is not None, "parse_jsonl should return a Session"
        elapsed = format_elapsed_time(session.last_message_timestamp)
        assert elapsed == "2h ago", (
            f"Expected '2h ago' but got '{elapsed}'. "
            "The 'Z' suffix in ISO 8601 timestamps is not being parsed correctly — "
            "the parser may be falling back to datetime.now()."
        )

    def test_parse_jsonl_with_z_suffix_one_day_ago_not_just_now(self, tmp_path, monkeypatch):
        """A session from 1 day ago with a 'Z' timestamp must NOT show 'just now'."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        one_day_ago = datetime.now(timezone.utc) - timedelta(days=1)
        ts_str = one_day_ago.strftime("%Y-%m-%dT%H:%M:%SZ")

        jsonl_file = self._make_session_file(ts_str, tmp_path)
        session = parse_jsonl(jsonl_file)

        assert session is not None
        elapsed = format_elapsed_time(session.last_message_timestamp)
        assert elapsed != "just now", (
            f"A 1-day-old session reported 'just now' — the 'Z' suffix timestamp "
            f"was likely not parsed and fell back to datetime.now()."
        )
        assert "d ago" in elapsed or "h ago" in elapsed, (
            f"Expected a relative time like '1d ago', got '{elapsed}'"
        )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_TS = "2026-03-28T07:20:53.867Z"
_CLEAR_CONTENT = (
    "<command-name>/clear</command-name>\n"
    "            <command-message>clear</command-message>\n"
    "            <command-args></command-args>"
)


def _write_real_session(session_id: str, project_dir: Path) -> Path:
    """Create a normal JSONL session file with at least one assistant message."""
    jsonl_file = project_dir / f"{session_id}.jsonl"
    with open(jsonl_file, "w") as f:
        f.write(json.dumps({"sessionId": session_id, "timestamp": _TS,
                            "message": {"role": "user", "content": "help me refactor"}}) + "\n")
        f.write(json.dumps({"sessionId": session_id, "timestamp": _TS,
                            "message": {"role": "assistant", "content": "Sure, here is how."}}) + "\n")
    return jsonl_file


def _write_clear_session(session_id: str, project_dir: Path) -> Path:
    """Create a JSONL file that matches what Claude Code writes when /clear is used.

    Real examples observed on disk contain exactly four entries:
      1. file-history-snapshot  (no sessionId field)
      2. user meta message      (local-command-caveat, isMeta=True)
      3. user message           (the /clear slash command content)
      4. system message         (local_command result, empty stdout)

    No assistant message is ever written to these files.
    """
    jsonl_file = project_dir / f"{session_id}.jsonl"
    with open(jsonl_file, "w") as f:
        f.write(json.dumps({"type": "file-history-snapshot", "messageId": "snap-01",
                            "isSnapshotUpdate": False}) + "\n")
        f.write(json.dumps({"sessionId": session_id, "type": "user", "isMeta": True,
                            "message": {"role": "user",
                                        "content": "<local-command-caveat>...</local-command-caveat>"},
                            "timestamp": _TS}) + "\n")
        f.write(json.dumps({"sessionId": session_id, "type": "user",
                            "message": {"role": "user", "content": _CLEAR_CONTENT},
                            "timestamp": _TS}) + "\n")
        f.write(json.dumps({"sessionId": session_id, "type": "system",
                            "subtype": "local_command",
                            "content": "<local-command-stdout></local-command-stdout>",
                            "timestamp": _TS}) + "\n")
    return jsonl_file


class TestClearSessionFiltering:
    """/clear creates a new JSONL file — these artifacts must be hidden from the TUI.

    When a user types /clear in Claude Code, a brand-new session file is written:
      - file-history-snapshot entry
      - The /clear command logged as a user message
      - A system entry recording the (empty) stdout result

    No assistant message is ever present.  These sessions show up as "(no messages)"
    in the TUI.  discover_sessions() must exclude them.
    """

    def test_clear_session_excluded_from_discover_sessions(self, tmp_path, monkeypatch):
        """/clear-spawned sessions must not appear in discover_sessions() results."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        proj_dir = tmp_path / ".claude" / "projects" / "my-project"
        proj_dir.mkdir(parents=True)
        _write_clear_session("clear-abc", proj_dir)

        sessions = discover_sessions()
        assert not any(s.session_id == "clear-abc" for s in sessions), (
            "A /clear-spawned session (no assistant messages, /clear in content) "
            "appeared in discover_sessions() — it should be filtered out."
        )

    def test_real_session_not_filtered_by_clear_logic(self, tmp_path, monkeypatch):
        """Sessions with real assistant responses must still appear."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        proj_dir = tmp_path / ".claude" / "projects" / "my-project"
        proj_dir.mkdir(parents=True)
        _write_real_session("real-session", proj_dir)

        sessions = discover_sessions()
        assert any(s.session_id == "real-session" for s in sessions), (
            "A session with an assistant message was incorrectly filtered out."
        )

    def test_clear_session_not_returned_alongside_real_session(self, tmp_path, monkeypatch):
        """Only clear-spawned sessions are filtered; real sessions remain."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        proj_dir = tmp_path / ".claude" / "projects" / "my-project"
        proj_dir.mkdir(parents=True)
        _write_real_session("real-session", proj_dir)
        _write_clear_session("clear-session", proj_dir)

        sessions = discover_sessions()
        session_ids = [s.session_id for s in sessions]
        assert "real-session" in session_ids, "Real session should appear in TUI."
        assert "clear-session" not in session_ids, "/clear session should be hidden."
        assert len(sessions) == 1, (
            f"Expected exactly 1 session, got {len(sessions)}: {session_ids}"
        )


class TestSubagentFileFiltering:
    """JSONL files inside subagent subdirectories must not appear as TUI sessions.

    Claude Code writes subagent conversation logs under:
      ~/.claude/projects/{project}/{session-uuid}/subagents/{agent-id}.jsonl

    The discover_sessions() glob ('**/*.jsonl') recurses into these directories.
    Subagent files must be excluded — only top-level {project}/{session}.jsonl
    files are real user sessions.
    """

    def test_subagent_jsonl_excluded_from_discover_sessions(self, tmp_path, monkeypatch):
        """JSONL files nested inside subagents/ directories must not appear."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        proj_dir = tmp_path / ".claude" / "projects" / "my-project"
        subagents_dir = proj_dir / "parent-session" / "subagents"
        subagents_dir.mkdir(parents=True)

        _write_real_session("parent-session", proj_dir)
        _write_real_session("agent-12345", subagents_dir)

        sessions = discover_sessions()
        session_ids = [s.session_id for s in sessions]
        assert "parent-session" in session_ids, "Parent session should appear."
        assert "agent-12345" not in session_ids, (
            "Subagent session file was incorrectly surfaced as a TUI session."
        )

    def test_only_top_level_sessions_returned_when_subagents_present(self, tmp_path, monkeypatch):
        """With a subagent sibling, only the main session appears (count == 1)."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        proj_dir = tmp_path / ".claude" / "projects" / "my-project"
        subagents_dir = proj_dir / "the-session" / "subagents"
        subagents_dir.mkdir(parents=True)

        _write_real_session("the-session", proj_dir)
        _write_real_session("agent-abc", subagents_dir)

        sessions = discover_sessions()
        assert len(sessions) == 1, (
            f"Expected 1 session but got {len(sessions)}: "
            f"{[s.session_id for s in sessions]}"
        )
        assert sessions[0].session_id == "the-session"
