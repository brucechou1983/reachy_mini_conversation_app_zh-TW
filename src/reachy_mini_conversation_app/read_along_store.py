"""In-process store for the active read-along session and its SSE fan-out.

This mirrors :class:`StoryStore` but models the *Ello-style* reading loop where
the child reads and the robot scaffolds.  The signature mechanics live here so
they are deterministic and unit-testable rather than left to the LLM:

* **Tiered miss escalation** — a ``"miss"`` cue auto-escalates per word:
  1st miss → ``bounce``, 2nd miss → ``highlight``, 3rd+ → ``sound_out``
  (exactly Ello's word-state ladder).
* **Word resolution** — a flagged word string is matched to a token index on the
  current page (case/punctuation-insensitive, skipping already-mastered words).
* **Stars / progress** — lightweight reward state.

The frontend reader subscribes to the SSE fan-out and renders the broadcast
state; it never decides escalation itself.
"""

from __future__ import annotations
import asyncio
import logging
import threading
from typing import Any, Dict, List, Tuple, Optional
from dataclasses import field, dataclass

from reachy_mini_conversation_app.read_along_books import (
    READING_MODES,
    MODE_DECODABLE,
    MODE_TURN_TAKING,
    ReadAlongBook,
    ReadAlongBookPage,
    tokenize,
    normalize_word,
)


__all__ = [
    "READING_MODES",
    "MODE_DECODABLE",
    "MODE_TURN_TAKING",
    "ReadAlongSession",
    "ReadAlongStore",
    "STATE_BOUNCE",
    "STATE_HIGHLIGHT",
    "STATE_SOUND_OUT",
    "STATE_SUCCESS",
    "STATE_CLEAR",
    "CUE_MISS",
    "VALID_CUE_INPUTS",
]


logger = logging.getLogger(__name__)


# Word visual states (must match CSS classes in static/read_along.css).
STATE_BOUNCE = "bounce"
STATE_HIGHLIGHT = "highlight"
STATE_SOUND_OUT = "sound_out"
STATE_SUCCESS = "success"
STATE_CLEAR = "clear"
# Accepted cue inputs from the LLM (``miss`` auto-escalates through the ladder).
CUE_MISS = "miss"
_DIRECT_STATES = (STATE_BOUNCE, STATE_HIGHLIGHT, STATE_SOUND_OUT, STATE_SUCCESS, STATE_CLEAR)
VALID_CUE_INPUTS = (CUE_MISS, *_DIRECT_STATES)

# Miss-count -> escalated state ladder.
_ESCALATION = {1: STATE_BOUNCE, 2: STATE_HIGHLIGHT}


@dataclass
class ReadAlongSession:
    """State of one active read-along session."""

    book_id: str
    title: str
    sel_theme: str
    mode: str
    wrapup: str
    pages: List[ReadAlongBookPage]
    page_words: List[List[str]]
    current_page: int = 0
    stars: int = 0
    status: str = "reading"  # reading | finished | closed
    # Per-current-page transient state (reset on page change).
    word_states: Dict[int, str] = field(default_factory=dict)
    miss_counts: Dict[int, int] = field(default_factory=dict)

    @property
    def total_pages(self) -> int:
        """Return the number of pages in the active book."""
        return len(self.pages)

    @property
    def current(self) -> ReadAlongBookPage:
        """Return the current page object."""
        return self.pages[self.current_page]

    @property
    def current_words(self) -> List[str]:
        """Return the tokenized words of the current page."""
        return self.page_words[self.current_page]

    @property
    def is_last_page(self) -> bool:
        """Return True when the current page is the last page."""
        return self.current_page >= self.total_pages - 1

    def remaining_words(self) -> List[str]:
        """Return current-page words not yet read correctly (not ``success``)."""
        return [
            w for i, w in enumerate(self.current_words)
            if self.word_states.get(i) != STATE_SUCCESS
        ]

    @property
    def page_complete(self) -> bool:
        """Return True only when every word on the page is marked ``success``."""
        return not self.remaining_words()


class ReadAlongStore:
    """Singleton in-process store for the active read-along session."""

    _instance: Optional[ReadAlongStore] = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        """Initialize with no active session and no subscribers/handler."""
        self._session: Optional[ReadAlongSession] = None
        self._subscribers: List[asyncio.Queue[Dict[str, Any]]] = []
        self._handler: Any | None = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @classmethod
    def get(cls) -> ReadAlongStore:
        """Return the singleton instance, creating it on first call."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @property
    def session(self) -> Optional[ReadAlongSession]:
        """Return the currently active session, or None."""
        return self._session

    # --- realtime handler bridge (for browser tap -> robot) ---

    @property
    def handler(self) -> Any | None:
        """Return the realtime handler bound to the active session, if any."""
        return self._handler

    @property
    def loop(self) -> Optional[asyncio.AbstractEventLoop]:
        """Return the event loop the realtime handler runs on, if known."""
        return self._loop

    def bind_handler(self, handler: Any | None, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        """Bind the active realtime handler (and its loop) for tap injection."""
        self._handler = handler
        self._loop = loop

    # --- session lifecycle ---

    def start(self, book: ReadAlongBook, mode: str) -> ReadAlongSession:
        """Begin a new read-along session for ``book`` and broadcast page 1."""
        session = ReadAlongSession(
            book_id=book.id,
            title=book.title,
            sel_theme=book.sel_theme,
            mode=mode,
            wrapup=book.wrapup,
            pages=list(book.pages),
            page_words=[tokenize(p.text) for p in book.pages],
        )
        self._session = session
        self._broadcast(self._page_event())
        return session

    def go_to_page(self, page: int) -> Optional[int]:
        """Move to a (clamped) page, reset transient word state, and broadcast."""
        if not self._session or not self._session.pages:
            return None
        page = max(0, min(page, self._session.total_pages - 1))
        self._session.current_page = page
        self._session.status = "reading"
        self._session.word_states = {}
        self._session.miss_counts = {}
        self._broadcast(self._page_event())
        return page

    def next_page(self) -> Optional[Tuple[int, bool]]:
        """Advance one page if possible; return (new_page, is_last) or None."""
        if not self._session:
            return None
        if self._session.is_last_page:
            return self._session.current_page, True
        new_page = self.go_to_page(self._session.current_page + 1)
        assert new_page is not None  # session exists
        return new_page, self._session.is_last_page

    def resolve_index(self, word: Any) -> Optional[int]:
        """Resolve a word string (or int index) to a token index on the current page.

        Matches case/punctuation-insensitively and prefers a not-yet-mastered
        occurrence so repeated words escalate the right token.
        """
        if not self._session:
            return None
        words = self._session.current_words
        if isinstance(word, int) or (isinstance(word, str) and word.isdigit()):
            idx = int(word)
            return idx if 0 <= idx < len(words) else None
        if not isinstance(word, str):
            return None
        target = normalize_word(word)
        if not target:
            return None
        fallback: Optional[int] = None
        for i, w in enumerate(words):
            if normalize_word(w) == target:
                if self._session.word_states.get(i) != STATE_SUCCESS:
                    return i
                if fallback is None:
                    fallback = i
        return fallback

    def cue(self, word: Any, state: str) -> Optional[Dict[str, Any]]:
        """Flag a word with a visual state and broadcast it.

        ``state="miss"`` auto-escalates (bounce -> highlight -> sound_out) using
        the per-word miss count.  Returns the resolved cue, or None if the word
        could not be matched / no session is active.
        """
        if not self._session:
            return None
        idx = self.resolve_index(word)
        if idx is None:
            return None

        if state == CUE_MISS:
            self._session.miss_counts[idx] = self._session.miss_counts.get(idx, 0) + 1
            n = self._session.miss_counts[idx]
            effective = _ESCALATION.get(n, STATE_SOUND_OUT)
        elif state in _DIRECT_STATES:
            effective = state
        else:
            return None

        if effective == STATE_SUCCESS:
            self._session.miss_counts.pop(idx, None)
            self._session.word_states[idx] = STATE_SUCCESS
        elif effective == STATE_CLEAR:
            self._session.word_states.pop(idx, None)
        else:
            self._session.word_states[idx] = effective

        word_text = self._session.current_words[idx]
        miss = self._session.miss_counts.get(idx, 0)
        event = {
            "event": "word_cue",
            "index": idx,
            "word": word_text,
            "state": effective,
            "miss": miss,
        }
        self._broadcast(event)
        return {"index": idx, "word": word_text, "state": effective, "miss": miss}

    def grade(self, correct: List[str], incorrect: List[str]) -> Optional[Dict[str, Any]]:
        """Grade a whole page in one call: mark misses then successes.

        Misses are applied first so a word that is both wrong-then-right ends as
        success.  Returns the still-unread words and whether the page is complete.
        """
        if not self._session:
            return None
        for w in incorrect or []:
            self.cue(w, CUE_MISS)
        for w in correct or []:
            self.cue(w, STATE_SUCCESS)
        return {
            "remaining": self._session.remaining_words(),
            "complete": self._session.page_complete,
        }

    def add_stars(self, n: int) -> int:
        """Add ``n`` stars (never negative) and broadcast; return the new total."""
        if not self._session:
            return 0
        self._session.stars = max(0, self._session.stars + n)
        self._broadcast({"event": "stars", "stars": self._session.stars})
        return self._session.stars

    def finish(self, stars: int = 0) -> Optional[Dict[str, Any]]:
        """Mark the session finished, award stars, and broadcast the reward."""
        if not self._session:
            return None
        if stars:
            self._session.stars = max(0, self._session.stars + stars)
        self._session.status = "finished"
        payload = {
            "event": "read_along_finish",
            "stars": self._session.stars,
            "title": self._session.title,
            "wrapup": self._session.wrapup,
        }
        self._broadcast(payload)
        return payload

    def close(self) -> None:
        """Mark the session closed, broadcast, and clear it."""
        if self._session:
            self._session.status = "closed"
        self._broadcast({"event": "read_along_closed"})
        self._session = None

    # --- snapshots / events ---

    def _page_event(self) -> Dict[str, Any]:
        s = self._session
        assert s is not None
        page = s.current
        return {
            "event": "read_along_page",
            "book_id": s.book_id,
            "title": s.title,
            "mode": s.mode,
            "page": s.current_page,
            "total": s.total_pages,
            "words": list(s.current_words),
            "tricky": list(page.tricky),
            "sel_prompt": page.sel_prompt,
            "is_last_page": s.is_last_page,
            "stars": s.stars,
        }

    def snapshot(self) -> Optional[Dict[str, Any]]:
        """Return a full snapshot of the active session (for the /state route)."""
        if not self._session:
            return None
        event = self._page_event()
        event["status"] = self._session.status
        event["word_states"] = dict(self._session.word_states)
        return event

    # --- SSE fan-out (same pattern as StoryStore) ---

    def subscribe(self) -> asyncio.Queue[Dict[str, Any]]:
        """Register and return a new queue for receiving SSE events."""
        q: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[Dict[str, Any]]) -> None:
        """Remove a previously subscribed queue from the fan-out list."""
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    def _broadcast(self, data: Dict[str, Any]) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(data)
            except Exception:
                pass
