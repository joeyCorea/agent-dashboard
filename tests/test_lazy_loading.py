"""Tests for lazy loading of session message history (Tier 1 optimization).

The Session dataclass should store a filepath instead of full_message_history.
Message history is loaded on demand via load_message_history().
"""

import json
import pytest
from datetime import datetime, timezone
from pathlib import Path

from src.parser import Session, parse_jsonl, load_message_history


_TS = "2026-03-28T07:20:53.867Z"


def _write_session_file(session_id: str, project_dir: Path, messages: list[dict] = None) -> Path:
    """Create a JSONL session file with given messages."""
    if messages is None:
        messages = [
            {"sessionId": session_id, "timestamp": _TS,
             "message": {"role": "user", "content": "help me refactor"}},
            {"sessionId": session_id, "timestamp": _TS,
             "message": {"role": "assistant", "content": "Sure, here is how."}},
        ]
    jsonl_file = project_dir / f"{session_id}.jsonl"
    with open(jsonl_file, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")
    return jsonl_file


class TestSessionFilepathField:
    """Session dataclass should have a filepath field instead of full_message_history."""

    def test_session_has_filepath_field(self):
        """Session should have a filepath field of type Path."""
        import dataclasses
        field_names = [f.name for f in dataclasses.fields(Session)]
        assert "filepath" in field_names, (
            "Session dataclass must have a 'filepath' field for lazy loading."
        )

    def test_session_no_full_message_history_field(self):
        """Session should NOT have a full_message_history field (replaced by filepath)."""
        import dataclasses
        field_names = [f.name for f in dataclasses.fields(Session)]
        assert "full_message_history" not in field_names, (
            "Session should no longer have 'full_message_history' — "
            "replaced by 'filepath' for lazy loading."
        )


class TestParseJsonlFilepath:
    """parse_jsonl() should populate the filepath field on the returned Session."""

    def test_parse_jsonl_sets_filepath(self, tmp_path, monkeypatch):
        """parse_jsonl should set session.filepath to the source JSONL file path."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        proj_dir = tmp_path / ".claude" / "projects" / "my-project"
        proj_dir.mkdir(parents=True)
        jsonl_file = _write_session_file("abc123", proj_dir)

        session = parse_jsonl(jsonl_file)
        assert session is not None
        assert session.filepath == jsonl_file, (
            f"Expected filepath={jsonl_file}, got {session.filepath}"
        )


class TestLoadMessageHistory:
    """load_message_history() reads and returns parsed JSONL lines on demand."""

    def test_load_returns_all_messages(self, tmp_path):
        """load_message_history should return all parsed message dicts from the file."""
        proj_dir = tmp_path / "project"
        proj_dir.mkdir()
        messages = [
            {"sessionId": "s1", "timestamp": _TS,
             "message": {"role": "user", "content": "question 1"}},
            {"sessionId": "s1", "timestamp": _TS,
             "message": {"role": "assistant", "content": "answer 1"}},
            {"sessionId": "s1", "timestamp": _TS,
             "message": {"role": "user", "content": "question 2"}},
            {"sessionId": "s1", "timestamp": _TS,
             "message": {"role": "assistant", "content": "answer 2"}},
        ]
        filepath = _write_session_file("s1", proj_dir, messages)

        result = load_message_history(filepath)
        assert len(result) == 4, f"Expected 4 messages, got {len(result)}"
        assert result[0]["message"]["content"] == "question 1"
        assert result[3]["message"]["content"] == "answer 2"

    def test_load_returns_empty_for_missing_file(self, tmp_path):
        """load_message_history should return empty list for a nonexistent file."""
        missing = tmp_path / "does-not-exist.jsonl"
        result = load_message_history(missing)
        assert result == [], f"Expected empty list for missing file, got {result}"

    def test_load_skips_blank_lines(self, tmp_path):
        """load_message_history should skip blank lines in the JSONL file."""
        proj_dir = tmp_path / "project"
        proj_dir.mkdir()
        filepath = proj_dir / "s1.jsonl"
        with open(filepath, "w") as f:
            f.write(json.dumps({"sessionId": "s1", "message": {"role": "user", "content": "hi"}}) + "\n")
            f.write("\n")  # blank line
            f.write(json.dumps({"sessionId": "s1", "message": {"role": "assistant", "content": "hello"}}) + "\n")

        result = load_message_history(filepath)
        assert len(result) == 2, f"Expected 2 messages (blank skipped), got {len(result)}"

    def test_load_handles_malformed_json_gracefully(self, tmp_path):
        """load_message_history should return empty list if file contains invalid JSON."""
        proj_dir = tmp_path / "project"
        proj_dir.mkdir()
        filepath = proj_dir / "bad.jsonl"
        filepath.write_text("not valid json\n", encoding="utf-8")

        result = load_message_history(filepath)
        assert result == [], f"Expected empty list for malformed file, got {result}"
