"""Tests for metadata cache with mtime invalidation (Tier 3 optimization).

The cache stores parsed session metadata keyed by filepath. On refresh,
only files whose mtime changed since the last cache write are re-parsed.
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from src.cache import load_cache, save_cache, CACHE_VERSION


_TS = "2026-03-28T07:20:53.867Z"


def _write_real_session(session_id: str, project_dir: Path, cwd: str = None) -> Path:
    """Create a normal JSONL session file with at least one assistant message."""
    jsonl_file = project_dir / f"{session_id}.jsonl"
    user_msg = {"sessionId": session_id, "timestamp": _TS,
                "message": {"role": "user", "content": "help me refactor"}}
    if cwd:
        user_msg["cwd"] = cwd
    with open(jsonl_file, "w") as f:
        f.write(json.dumps(user_msg) + "\n")
        f.write(json.dumps({"sessionId": session_id, "timestamp": _TS,
                            "message": {"role": "assistant", "content": "Sure, here is how."}}) + "\n")
    return jsonl_file


class TestLoadCache:
    """load_cache reads and validates the cache file."""

    def test_returns_empty_dict_when_no_cache_file(self, tmp_path):
        """Missing cache file should return empty dict, not error."""
        cache_path = tmp_path / "dashboard-cache.json"
        result = load_cache(cache_path)
        assert result == {}

    def test_returns_empty_dict_on_corrupt_json(self, tmp_path):
        """Corrupt cache file should return empty dict (full re-parse fallback)."""
        cache_path = tmp_path / "dashboard-cache.json"
        cache_path.write_text("not valid json", encoding="utf-8")
        result = load_cache(cache_path)
        assert result == {}

    def test_returns_empty_dict_on_version_mismatch(self, tmp_path):
        """Cache with wrong version should be treated as empty (forces full re-parse)."""
        cache_path = tmp_path / "dashboard-cache.json"
        cache_path.write_text(json.dumps({
            "version": CACHE_VERSION + 999,
            "sessions": {"some/file.jsonl": {"mtime": 1.0, "metadata": {}}}
        }), encoding="utf-8")
        result = load_cache(cache_path)
        assert result == {}

    def test_returns_sessions_dict_on_valid_cache(self, tmp_path):
        """Valid cache file should return the sessions dict."""
        cache_path = tmp_path / "dashboard-cache.json"
        sessions_data = {
            "some/file.jsonl": {"mtime": 123.456, "metadata": {"session_id": "abc"}}
        }
        cache_path.write_text(json.dumps({
            "version": CACHE_VERSION,
            "sessions": sessions_data,
        }), encoding="utf-8")
        result = load_cache(cache_path)
        assert result == sessions_data


class TestSaveCache:
    """save_cache writes the cache file with correct structure."""

    def test_save_creates_file_with_version(self, tmp_path):
        """save_cache should write a file with version and sessions keys."""
        cache_path = tmp_path / "dashboard-cache.json"
        sessions_data = {"file.jsonl": {"mtime": 1.0, "metadata": {"id": "x"}}}
        save_cache(cache_path, sessions_data)

        data = json.loads(cache_path.read_text(encoding="utf-8"))
        assert data["version"] == CACHE_VERSION
        assert data["sessions"] == sessions_data

    def test_save_overwrites_existing_cache(self, tmp_path):
        """save_cache should overwrite, not append to, existing cache."""
        cache_path = tmp_path / "dashboard-cache.json"
        save_cache(cache_path, {"old.jsonl": {"mtime": 1.0, "metadata": {}}})
        save_cache(cache_path, {"new.jsonl": {"mtime": 2.0, "metadata": {}}})

        data = json.loads(cache_path.read_text(encoding="utf-8"))
        assert "old.jsonl" not in data["sessions"]
        assert "new.jsonl" in data["sessions"]


class TestDiscoverSessionsWithCache:
    """discover_sessions uses cache to skip re-parsing unchanged files."""

    def test_unchanged_file_uses_cached_metadata(self, tmp_path, monkeypatch):
        """A file whose mtime matches the cache should NOT be re-parsed."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        proj_dir = tmp_path / ".claude" / "projects" / "my-project"
        proj_dir.mkdir(parents=True)
        jsonl_file = _write_real_session("cached-sess", proj_dir)

        # First call: populates cache
        from src.parser import discover_sessions
        sessions_1 = discover_sessions()
        assert any(s.session_id == "cached-sess" for s in sessions_1)

        # Overwrite file content but preserve mtime to simulate "unchanged"
        mtime = jsonl_file.stat().st_mtime
        jsonl_file.write_text("garbage that would fail parse\n", encoding="utf-8")
        import os
        os.utime(jsonl_file, (mtime, mtime))

        # Second call: should use cache, not re-parse the now-garbage file
        sessions_2 = discover_sessions()
        assert any(s.session_id == "cached-sess" for s in sessions_2), (
            "Session from cache should appear even though file content changed "
            "(mtime unchanged, so cache should be used)."
        )

    def test_modified_file_is_reparsed(self, tmp_path, monkeypatch):
        """A file whose mtime changed should be re-parsed, not use stale cache."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        proj_dir = tmp_path / ".claude" / "projects" / "my-project"
        proj_dir.mkdir(parents=True)
        jsonl_file = _write_real_session("sess-v1", proj_dir)

        from src.parser import discover_sessions
        sessions_1 = discover_sessions()
        assert any(s.session_id == "sess-v1" for s in sessions_1)

        # Rewrite file with new content AND new mtime
        time.sleep(0.05)  # ensure mtime differs
        with open(jsonl_file, "w") as f:
            f.write(json.dumps({"sessionId": "sess-v2", "timestamp": _TS,
                                "message": {"role": "user", "content": "new"}}) + "\n")
            f.write(json.dumps({"sessionId": "sess-v2", "timestamp": _TS,
                                "message": {"role": "assistant", "content": "updated"}}) + "\n")

        sessions_2 = discover_sessions()
        ids = [s.session_id for s in sessions_2]
        assert "sess-v2" in ids, "Modified file should be re-parsed with new session_id."
        assert "sess-v1" not in ids, "Stale cached session_id should not appear."

    def test_deleted_file_removed_from_results(self, tmp_path, monkeypatch):
        """Files that no longer exist on disk should not appear in results."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        proj_dir = tmp_path / ".claude" / "projects" / "my-project"
        proj_dir.mkdir(parents=True)
        jsonl_file = _write_real_session("doomed-sess", proj_dir)

        from src.parser import discover_sessions
        sessions_1 = discover_sessions()
        assert any(s.session_id == "doomed-sess" for s in sessions_1)

        # Delete the file
        jsonl_file.unlink()

        sessions_2 = discover_sessions()
        assert not any(s.session_id == "doomed-sess" for s in sessions_2), (
            "Deleted session file should not appear in results (stale cache entry)."
        )

    def test_new_file_discovered_alongside_cached(self, tmp_path, monkeypatch):
        """New files should be parsed and appear alongside cached sessions."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        proj_dir = tmp_path / ".claude" / "projects" / "my-project"
        proj_dir.mkdir(parents=True)
        _write_real_session("existing-sess", proj_dir)

        from src.parser import discover_sessions
        sessions_1 = discover_sessions()
        assert len(sessions_1) == 1

        # Add a new file
        _write_real_session("new-sess", proj_dir)

        sessions_2 = discover_sessions()
        ids = [s.session_id for s in sessions_2]
        assert "existing-sess" in ids, "Cached session should still appear."
        assert "new-sess" in ids, "New session should be discovered."
        assert len(sessions_2) == 2
