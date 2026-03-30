"""
Textual TUI for pending Claude Code sessions.

Main UI components and key binding handlers.
"""

from datetime import datetime, timedelta, timezone

from textual.app import ComposeResult, App
from textual.containers import Vertical
from textual.widgets import Footer, Header, ListItem, ListView, Static
from textual.binding import Binding

from src.parser import Session, discover_sessions, format_elapsed_time, _extract_text_from_content
from src.dismiss import read_dismissed_ids, dismiss_session

DEFAULT_DAYS_FILTER = 7


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

    def __init__(self, session: Session):
        super().__init__()
        self.session = session
        if session.status == "ready":
            self.add_class("status-ready")

    def render(self) -> str:
        """Render the list item."""
        # Format: "project [title] status time"
        # Preview on next line
        elapsed = format_elapsed_time(self.session.last_message_timestamp)
        status = self.session.status

        # Build the main line
        main_line = f"  {self.session.project_name:15} [{self.session.title:40}] {status:>11} {elapsed:>10}"

        # Build the preview line
        preview = self.session.last_assistant_message
        if not preview:
            preview = "(no messages)"

        # Truncate preview to roughly 70 chars
        if len(preview) > 70:
            preview = preview[:67] + "..."

        return f"{main_line}\n    \"{preview}\""


class SessionListView(ListView):
    """The main session list view."""

    def __init__(self, sessions: list[Session] | None = None, **kwargs):
        super().__init__(**kwargs)
        self.sessions = sessions or []

    def update_sessions(self, sessions: list[Session]):
        """Update the list with new sessions."""
        self.sessions = sessions
        self.clear()

        if not sessions:
            # Show empty state
            self.append(ListItem(Static("All caught up.")))
        else:
            for session in sessions:
                self.append(SessionListItem(session))

    def get_selected_session(self) -> Session | None:
        """Get the currently selected session."""
        if self.index is not None and 0 <= self.index < len(self.sessions):
            return self.sessions[self.index]
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

        lines = ["Preview: {} / {}\n".format(self.session.project_name, self.session.title)]

        # Show last ~5 message exchanges (max 10 messages)
        messages = self.session.full_message_history[-10:]

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
        Binding("space", "toggle_preview", "Preview", show=True),
        Binding("o", "open_session", "Open", show=True),
        Binding("d", "dismiss_current", "Dismiss", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    CSS = """
    Screen {
        layout: vertical;
    }

    #session-list {
        height: 1fr;
        border: solid $primary;
    }

    SessionListItem.status-ready {
        color: $success;
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
            yield SessionListView(id="session-list")
            yield PreviewPane(id="preview-pane")

        yield Footer()

    def on_mount(self):
        """Initialize the app on mount."""
        self.title = "Claude Code Pending Sessions"
        self.refresh_sessions()

    def refresh_sessions(self):
        """Refresh the session list from disk."""
        # Discover all sessions
        all_sessions = discover_sessions()

        # Layer 2: Filter out dismissed sessions
        dismissed_ids = read_dismissed_ids()
        active_sessions = [
            s for s in all_sessions if s.session_id not in dismissed_ids
        ]

        # Layer 3: Filter by date cutoff (default: last 7 days)
        cutoff = datetime.now(timezone.utc) - timedelta(days=DEFAULT_DAYS_FILTER)
        active_sessions = [
            s for s in active_sessions if is_within_cutoff(s, cutoff)
        ]

        # Get the list view and update it
        list_view = self.query_one("#session-list", SessionListView)
        list_view.update_sessions(active_sessions)

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
        """Open the selected session in Claude Code."""
        try:
            list_view = self.query_one("#session-list", SessionListView)
            session = list_view.get_selected_session()
            if session:
                # Exit with the session ID, main.py will handle launching Claude Code
                # after the app has fully exited and restored the terminal
                self.exit(result=session)
        except Exception as e:
            print("Error opening session: {}".format(e))

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
