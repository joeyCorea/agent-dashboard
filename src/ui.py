"""
Textual TUI for pending Claude Code sessions.

Main UI components and key binding handlers.
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from typing import Any, Optional

from textual.app import ComposeResult, App
from textual.containers import Vertical
from textual.widgets import Footer, Header, Input, ListItem, ListView, Static
from textual.binding import Binding

from textual import work
from rich.markup import escape

from src.parser import Session, discover_sessions, format_elapsed_time, load_message_history, _extract_text_from_content
from src.dismiss import read_dismissed_ids, dismiss_session

DEFAULT_DAYS_FILTER = 7


def parse_filter_input(value: str) -> Optional[int]:
    """Parse user input for the days filter.

    Returns a non-negative integer, or None if input is invalid.
    """
    try:
        days = int(value)
        return days if days >= 0 else None
    except (ValueError, TypeError):
        return None


def filter_subtitle(days_filter: int) -> str:
    """Return the subtitle text for the current filter setting."""
    return f"Last {days_filter}d" if days_filter > 0 else "All sessions"


def filter_sessions(sessions: list[Session], days_filter: int = DEFAULT_DAYS_FILTER) -> list[Session]:
    """Apply dismissal and optional date filtering to a session list.

    When days_filter is 0, no date filtering is applied (show all sessions).
    """
    dismissed_ids = read_dismissed_ids()
    result = [s for s in sessions if s.session_id not in dismissed_ids]

    if days_filter > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_filter)
        result = [s for s in result if is_within_cutoff(s, cutoff)]

    return result


def group_sessions(sessions: list[Session]) -> list[tuple[str, Any]]:
    """Group sessions by project name with headers.

    Returns a list of tagged tuples:
      ("header", project_name) — group header
      ("session", Session)     — session item

    Groups sorted by most recent session in each group.
    Sessions within each group preserve their input order.
    """
    if not sessions:
        return []

    groups = defaultdict(list)
    for s in sessions:
        groups[s.project_name].append(s)

    sorted_groups = sorted(
        groups.items(),
        key=lambda g: g[1][0].last_message_timestamp,
        reverse=True,
    )

    result = []
    for project_name, project_sessions in sorted_groups:
        result.append(("header", project_name))
        for s in project_sessions:
            result.append(("session", s))
    return result


def is_within_cutoff(session: Session, cutoff: datetime) -> bool:
    """Check if a session's timestamp is at or after the cutoff.

    Handles mixed timezone-aware and naive datetimes: if the session
    timestamp is naive (fallback from unparseable timestamps), treat
    it as UTC so the comparison doesn't raise TypeError.
    """
    ts = session.last_message_timestamp
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts >= cutoff


class SessionListItem(ListItem):
    """A single session item in the list."""

    def __init__(self, session: Session, grouped: bool = False):
        super().__init__()
        self.session = session
        self.grouped = grouped
        if session.status == "ready":
            self.add_class("status-ready")

    def render(self) -> str:
        """Render the list item."""
        # Format: "project [title] status time" (flat) or "[title] status time" (grouped)
        # Preview on next line
        elapsed = format_elapsed_time(self.session.last_message_timestamp)
        status = self.session.status

        # Escape dynamic text to prevent Rich markup interpretation
        # (session content may contain brackets like [/code] that Rich treats as tags)
        title = escape(self.session.title)

        # Build the main line — omit project name when grouped (header already shows it)
        if self.grouped:
            main_line = f"  {title:40}  {status:>11} {elapsed:>10}"
        else:
            main_line = f"  {escape(self.session.project_name):15} {title:40}  {status:>11} {elapsed:>10}"

        # Build the preview line
        preview = self.session.last_assistant_message
        if not preview:
            preview = "(no messages)"

        # Truncate preview to roughly 70 chars
        if len(preview) > 70:
            preview = preview[:67] + "..."

        return f"{main_line}\n    \"{escape(preview)}\""


class SessionListView(ListView):
    """The main session list view."""

    def __init__(self, sessions: list[Session] | None = None, **kwargs):
        super().__init__(**kwargs)
        self.sessions = sessions or []

    def update_sessions(self, sessions: list[Session], grouped: bool = False):
        """Update the list with new sessions."""
        self.sessions = sessions
        self.clear()

        if not sessions:
            self.append(ListItem(Static("All caught up.")))
            return

        if not grouped:
            for session in sessions:
                self.append(SessionListItem(session))
            return

        for tag, value in group_sessions(sessions):
            if tag == "header":
                header = ListItem(Static(f"  --- {value} ---"))
                header.add_class("group-header")
                self.append(header)
            else:
                self.append(SessionListItem(value, grouped=True))

    def get_selected_session(self) -> Session | None:
        """Get the currently selected session.

        Walks the widget children to find the selected item. This handles
        both flat and grouped views — in grouped view, header ListItems
        are not SessionListItems and are skipped.
        """
        if self.index is None:
            return None
        children = list(self.children)
        if 0 <= self.index < len(children):
            child = children[self.index]
            if isinstance(child, SessionListItem):
                return child.session
        return None


class PreviewPane(Static):
    """Collapsible preview pane showing recent messages."""

    DEFAULT_CSS = """
    PreviewPane {
        border: solid $primary;
        height: auto;
        max-height: 15;
        overflow: auto;
    }
    """

    def __init__(self, session: Session | None = None, **kwargs):
        super().__init__(**kwargs)
        self.session = session
        self.visible = False

    def render(self) -> str:
        """Render the preview pane."""
        if not self.session:
            return ""

        lines = ["Preview: {} / {}\n".format(
            escape(self.session.project_name), escape(self.session.title))]

        # Load message history on demand (lazy loading)
        full_history = load_message_history(self.session.filepath)
        messages = full_history[-10:]

        for msg in messages:
            role = msg.get("message", {}).get("role", "unknown")
            content = msg.get("message", {}).get("content", "")

            if not content:
                continue

            # Extract text from structured or plain content
            text = _extract_text_from_content(content)
            if not text:
                continue

            # Get first line only
            first_line = text.split("\n")[0]
            if len(first_line) > 70:
                first_line = first_line[:67] + "..."

            first_line = escape(first_line)
            if role == "user":
                lines.append("You:    {}".format(first_line))
            elif role == "assistant":
                lines.append("Claude: {}".format(first_line))
            lines.append("")

        return "\n".join(lines)


class PendingSessionsApp(App):
    """Main TUI application for pending sessions."""

    BINDINGS = [
        Binding("j", "move_down", "Down", show=False),
        Binding("k", "move_up", "Up", show=False),
        Binding("enter", "open_session", "Open", show=False, priority=True),
        Binding("escape", "close_search", "Close search", show=False),
        Binding("space", "toggle_preview", "Preview", show=True),
        Binding("o", "open_session", "Open", show=True),
        Binding("d", "dismiss_current", "Dismiss", show=True),
        Binding("slash", "open_search", "Search", show=True),
        Binding("f", "open_filter", "Filter", show=True),
        Binding("g", "toggle_group", "Group", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    CSS = """
    Screen {
        layout: vertical;
    }

    #filter-input {
        dock: top;
        display: none;
        height: 3;
        border: solid $accent;
    }

    #filter-input.visible {
        display: block;
    }

    #search-input {
        dock: top;
        display: none;
        height: 3;
        border: solid $accent;
    }

    #search-input.visible {
        display: block;
    }

    #session-list {
        height: 1fr;
        border: solid $primary;
    }

    SessionListItem.status-ready {
        color: $success;
    }

    .group-header {
        color: $accent;
        text-style: bold;
    }

    #preview-pane {
        dock: bottom;
        height: auto;
        max-height: 15;
        border: solid $accent;
        display: none;
    }

    #preview-pane.visible {
        display: block;
    }

    #empty-state {
        align: center middle;
        height: 1fr;
        content-align: center middle;
    }
    """

    def compose(self) -> ComposeResult:
        """Compose the app layout."""
        yield Header()

        with Vertical(id="main-container"):
            yield Input(placeholder="Search by title:", id="search-input")
            yield Input(placeholder="Days to filter (0 = all):", id="filter-input")
            yield SessionListView(id="session-list")
            yield PreviewPane(id="preview-pane")

        yield Footer()

    def __init__(self, default_days: int | None = None):
        super().__init__()
        self._initial_days = default_days if default_days is not None else DEFAULT_DAYS_FILTER

    def on_mount(self):
        """Initialize the app on mount."""
        self._days_filter = self._initial_days
        self._grouped = True
        self._search_query = ""
        self.title = "Claude Code Pending Sessions"
        self.sub_title = filter_subtitle(self._days_filter)
        self._load_sessions()

    @work(thread=True)
    def _load_sessions(self):
        """Load sessions in a background thread for non-blocking startup."""
        self.call_from_thread(self._show_loading)
        all_sessions = discover_sessions()
        active_sessions = filter_sessions(all_sessions, self._days_filter)
        self.call_from_thread(self._update_session_list, active_sessions)

    def _show_loading(self):
        """Show a loading indicator in the session list."""
        list_view = self.query_one("#session-list", SessionListView)
        list_view.clear()
        list_view.append(ListItem(Static("  Loading sessions...")))

    def _update_session_list(self, sessions: list[Session]):
        """Update the UI with loaded sessions (called on the main thread)."""
        filtered = self._apply_search_filter(sessions)
        list_view = self.query_one("#session-list", SessionListView)
        list_view.update_sessions(filtered, grouped=self._grouped)
        list_view.focus()

    def _apply_search_filter(self, sessions: list[Session]) -> list[Session]:
        """Filter sessions by title using the current search query.

        Each whitespace-separated term must appear somewhere in the title
        (case-insensitive). All terms must match for a session to be included.
        """
        if not self._search_query:
            return sessions
        terms = self._search_query.lower().split()
        return [
            s for s in sessions
            if all(term in s.title.lower() for term in terms)
        ]

    def refresh_sessions(self):
        """Refresh the session list from disk."""
        self._load_sessions()

    def action_toggle_group(self):
        """Toggle between flat and grouped-by-project view."""
        self._grouped = not self._grouped
        self.refresh_sessions()

    def action_open_filter(self):
        """Show the filter input widget."""
        filter_input = self.query_one("#filter-input", Input)
        filter_input.add_class("visible")
        filter_input.value = str(self._days_filter)
        filter_input.focus()

    def action_open_search(self):
        """Show the search input widget."""
        search_input = self.query_one("#search-input", Input)
        search_input.add_class("visible")
        search_input.value = self._search_query
        search_input.focus()

    def action_close_search(self):
        """Close the search input and clear the search query."""
        search_input = self.query_one("#search-input", Input)
        if search_input.has_class("visible"):
            search_input.remove_class("visible")
            search_input.value = ""
            self._search_query = ""
            self.query_one("#session-list", SessionListView).focus()
            self.refresh_sessions()

    def on_input_submitted(self, event: Input.Submitted):
        """Handle input submission for filter and search."""
        if event.input.id == "filter-input":
            self._submit_filter(event.input)
        elif event.input.id == "search-input":
            self._submit_search(event.input)

    def action_move_up(self):
        """Move up in the list."""
        try:
            list_view = self.query_one("#session-list", SessionListView)
            if list_view.index is not None and list_view.index > 0:
                list_view.index -= 1
        except Exception:
            pass

    def action_move_down(self):
        """Move down in the list."""
        try:
            list_view = self.query_one("#session-list", SessionListView)
            if list_view.index is not None and list_view.index < len(list_view) - 1:
                list_view.index += 1
        except Exception:
            pass

    def action_toggle_preview(self):
        """Toggle the preview pane."""
        try:
            list_view = self.query_one("#session-list", SessionListView)
            preview = self.query_one("#preview-pane", PreviewPane)

            # Get selected session
            session = list_view.get_selected_session()
            if not session:
                return

            # Toggle visibility
            preview.visible = not preview.visible
            preview.session = session if preview.visible else None

            # Update CSS class
            if preview.visible:
                preview.add_class("visible")
            else:
                preview.remove_class("visible")
        except Exception:
            pass

    def action_open_session(self):
        """Open the selected session in Claude Code.

        When the filter input is visible, Enter should submit the filter
        instead of opening a session. The app-level enter binding has
        priority=True (to override ListView), which also intercepts Enter
        from the Input widget — so we detect that case and delegate.
        """
        try:
            search_input = self.query_one("#search-input", Input)
            if search_input.has_class("visible"):
                self._submit_search(search_input)
                return

            filter_input = self.query_one("#filter-input", Input)
            if filter_input.has_class("visible"):
                self._submit_filter(filter_input)
                return

            list_view = self.query_one("#session-list", SessionListView)
            session = list_view.get_selected_session()
            if session:
                # Exit with the session ID, main.py will handle launching Claude Code
                # after the app has fully exited and restored the terminal
                self.exit(result=session)
        except Exception as e:
            print("Error opening session: {}".format(e))

    def _submit_filter(self, filter_input: Input):
        """Process filter input submission and hide the widget."""
        days = parse_filter_input(filter_input.value)
        if days is not None:
            self._days_filter = days
        filter_input.remove_class("visible")
        filter_input.value = ""
        self.query_one("#session-list", SessionListView).focus()
        self.sub_title = filter_subtitle(self._days_filter)
        self.refresh_sessions()

    def _submit_search(self, search_input: Input):
        """Process search input submission and hide the widget."""
        self._search_query = search_input.value.strip()
        search_input.remove_class("visible")
        self.query_one("#session-list", SessionListView).focus()
        self.refresh_sessions()

    def action_dismiss_current(self):
        """Dismiss the selected session."""
        try:
            list_view = self.query_one("#session-list", SessionListView)
            session = list_view.get_selected_session()
            if session:
                dismiss_session(session.session_id)
                self.refresh_sessions()
        except Exception as e:
            print("Error dismissing session: {}".format(e))

    def action_refresh(self):
        """Manually refresh the session list."""
        self.refresh_sessions()
