"""Tool: story_book_open - Load a persisted book from the library and open the reader."""

from __future__ import annotations
import base64
import logging
import webbrowser
from typing import Any, Dict, Optional

from reachy_mini_conversation_app.story_store import Story, StoryPage, StoryStore
from reachy_mini_conversation_app.book_library import BookLibrary
from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies


logger = logging.getLogger(__name__)


class StoryBookOpen(Tool):
    """Load a persisted book from the library and open the reader."""

    name = "story_book_open"
    description = (
        "從書架上載入一本已儲存的故事書並開始朗讀。"
        "如果不知道 book_id，呼叫此工具不帶參數來列出書架上的書。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "book_id": {
                "type": "string",
                "description": "要開啟的故事書 ID（從書架列表取得）",
            },
            "page": {
                "type": "integer",
                "description": "從哪一頁開始（從 1 開始，預設第 1 頁）",
            },
        },
        "required": [],
    }

    def is_available(self) -> bool:
        """Return True when a Gemini backend (AI Studio key or Vertex AI) is configured."""
        from reachy_mini_conversation_app.config import config

        return config.GEMINI_AVAILABLE

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        """List saved books, or load one by id and open the reader."""
        library = BookLibrary.get()
        book_id: Optional[str] = kwargs.get("book_id")

        # No book_id: return library listing so LLM can pick one
        if not book_id:
            books = library.list_books()
            if not books:
                return {"status": "empty", "message": "書架上還沒有故事書喔！"}
            listing = [
                {"id": b.id, "title": b.title, "page_count": library.page_count(b.id)}
                for b in books
            ]
            return {
                "status": "listing",
                "books": listing,
                "message": "書架上有這些故事書，請問小朋友想讀哪一本。",
            }

        # Load from disk
        meta = library.get_book(book_id)
        if meta is None:
            return {"error": f"找不到 book_id={book_id} 的故事書"}

        count = library.page_count(book_id)
        pages = []
        for i in range(count):
            text = library.page_text(book_id, i)
            img_path = library.page_image_path(book_id, i)
            if img_path:
                mime = "image/jpeg" if img_path.suffix in (".jpg", ".jpeg") else "image/png"
                image_b64 = base64.b64encode(img_path.read_bytes()).decode("ascii")
            else:
                image_b64, mime = "", "image/png"
            pages.append(StoryPage(text=text, image_b64=image_b64, image_mime=mime))

        story = Story(id=book_id, title=meta.title, pages=pages, status="ready")

        # Load into StoryStore (broadcasts story_ready, not generating)
        store = StoryStore.get()
        store.load_story(story)

        # Determine start page (1-based from LLM, convert to 0-based for URL)
        page_1based = kwargs.get("page", 1)
        page_0based = max(page_1based - 1, 0)

        # Update last read timestamp
        library.update_last_read(book_id)

        # Auto-open reader in browser (URL uses 0-based index)
        webbrowser.open(f"http://localhost:7860/reader/books/{book_id}?page={page_0based}")

        return {
            "status": "ok",
            "story_id": book_id,
            "title": story.title,
            "page_count": len(story.pages),
            "start_page": page_1based,
            "message": (
                f"已載入故事書「{story.title}」，共 {len(story.pages)} 頁。"
                f"請呼叫 story_book_go_to_page(page={page_1based}) 開始朗讀。"
            ),
        }
