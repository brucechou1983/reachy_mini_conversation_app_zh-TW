"""Persistent book library: CSV metadata + per-book image folders on disk."""

from __future__ import annotations
import csv
import base64
import shutil
import logging
import threading
from typing import TYPE_CHECKING, List, Optional
from pathlib import Path
from datetime import datetime, timezone


if TYPE_CHECKING:
    from reachy_mini_conversation_app.story_store import Story


logger = logging.getLogger(__name__)

_CSV_FIELDS = ["id", "title", "created_date", "last_read_date"]
_CSV_FILE = "books.csv"


class BookMeta:
    """Metadata for a single persisted book."""

    __slots__ = ("id", "title", "created_date", "last_read_date")

    def __init__(self, id: str, title: str, created_date: str, last_read_date: str):
        """Store the book's id, title, and creation/last-read timestamps."""
        self.id = id
        self.title = title
        self.created_date = created_date
        self.last_read_date = last_read_date


def _validate_book_id(book_id: str) -> str:
    """Raise ValueError if book_id contains path traversal components."""
    if not book_id or ".." in book_id or "/" in book_id or "\\" in book_id or "\0" in book_id:
        raise ValueError(f"invalid book id: {book_id!r}")
    return book_id


class BookLibrary:
    """Singleton persistent library for story books.

    Each book is stored as a directory of page images and text files,
    with a CSV file tracking metadata (id, title, dates).
    """

    _instance: Optional[BookLibrary] = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self, books_dir: Path) -> None:
        """Set up the books directory, CSV path, and lock; create the dir."""
        self._books_dir = books_dir
        self._csv_path = books_dir / _CSV_FILE
        self._rw_lock = threading.Lock()
        books_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def get(cls) -> BookLibrary:
        """Return the singleton instance, creating it on first call."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    from reachy_mini_conversation_app.config import config

                    books_dir_env = getattr(config, "STORY_BOOKS_DIR", None)
                    if books_dir_env:
                        books_dir = Path(books_dir_env)
                    else:
                        books_dir = Path.home() / ".reachy_mini" / "books"
                    cls._instance = cls(books_dir)
        return cls._instance

    @property
    def books_dir(self) -> Path:
        """Return the root directory where books are stored."""
        return self._books_dir

    # --- Core operations ---

    def save_book(self, story: "Story") -> None:
        """Persist all pages of a completed story to disk."""
        _validate_book_id(story.id)
        book_dir = self._books_dir / story.id
        book_dir.mkdir(parents=True, exist_ok=True)

        for i, page in enumerate(story.pages):
            if page.image_b64:
                ext = "jpg" if "jpeg" in page.image_mime else "png"
                img_path = book_dir / f"page_{i}.{ext}"
                img_path.write_bytes(base64.b64decode(page.image_b64))

            text_path = book_dir / f"page_{i}.txt"
            text_path.write_text(page.text, encoding="utf-8")

        now = datetime.now(timezone.utc).isoformat()
        self._append_csv(story.id, story.title, now, now)
        logger.info("Book '%s' saved to %s", story.title, book_dir)

    def list_books(self) -> List[BookMeta]:
        """Return all books sorted newest-first."""
        rows = self._read_csv()
        return sorted(rows, key=lambda r: r.created_date, reverse=True)

    def get_book(self, book_id: str) -> Optional[BookMeta]:
        """Return metadata for the given book id, or None if not found."""
        for row in self._read_csv():
            if row.id == book_id:
                return row
        return None

    def page_count(self, book_id: str) -> int:
        """Return the number of pages stored for the given book."""
        _validate_book_id(book_id)
        d = self._books_dir / book_id
        if not d.exists():
            return 0
        return len([f for f in d.iterdir() if f.suffix == ".txt"])

    def book_dir(self, book_id: str) -> Path:
        """Return the on-disk directory path for the given book."""
        _validate_book_id(book_id)
        return self._books_dir / book_id

    def page_image_path(self, book_id: str, page: int) -> Optional[Path]:
        """Return the image file path for a page, or None if none exists."""
        _validate_book_id(book_id)
        d = self._books_dir / book_id
        for ext in ("png", "jpg", "jpeg"):
            p = d / f"page_{page}.{ext}"
            if p.exists():
                return p
        return None

    def page_text(self, book_id: str, page: int) -> str:
        """Return the text of a page, or an empty string if missing."""
        _validate_book_id(book_id)
        p = self._books_dir / book_id / f"page_{page}.txt"
        if p.exists():
            return p.read_text(encoding="utf-8")
        return ""

    def update_last_read(self, book_id: str) -> None:
        """Update the last-read timestamp for the given book."""
        _validate_book_id(book_id)
        with self._rw_lock:
            rows = self._read_csv_unlocked()
            now = datetime.now(timezone.utc).isoformat()
            for row in rows:
                if row.id == book_id:
                    row.last_read_date = now
            self._write_csv_unlocked(rows)

    def delete_book(self, book_id: str) -> bool:
        """Delete a book's metadata and files; return True if removed."""
        _validate_book_id(book_id)
        with self._rw_lock:
            rows = self._read_csv_unlocked()
            new_rows = [r for r in rows if r.id != book_id]
            if len(new_rows) == len(rows):
                return False
            self._write_csv_unlocked(new_rows)
        book_dir = self._books_dir / book_id
        if book_dir.exists():
            shutil.rmtree(book_dir)
        return True

    # --- CSV helpers ---

    def _read_csv(self) -> List[BookMeta]:
        """Thread-safe read. Acquires lock internally."""
        with self._rw_lock:
            return self._read_csv_unlocked()

    def _read_csv_unlocked(self) -> List[BookMeta]:
        """Read CSV without locking. Caller must hold _rw_lock."""
        if not self._csv_path.exists():
            return []
        try:
            with self._csv_path.open(newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                return [
                    BookMeta(
                        id=row["id"],
                        title=row["title"],
                        created_date=row.get("created_date", ""),
                        last_read_date=row.get("last_read_date", ""),
                    )
                    for row in reader
                ]
        except Exception as e:
            logger.warning("Failed to read books CSV: %s", e)
            return []

    def _write_csv(self, rows: List[BookMeta]) -> None:
        """Thread-safe write. Acquires lock internally."""
        with self._rw_lock:
            self._write_csv_unlocked(rows)

    def _write_csv_unlocked(self, rows: List[BookMeta]) -> None:
        """Write CSV without locking. Caller must hold _rw_lock."""
        tmp = self._csv_path.with_suffix(".tmp")
        with tmp.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            for r in rows:
                writer.writerow({
                    "id": r.id,
                    "title": r.title,
                    "created_date": r.created_date,
                    "last_read_date": r.last_read_date,
                })
        tmp.replace(self._csv_path)

    def _append_csv(self, id: str, title: str, created: str, last_read: str) -> None:
        with self._rw_lock:
            write_header = not self._csv_path.exists()
            with self._csv_path.open("a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
                if write_header:
                    writer.writeheader()
                writer.writerow({
                    "id": id,
                    "title": title,
                    "created_date": created,
                    "last_read_date": last_read,
                })
