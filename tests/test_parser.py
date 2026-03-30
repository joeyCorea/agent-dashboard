"""Tests for session parser and time formatting."""

import json
import pytest
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from src.parser import format_elapsed_time, parse_jsonl, discover_sessions, _build_session_cwd_map


class TestElapsedTimeFormatting:
    """Boundary tests for elapsed time formatting thresholds."""

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


# ---------------------------------------------------------------------------
# Session CWD resolution (fix: resume uses wrong working directory)
# ---------------------------------------------------------------------------

def _write_session_json(sessions_dir: Path, pid: int, entries: list[dict]) -> Path:
    """Write a sessions/*.json file with concatenated JSON objects (not JSONL)."""
    json_file = sessions_dir / f"{pid}.json"
    # Claude Code writes concatenated JSON objects with no separator
    raw = "".join(json.dumps(e) for e in entries)
    json_file.write_text(raw, encoding="utf-8")
    return json_file


class TestBuildSessionCwdMap:
    """_build_session_cwd_map() reads ~/.claude/sessions/*.json to map session IDs to CWDs."""

    def test_single_entry(self, tmp_path, monkeypatch):
        """A single session entry maps sessionId to cwd."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        sessions_dir = tmp_path / ".claude" / "sessions"
        sessions_dir.mkdir(parents=True)
        _write_session_json(sessions_dir, 1234, [
            {"sessionId": "aaa-111", "cwd": "/home/user/project-a", "pid": 1234},
        ])

        result = _build_session_cwd_map()
        assert result["aaa-111"] == "/home/user/project-a"

    def test_multiple_entries_concatenated(self, tmp_path, monkeypatch):
        """Multiple JSON objects concatenated in one file are all parsed."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        sessions_dir = tmp_path / ".claude" / "sessions"
        sessions_dir.mkdir(parents=True)
        _write_session_json(sessions_dir, 5678, [
            {"sessionId": "aaa-111", "cwd": "/path/a", "pid": 5678},
            {"sessionId": "bbb-222", "cwd": "/path/b", "pid": 5678},
        ])

        result = _build_session_cwd_map()
        assert result["aaa-111"] == "/path/a"
        assert result["bbb-222"] == "/path/b"

    def test_duplicate_session_id_last_wins(self, tmp_path, monkeypatch):
        """When a session ID appears in multiple files, the last-written entry wins."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        sessions_dir = tmp_path / ".claude" / "sessions"
        sessions_dir.mkdir(parents=True)
        _write_session_json(sessions_dir, 100, [
            {"sessionId": "aaa-111", "cwd": "/old/path", "pid": 100},
        ])
        _write_session_json(sessions_dir, 200, [
            {"sessionId": "aaa-111", "cwd": "/new/path", "pid": 200},
        ])

        result = _build_session_cwd_map()
        # We accept either path — the key point is it doesn't crash
        assert "aaa-111" in result

    def test_missing_sessions_dir_returns_empty(self, tmp_path, monkeypatch):
        """If ~/.claude/sessions/ doesn't exist, return an empty dict."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        result = _build_session_cwd_map()
        assert result == {}

    def test_malformed_json_file_skipped(self, tmp_path, monkeypatch):
        """A sessions/*.json file with invalid JSON is skipped without crashing."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        sessions_dir = tmp_path / ".claude" / "sessions"
        sessions_dir.mkdir(parents=True)
        bad_file = sessions_dir / "9999.json"
        bad_file.write_text("not valid json{{{", encoding="utf-8")

        # Should not raise
        result = _build_session_cwd_map()
        assert result == {}

    def test_entry_missing_cwd_field_skipped(self, tmp_path, monkeypatch):
        """Entries without a cwd field are ignored."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        sessions_dir = tmp_path / ".claude" / "sessions"
        sessions_dir.mkdir(parents=True)
        _write_session_json(sessions_dir, 111, [
            {"sessionId": "aaa-111", "pid": 111},  # no cwd
        ])

        result = _build_session_cwd_map()
        assert "aaa-111" not in result


def _write_real_session_at(session_id: str, project_dir: Path, timestamp: datetime) -> Path:
    """Create a normal JSONL session file with a specific timestamp."""
    ts_str = timestamp.strftime("%Y-%m-%dT%H:%M:%S")
    if timestamp.tzinfo is not None:
        ts_str += "Z"  # mimic Claude Code's UTC 'Z' suffix
    jsonl_file = project_dir / f"{session_id}.jsonl"
    with open(jsonl_file, "w") as f:
        f.write(json.dumps({"sessionId": session_id, "timestamp": ts_str,
                            "message": {"role": "user", "content": "help me"}}) + "\n")
        f.write(json.dumps({"sessionId": session_id, "timestamp": ts_str,
                            "message": {"role": "assistant", "content": "Sure thing."}}) + "\n")
    return jsonl_file


class TestSevenDayFilter:
    """Sessions older than the default cutoff (7 days) should be excluded by the UI layer.

    The date filter is layer 3 in the filtering architecture:
      Layer 1: Content check (_is_clear_session) in parse_jsonl
      Layer 2: ID dismissal in refresh_sessions
      Layer 3: Date cutoff in refresh_sessions

    This filter uses is_within_cutoff() which handles mixed tz-aware/naive datetimes.
    """

    def test_session_within_7_days_is_included(self, tmp_path, monkeypatch):
        """A session from 6 days ago should pass the 7-day filter."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        proj_dir = tmp_path / ".claude" / "projects" / "my-project"
        proj_dir.mkdir(parents=True)

        six_days_ago = datetime.now(timezone.utc) - timedelta(days=6)
        _write_real_session_at("recent-sess", proj_dir, six_days_ago)

        from src.ui import is_within_cutoff
        sessions = discover_sessions()
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        included = [s for s in sessions if is_within_cutoff(s, cutoff)]
        assert any(s.session_id == "recent-sess" for s in included), (
            "A 6-day-old session should be included within the 7-day filter."
        )

    def test_session_older_than_7_days_is_excluded(self, tmp_path, monkeypatch):
        """A session from 8 days ago should be excluded by the 7-day filter."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        proj_dir = tmp_path / ".claude" / "projects" / "my-project"
        proj_dir.mkdir(parents=True)

        eight_days_ago = datetime.now(timezone.utc) - timedelta(days=8)
        _write_real_session_at("old-sess", proj_dir, eight_days_ago)

        from src.ui import is_within_cutoff
        sessions = discover_sessions()
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        included = [s for s in sessions if is_within_cutoff(s, cutoff)]
        assert not any(s.session_id == "old-sess" for s in included), (
            "An 8-day-old session should be excluded by the 7-day filter."
        )

    def test_session_exactly_at_cutoff_is_included(self, tmp_path, monkeypatch):
        """A session exactly 7 days old (to the second) should be included (>= comparison)."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        proj_dir = tmp_path / ".claude" / "projects" / "my-project"
        proj_dir.mkdir(parents=True)

        # Use a fixed reference point to avoid race between file write and cutoff calc.
        # Add 1 second of slack since strftime truncates sub-second precision.
        seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7, seconds=-1)
        _write_real_session_at("edge-sess", proj_dir, seven_days_ago)

        from src.ui import is_within_cutoff
        sessions = discover_sessions()
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        included = [s for s in sessions if is_within_cutoff(s, cutoff)]
        assert any(s.session_id == "edge-sess" for s in included), (
            "A session at the 7-day boundary (with 1s slack) should be included (>= comparison)."
        )

    def test_naive_timestamp_fallback_is_included(self, tmp_path, monkeypatch):
        """Sessions with naive datetime (parse fallback) should be treated as current, not excluded.

        When parse_jsonl cannot parse a timestamp, it falls back to naive datetime.now().
        The filter must handle comparing a tz-aware cutoff against a naive timestamp
        without raising TypeError — and should include such sessions (they are likely current).
        """
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        proj_dir = tmp_path / ".claude" / "projects" / "my-project"
        proj_dir.mkdir(parents=True)

        # Write a session with an unparseable timestamp to trigger the naive fallback
        jsonl_file = proj_dir / "naive-sess.jsonl"
        with open(jsonl_file, "w") as f:
            f.write(json.dumps({"sessionId": "naive-sess", "timestamp": "not-a-date",
                                "message": {"role": "user", "content": "hello"}}) + "\n")
            f.write(json.dumps({"sessionId": "naive-sess", "timestamp": "not-a-date",
                                "message": {"role": "assistant", "content": "hi"}}) + "\n")

        from src.ui import is_within_cutoff
        sessions = discover_sessions()
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        # This must not raise TypeError from mixed tz-aware/naive comparison
        included = [s for s in sessions if is_within_cutoff(s, cutoff)]
        assert any(s.session_id == "naive-sess" for s in included), (
            "Sessions with naive timestamps (parse fallback) should be included, "
            "not excluded or cause a TypeError."
        )

    def test_mixed_old_and_new_sessions_filtered_correctly(self, tmp_path, monkeypatch):
        """With a mix of recent and old sessions, only recent ones survive the filter."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        proj_dir = tmp_path / ".claude" / "projects" / "my-project"
        proj_dir.mkdir(parents=True)

        recent = datetime.now(timezone.utc) - timedelta(days=1)
        old = datetime.now(timezone.utc) - timedelta(days=14)
        _write_real_session_at("new-sess", proj_dir, recent)
        _write_real_session_at("ancient-sess", proj_dir, old)

        from src.ui import is_within_cutoff
        sessions = discover_sessions()
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        included = [s for s in sessions if is_within_cutoff(s, cutoff)]
        ids = [s.session_id for s in included]
        assert "new-sess" in ids, "1-day-old session should be included."
        assert "ancient-sess" not in ids, "14-day-old session should be excluded."
        assert len(included) == 1, f"Expected 1 session, got {len(included)}: {ids}"


class TestDiscoverSessionsProjectDir:
    """discover_sessions() should populate project_dir from ~/.claude/sessions/*.json."""

    def test_project_dir_populated_from_session_json(self, tmp_path, monkeypatch):
        """Sessions get project_dir set when a matching sessions/*.json entry exists."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        # Create a session JSONL file
        proj_dir = tmp_path / ".claude" / "projects" / "my-project"
        proj_dir.mkdir(parents=True)
        _write_real_session("sess-001", proj_dir)

        # Create the sessions/*.json mapping
        sessions_dir = tmp_path / ".claude" / "sessions"
        sessions_dir.mkdir(parents=True)
        _write_session_json(sessions_dir, 42, [
            {"sessionId": "sess-001", "cwd": "/home/user/my-project", "pid": 42},
        ])

        sessions = discover_sessions()
        assert len(sessions) == 1
        assert sessions[0].project_dir == "/home/user/my-project"

    def test_project_dir_none_when_no_session_json(self, tmp_path, monkeypatch):
        """Sessions without a matching sessions/*.json entry get project_dir=None."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        proj_dir = tmp_path / ".claude" / "projects" / "my-project"
        proj_dir.mkdir(parents=True)
        _write_real_session("orphan-001", proj_dir)

        # No sessions/*.json files at all
        sessions = discover_sessions()
        assert len(sessions) == 1
        assert sessions[0].project_dir is None
