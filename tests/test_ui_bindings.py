"""Tests for UI key binding configuration, configurable filter, and grouped view."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.ui import PendingSessionsApp, is_within_cutoff, DEFAULT_DAYS_FILTER
from src.parser import Session, discover_sessions


class TestEnterKeyBinding:

    def _get_binding(self, key: str):
        for binding in PendingSessionsApp.BINDINGS:
            if binding.key == key:
                return binding
        return None

    def test_enter_binding_has_priority(self):
        """Enter binding must have priority=True to override ListView's built-in enter handler.

        ListView intercepts 'enter' at the widget level before it can bubble up
        to the app. Without priority=True, the app-level binding is silently ignored.
        """
        binding = self._get_binding("enter")
        assert binding is not None and binding.priority is True, (
            "The 'enter' binding must have priority=True. "
            "ListView's built-in handler intercepts 'enter' before app-level bindings "
            "fire — priority=True is required to override it."
        )


def _write_session_at(session_id: str, project_dir: Path, timestamp: datetime) -> Path:
    """Create a JSONL session file with a specific timestamp."""
    ts_str = timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
    jsonl_file = project_dir / f"{session_id}.jsonl"
    with open(jsonl_file, "w") as f:
        f.write(json.dumps({"sessionId": session_id, "timestamp": ts_str,
                            "message": {"role": "user", "content": "hello"}}) + "\n")
        f.write(json.dumps({"sessionId": session_id, "timestamp": ts_str,
                            "message": {"role": "assistant", "content": "hi"}}) + "\n")
    return jsonl_file


class TestFilterBinding:
    """The 'f' key binding must exist and trigger the filter action."""

    def _get_binding(self, key: str):
        for binding in PendingSessionsApp.BINDINGS:
            if binding.key == key:
                return binding
        return None

    def test_f_binding_exists(self):
        """The 'f' key must be bound to action_open_filter."""
        binding = self._get_binding("f")
        assert binding is not None, "No 'f' binding found in PendingSessionsApp.BINDINGS."
        assert binding.action == "open_filter", (
            f"Expected 'f' to trigger 'open_filter', got '{binding.action}'."
        )


class TestConfigurableDaysFilter:
    """The date filter cutoff should be adjustable at runtime via _days_filter.

    When _days_filter is 0, no date filtering should occur (show all sessions).
    When _days_filter is a positive integer, only sessions within that many days are shown.
    """

    def test_custom_days_filter_3_days(self, tmp_path, monkeypatch):
        """With a 3-day filter, a 2-day-old session is included, a 5-day-old session is excluded."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        proj_dir = tmp_path / ".claude" / "projects" / "my-project"
        proj_dir.mkdir(parents=True)

        two_days_ago = datetime.now(timezone.utc) - timedelta(days=2)
        five_days_ago = datetime.now(timezone.utc) - timedelta(days=5)
        _write_session_at("recent", proj_dir, two_days_ago)
        _write_session_at("older", proj_dir, five_days_ago)

        sessions = discover_sessions()
        days_filter = 3
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_filter)
        included = [s for s in sessions if is_within_cutoff(s, cutoff)]
        ids = [s.session_id for s in included]
        assert "recent" in ids, "2-day-old session should pass a 3-day filter."
        assert "older" not in ids, "5-day-old session should be excluded by a 3-day filter."

    def test_zero_days_filter_shows_all(self, tmp_path, monkeypatch):
        """When _days_filter is 0, all sessions should be shown (no date filtering).

        The app must skip the cutoff filter entirely when days_filter == 0.
        We simulate this by importing the app's filter_sessions helper.
        """
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        proj_dir = tmp_path / ".claude" / "projects" / "my-project"
        proj_dir.mkdir(parents=True)

        ancient = datetime.now(timezone.utc) - timedelta(days=365)
        _write_session_at("ancient", proj_dir, ancient)

        from src.ui import filter_sessions
        sessions = discover_sessions()
        included = filter_sessions(sessions, days_filter=0)
        assert any(s.session_id == "ancient" for s in included), (
            "A 365-day-old session should be included when days_filter is 0 (show all)."
        )

    def test_filter_persists_default_is_7(self):
        """The default days filter value must be 7."""
        assert DEFAULT_DAYS_FILTER == 7, (
            f"Expected DEFAULT_DAYS_FILTER to be 7, got {DEFAULT_DAYS_FILTER}."
        )

    def test_parse_filter_input_valid_integer(self):
        """Valid positive integer input should be accepted."""
        from src.ui import parse_filter_input
        assert parse_filter_input("3") == 3
        assert parse_filter_input("0") == 0
        assert parse_filter_input("30") == 30

    def test_parse_filter_input_invalid_returns_none(self):
        """Non-numeric, negative, or empty input should return None (keep current filter)."""
        from src.ui import parse_filter_input
        assert parse_filter_input("") is None
        assert parse_filter_input("abc") is None
        assert parse_filter_input("-5") is None
        assert parse_filter_input("3.5") is None

    def test_subtitle_text_for_active_filter(self):
        """Subtitle should show 'Last Xd' for positive filter, 'All sessions' for 0."""
        from src.ui import filter_subtitle
        assert filter_subtitle(7) == "Last 7d"
        assert filter_subtitle(3) == "Last 3d"
        assert filter_subtitle(0) == "All sessions"


def _make_session(session_id: str, project_name: str, days_ago: int = 0) -> Session:
    """Create a Session object for grouping tests."""
    ts = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return Session(
        session_id=session_id,
        project_name=project_name,
        title=f"Session {session_id}",
        last_message_timestamp=ts,
        last_assistant_message="some response",
        filepath=Path("dummy.jsonl"),
        status="ready",
    )


class TestDefaultGrouped:
    """The app must start in grouped view by default."""

    def test_default_grouped_is_true(self):
        """_grouped must default to True so the app starts in grouped-by-project view."""
        app = PendingSessionsApp()
        # on_mount sets _grouped; simulate it by checking the intended default
        # We verify the on_mount code path sets _grouped = True
        assert hasattr(PendingSessionsApp, 'on_mount'), "App must have on_mount method"
        import inspect
        source = inspect.getsource(PendingSessionsApp.on_mount)
        assert "_grouped = True" in source, (
            "on_mount must set _grouped = True (grouped view as default). "
            f"Found: {source}"
        )


class TestGroupBinding:
    """The 'g' key binding must exist and trigger the group toggle."""

    def _get_binding(self, key: str):
        for binding in PendingSessionsApp.BINDINGS:
            if binding.key == key:
                return binding
        return None

    def test_g_binding_exists(self):
        """The 'g' key must be bound to action_toggle_group."""
        binding = self._get_binding("g")
        assert binding is not None, "No 'g' binding found in PendingSessionsApp.BINDINGS."
        assert binding.action == "toggle_group", (
            f"Expected 'g' to trigger 'toggle_group', got '{binding.action}'."
        )


class TestGroupSessions:
    """group_sessions() organizes sessions by project name with headers.

    Returns a list of tuples: either ("header", project_name) for group headers
    or ("session", Session) for session items. Groups are sorted by most recent
    session in the group. Sessions within each group retain their existing order.
    """

    def test_single_project_produces_one_header(self):
        """Sessions from one project produce one header followed by sessions."""
        from src.ui import group_sessions
        sessions = [
            _make_session("s1", "my-project", days_ago=1),
            _make_session("s2", "my-project", days_ago=2),
        ]
        result = group_sessions(sessions)
        headers = [item for item in result if item[0] == "header"]
        assert len(headers) == 1, f"Expected 1 header, got {len(headers)}: {headers}"
        assert headers[0][1] == "my-project"

    def test_multiple_projects_sorted_by_most_recent(self):
        """Groups are sorted by the most recent session in each group."""
        from src.ui import group_sessions
        sessions = [
            _make_session("s1", "project-a", days_ago=3),  # oldest
            _make_session("s2", "project-b", days_ago=1),  # most recent
        ]
        result = group_sessions(sessions)
        headers = [item[1] for item in result if item[0] == "header"]
        assert headers == ["project-b", "project-a"], (
            f"Expected groups sorted by recency: ['project-b', 'project-a'], got {headers}"
        )

    def test_sessions_within_group_preserve_order(self):
        """Sessions within a group retain the order they were passed in."""
        from src.ui import group_sessions
        sessions = [
            _make_session("newer", "proj", days_ago=1),
            _make_session("older", "proj", days_ago=3),
        ]
        result = group_sessions(sessions)
        session_items = [item[1] for item in result if item[0] == "session"]
        ids = [s.session_id for s in session_items]
        assert ids == ["newer", "older"], (
            f"Sessions within group should preserve input order, got {ids}"
        )

    def test_empty_sessions_returns_empty(self):
        """Grouping an empty list returns an empty list."""
        from src.ui import group_sessions
        assert group_sessions([]) == []

    def test_interleaved_projects_grouped_correctly(self):
        """Sessions from different projects interleaved in the input are grouped together."""
        from src.ui import group_sessions
        sessions = [
            _make_session("a1", "alpha", days_ago=0),
            _make_session("b1", "beta", days_ago=1),
            _make_session("a2", "alpha", days_ago=2),
        ]
        result = group_sessions(sessions)
        # alpha group: a1, a2 (most recent = 0 days ago → first group)
        # beta group: b1 (most recent = 1 day ago → second group)
        headers = [item[1] for item in result if item[0] == "header"]
        assert headers == ["alpha", "beta"], f"Expected ['alpha', 'beta'], got {headers}"

        alpha_sessions = []
        in_alpha = False
        for tag, val in result:
            if tag == "header" and val == "alpha":
                in_alpha = True
            elif tag == "header":
                in_alpha = False
            elif tag == "session" and in_alpha:
                alpha_sessions.append(val.session_id)
        assert alpha_sessions == ["a1", "a2"], (
            f"Alpha group should contain a1, a2 in order, got {alpha_sessions}"
        )


class TestSearchBinding:
    """The '/' key binding must exist and trigger the search action."""

    def _get_binding(self, key: str):
        for binding in PendingSessionsApp.BINDINGS:
            if binding.key == key:
                return binding
        return None

    def test_slash_binding_exists(self):
        """The '/' key must be bound to action_open_search."""
        binding = self._get_binding("slash")
        assert binding is not None, "No 'slash' binding found in PendingSessionsApp.BINDINGS."
        assert binding.action == "open_search", (
            f"Expected 'slash' to trigger 'open_search', got '{binding.action}'."
        )

    def test_escape_binding_exists(self):
        """The 'escape' key must be bound to action_close_search."""
        binding = self._get_binding("escape")
        assert binding is not None, "No 'escape' binding found in PendingSessionsApp.BINDINGS."
        assert binding.action == "close_search", (
            f"Expected 'escape' to trigger 'close_search', got '{binding.action}'."
        )


class TestSearchFilter:
    """_apply_search_filter should match each space-separated term against the title."""

    def _make_app(self):
        app = PendingSessionsApp()
        app._search_query = ""
        return app

    def test_empty_query_returns_all(self):
        app = self._make_app()
        sessions = [
            _make_session("s1", "proj"),
            _make_session("s2", "proj"),
        ]
        assert len(app._apply_search_filter(sessions)) == 2

    def test_single_term_matches(self):
        app = self._make_app()
        app._search_query = "eval"
        s1 = _make_session("s1", "proj")
        s1.title = "eval-skills"
        s2 = _make_session("s2", "proj")
        s2.title = "other-chat"
        result = app._apply_search_filter([s1, s2])
        assert len(result) == 1
        assert result[0].title == "eval-skills"

    def test_multiple_terms_all_must_match(self):
        app = self._make_app()
        app._search_query = "eval skills"
        s1 = _make_session("s1", "proj")
        s1.title = "eval-skills"
        s2 = _make_session("s2", "proj")
        s2.title = "eval-other"
        result = app._apply_search_filter([s1, s2])
        assert len(result) == 1
        assert result[0].title == "eval-skills"

    def test_case_insensitive(self):
        app = self._make_app()
        app._search_query = "EVAL"
        s1 = _make_session("s1", "proj")
        s1.title = "eval-skills"
        result = app._apply_search_filter([s1])
        assert len(result) == 1

    def test_no_match_returns_empty(self):
        app = self._make_app()
        app._search_query = "nonexistent"
        s1 = _make_session("s1", "proj")
        s1.title = "eval-skills"
        result = app._apply_search_filter([s1])
        assert len(result) == 0


class TestSessionListItemGroupedRendering:
    """SessionListItem should omit the project name when rendered in grouped mode."""

    def test_render_flat_includes_project_name(self):
        """In flat mode (grouped=False), the project name column is present."""
        from src.ui import SessionListItem
        session = _make_session("s1", "my-project")
        item = SessionListItem(session, grouped=False)
        rendered = item.render()
        assert "my-project" in rendered, (
            f"Flat mode should include project name. Got: {rendered}"
        )

    def test_render_grouped_omits_project_name(self):
        """In grouped mode (grouped=True), the project name column is omitted."""
        from src.ui import SessionListItem
        session = _make_session("s1", "my-project")
        item = SessionListItem(session, grouped=True)
        rendered = item.render()
        assert "my-project" not in rendered, (
            f"Grouped mode should omit project name. Got: {rendered}"
        )

