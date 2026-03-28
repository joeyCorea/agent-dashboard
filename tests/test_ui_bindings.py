"""Tests for UI key binding configuration.

Verifies that key bindings in PendingSessionsApp are wired to the correct
actions, specifically that 'enter' opens the selected session (same as 'o').
"""

from src.ui import PendingSessionsApp


class TestEnterKeyBinding:
    """The 'enter' key must open the selected session, same as 'o'."""

    def _get_binding(self, key: str):
        """Return the Binding for a given key, or None if not bound."""
        for binding in PendingSessionsApp.BINDINGS:
            if binding.key == key:
                return binding
        return None

    def test_enter_key_opens_session(self):
        """Pressing Enter must trigger action_open_session (same as 'o')."""
        binding = self._get_binding("enter")
        action = binding.action if binding else None
        assert action == "open_session", (
            f"Expected enter to open_session but got: {action!r}. "
            "The 'enter' key should open the selected session in Claude Code, "
            "same as pressing 'o'."
        )

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

    def test_enter_not_bound_to_toggle_preview(self):
        """Enter must NOT toggle the preview pane."""
        binding = self._get_binding("enter")
        action = binding.action if binding else None
        assert action != "toggle_preview", (
            "The 'enter' key is still bound to toggle_preview. "
            "It should be rebound to open_session."
        )

    def test_o_key_still_opens_session(self):
        """The 'o' key must still be bound to open_session (no regression)."""
        binding = self._get_binding("o")
        action = binding.action if binding else None
        assert action == "open_session", (
            f"The 'o' key should still open a session but is bound to: {action!r}"
        )
