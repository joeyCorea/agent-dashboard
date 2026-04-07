#!/usr/bin/env python3
"""
Agent Dashboard - TUI for managing pending Claude Code sessions.
"""

import argparse
import subprocess
from pathlib import Path
from src.ui import PendingSessionsApp


def main():
    """Entry point for the TUI application."""
    parser = argparse.ArgumentParser(description="Claude Code Pending Sessions Dashboard")
    parser.add_argument("--days", type=int, default=None, help="Default number of days to filter (0 = show all)")
    args = parser.parse_args()

    app = PendingSessionsApp(default_days=args.days)
    session = app.run()

    # If a session was returned, the user opened a session
    # Launch Claude Code now that the TUI has fully exited
    if session:
        cwd = session.project_dir if session.project_dir and Path(session.project_dir).is_dir() else None
        subprocess.run(["claude", "--resume", session.session_id], cwd=cwd)


if __name__ == "__main__":
    main()
