"""Tool: story_book_shelf - Open the visual reader bookshelf so the child can pick a book.

Opens the on-screen bookshelf (``http://localhost:7860/reader``) and returns the
saved-book list for reference. It does NOT load or read a book itself. The child can
then either tap a cover (which calls ``POST /reader/api/books/{id}/select`` -> the
robot is nudged to open & read it) or say the title (the model maps it to a book_id
and calls ``story_book_open``). Calling this tool also binds the live realtime handler
to ``StoryStore`` so a browser tap can reach the robot. Complements ``story_book_open``
(which lists books audio-only with no arg, and loads/narrates a book given an id).
"""

from __future__ import annotations
import asyncio
import logging
import webbrowser
from typing import Any, Dict

from reachy_mini_conversation_app.story_store import StoryStore
from reachy_mini_conversation_app.book_library import KIND_STORY, BookLibrary
from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies


logger = logging.getLogger(__name__)

SHELF_URL = "http://localhost:7860/reader"


class StoryBookShelf(Tool):
    """Open the visual story bookshelf for the child to choose a saved book."""

    name = "story_book_shelf"
    description = (
        "打開螢幕上的故事書架，顯示所有之前做好的故事書，讓小朋友可以用看的挑選想讀哪一本。"
        "這個工具只會打開書架頁面，不會載入故事；小朋友在螢幕上點封面，系統會自動通知你去開那本書，"
        "或是小朋友說出書名後，你再用 story_book_open 帶 book_id 開啟那本書來朗讀。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def is_available(self) -> bool:
        """Return True when a Gemini backend is configured (pairs with story_book_open)."""
        from reachy_mini_conversation_app.config import config

        return config.GEMINI_AVAILABLE

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        """Open the bookshelf page, bind the handler for taps, and return the book list."""
        # Bind the live handler so a browser tap on a cover can reach the robot.
        try:
            loop: Any = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover - defensive (no running loop)
            loop = None
        StoryStore.get().bind_handler(getattr(deps, "realtime_handler", None), loop)

        library = BookLibrary.get()
        books = library.list_books(kind=KIND_STORY)

        opened = False
        try:
            opened = bool(webbrowser.open(SHELF_URL))
        except Exception as e:  # never let a missing browser break the conversation
            logger.warning("Could not auto-open story bookshelf: %s", e)

        if not books:
            return {
                "status": "empty",
                "book_count": 0,
                "message": "書架上還沒有故事書喔！我們要不要先一起做一本新的故事書呢？",
            }

        listing = [
            {"id": b.id, "title": b.title, "page_count": library.page_count(b.id)}
            for b in books
        ]
        if opened:
            message = (
                "我把故事書架打開囉！螢幕上有我們之前做好的故事書，你想讀哪一本呢？"
                "可以直接點封面，或是告訴我書名，我就翻開來唸給你聽。"
                "（如果有兩本書名一樣，要先問清楚是哪一本再開。）"
            )
        else:
            # No screen/browser available — recite the titles instead of claiming a screen.
            titles = "、".join(str(b["title"]) for b in listing)
            message = (
                f"我們的書架上有這幾本故事書：{titles}。你想聽哪一本呢？"
                "告訴我書名，我就翻開來唸給你聽。"
            )
        return {
            "status": "ok",
            "shelf_opened": opened,
            "book_count": len(listing),
            "books": listing,
            "message": message,
        }
