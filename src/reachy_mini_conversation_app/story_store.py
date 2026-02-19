"""In-process store for story state and SSE fan-out."""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


@dataclass
class StoryPage:
    """A single page of a story book."""

    text: str
    image_b64: str = ""  # base64 PNG/JPEG
    image_mime: str = "image/png"


@dataclass
class Story:
    """A complete generated story."""

    id: str
    title: str
    pages: List[StoryPage] = field(default_factory=list)
    current_page: int = 0
    status: str = "generating"  # generating | ready | reading | closed


class StoryStore:
    """Singleton in-process store for the active story.

    Provides SSE fan-out via asyncio Queues so the reader frontend can
    receive real-time updates.
    """

    _instance: Optional[StoryStore] = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self._story: Optional[Story] = None
        self._subscribers: List[asyncio.Queue[Dict[str, Any]]] = []

    @classmethod
    def get(cls) -> StoryStore:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @property
    def story(self) -> Optional[Story]:
        return self._story

    def create_story(self, title: str) -> Story:
        story = Story(id=str(uuid.uuid4()), title=title)
        self._story = story
        self._broadcast({"event": "generating", "title": title})
        return story

    def set_story_ready(self, story_id: str, pages: List[StoryPage]) -> None:
        if self._story and self._story.id == story_id:
            self._story.pages = pages
            self._story.status = "ready"
            self._broadcast({
                "event": "story_ready",
                "story_id": story_id,
                "title": self._story.title,
                "page_count": len(pages),
            })

    def go_to_page(self, page: int) -> Optional[StoryPage]:
        if not self._story or not self._story.pages:
            return None
        page = max(0, min(page, len(self._story.pages) - 1))
        self._story.current_page = page
        self._story.status = "reading"
        sp = self._story.pages[page]
        self._broadcast({
            "event": "page_change",
            "page": page,
            "total": len(self._story.pages),
            "text": sp.text,
            "image_b64": sp.image_b64,
            "image_mime": sp.image_mime,
        })
        return sp

    def close_story(self) -> None:
        if self._story:
            self._story.status = "closed"
        self._broadcast({"event": "story_closed"})
        self._story = None

    # --- SSE fan-out ---

    def subscribe(self) -> asyncio.Queue[Dict[str, Any]]:
        q: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[Dict[str, Any]]) -> None:
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
