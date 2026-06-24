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

# A book belongs to exactly one activity. Stored per-row so the two shelves never
# show each other's books (see activity_state / story_routes).
KIND_STORY = "story"
KIND_READ_ALONG = "read_along"

_CSV_FIELDS = ["id", "title", "created_date", "last_read_date", "kind"]
_CSV_FILE = "books.csv"


def _derive_kind(book_id: str) -> str:
    """Infer a legacy row's kind from its id (read-along ids are the ``sel-*`` set)."""
    return KIND_READ_ALONG if book_id.startswith("sel-") else KIND_STORY


class BookMeta:
    """Metadata for a single persisted book."""

    __slots__ = ("id", "title", "created_date", "last_read_date", "kind")

    def __init__(
        self,
        id: str,
        title: str,
        created_date: str,
        last_read_date: str,
        kind: str = KIND_STORY,
    ):
        """Store the book's id, title, creation/last-read timestamps and activity kind."""
        self.id = id
        self.title = title
        self.created_date = created_date
        self.last_read_date = last_read_date
        self.kind = kind


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

    def save_book(self, story: "Story", kind: str = KIND_STORY) -> None:
        """Persist all pages of a completed story to disk, tagged with its activity kind."""
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
        self._upsert_csv(story.id, story.title, now, now, kind)
        logger.info("Book '%s' (%s) saved to %s", story.title, kind, book_dir)

    def list_books(self, kind: Optional[str] = None) -> List[BookMeta]:
        """Return books sorted newest-first, optionally filtered to one activity kind."""
        rows = self._read_csv()
        if kind is not None:
            rows = [r for r in rows if r.kind == kind]
        return sorted(rows, key=lambda r: r.created_date, reverse=True)

    def get_book(self, book_id: str, kind: Optional[str] = None) -> Optional[BookMeta]:
        """Return metadata for the given book id, or None if not found / wrong kind."""
        for row in self._read_csv():
            if row.id == book_id:
                if kind is not None and row.kind != kind:
                    return None
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

    def delete_book(self, book_id: str, kind: Optional[str] = None) -> bool:
        """Delete a book's metadata and files; return True if removed.

        When ``kind`` is given, only a book of that activity is deleted (so the
        storybook shelf can't delete a read-along book or vice versa).
        """
        _validate_book_id(book_id)
        with self._rw_lock:
            rows = self._read_csv_unlocked()
            new_rows = [
                r for r in rows
                if not (r.id == book_id and (kind is None or r.kind == kind))
            ]
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
                        # Legacy CSVs predate the kind column → derive from the id.
                        kind=(row.get("kind") or "").strip() or _derive_kind(row["id"]),
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
                    "kind": r.kind,
                })
        tmp.replace(self._csv_path)

    def _upsert_csv(self, id: str, title: str, created: str, last_read: str, kind: str) -> None:
        """Insert or update a book's row, rewriting the whole CSV.

        Read-modify-write (not append) so re-saving the same id can't duplicate a
        row and a legacy header without the ``kind`` column is migrated in place.
        """
        with self._rw_lock:
            rows = self._read_csv_unlocked()
            for r in rows:
                if r.id == id:
                    r.title, r.last_read_date, r.kind = title, last_read, kind
                    self._write_csv_unlocked(rows)
                    return
            rows.append(BookMeta(id, title, created, last_read, kind))
            self._write_csv_unlocked(rows)
