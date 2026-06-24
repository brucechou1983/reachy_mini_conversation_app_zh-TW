"""Persistent per-book read-along progress (completion + stars).

A tiny JSON-backed store (atomic writes, same lightweight style as
:class:`BookLibrary`'s CSV) so the bookshelf can show a green check on books the
child has finished and remember their best star count across sessions.

Stored next to the book library, e.g. ``~/.reachy_mini/read_along_progress.json``::

    {
      "sel-big-feelings": {"completed": true, "stars": 4,
                            "times_read": 2, "last_read": "2026-06-24T..."}
    }
"""

from __future__ import annotations
import json
import logging
import threading
from typing import Any, Dict, Optional
from pathlib import Path
from datetime import datetime, timezone


logger = logging.getLogger(__name__)

_FILENAME = "read_along_progress.json"


def _default_path() -> Path:
    """Resolve the progress file path (alongside the book library)."""
    from reachy_mini_conversation_app.config import config

    books_dir = getattr(config, "STORY_BOOKS_DIR", None)
    base = Path(books_dir).parent if books_dir else Path.home() / ".reachy_mini"
    return base / _FILENAME


class ReadAlongProgress:
    """Singleton JSON store of per-book read-along progress."""

    _instance: Optional[ReadAlongProgress] = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self, path: Path) -> None:
        """Create the store at ``path`` and ensure its parent directory exists."""
        self._path = path
        self._rw_lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def get(cls) -> ReadAlongProgress:
        """Return the singleton instance, creating it on first call."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(_default_path())
        return cls._instance

    # --- io ---

    def _load(self) -> Dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return dict(data) if isinstance(data, dict) else {}
        except Exception as e:
            logger.warning("Failed to read read-along progress: %s", e)
            return {}

    def _save(self, data: Dict[str, Any]) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    # --- queries ---

    def all(self) -> Dict[str, Any]:
        """Return the full progress map (book_id -> record)."""
        with self._rw_lock:
            return self._load()

    def get_book(self, book_id: str) -> Optional[Dict[str, Any]]:
        """Return the progress record for a book, or None."""
        return self.all().get(book_id)

    def is_completed(self, book_id: str) -> bool:
        """Return True if the book has been finished at least once."""
        rec = self.get_book(book_id)
        return bool(rec and rec.get("completed"))

    def stars(self, book_id: str) -> int:
        """Return the best star count recorded for a book (0 if none)."""
        rec = self.get_book(book_id)
        return int(rec.get("stars", 0)) if rec else 0

    # --- mutations ---

    def mark_completed(self, book_id: str, stars: int = 0) -> Dict[str, Any]:
        """Mark a book finished, keep the best star count, bump the read count."""
        with self._rw_lock:
            data = self._load()
            rec: Dict[str, Any] = data.get(book_id, {"completed": False, "stars": 0, "times_read": 0})
            rec["completed"] = True
            rec["stars"] = max(int(rec.get("stars", 0)), int(stars))
            rec["times_read"] = int(rec.get("times_read", 0)) + 1
            rec["last_read"] = datetime.now(timezone.utc).isoformat()
            data[book_id] = rec
            self._save(data)
            return rec
