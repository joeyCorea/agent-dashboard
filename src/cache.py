"""Metadata cache with mtime invalidation for session discovery.

Caches parsed session metadata to avoid re-parsing unchanged JSONL files.
On each discovery pass, only files whose mtime differs from the cached
value are re-parsed. The cache is stored as a JSON file.
"""

import json
from pathlib import Path

CACHE_VERSION = 1
DEFAULT_CACHE_PATH = Path.home() / ".claude" / "dashboard-cache.json"


def load_cache(cache_path: Path = DEFAULT_CACHE_PATH) -> dict:
    """Load the session metadata cache from disk.

    Returns the sessions dict on success, or empty dict on any failure
    (missing file, corrupt JSON, version mismatch).
    """
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        if data.get("version") == CACHE_VERSION:
            return data.get("sessions", {})
    except Exception:
        pass
    return {}


def save_cache(cache_path: Path, sessions: dict) -> None:
    """Write the session metadata cache to disk."""
    cache_path.write_text(json.dumps({
        "version": CACHE_VERSION,
        "sessions": sessions,
    }), encoding="utf-8")
