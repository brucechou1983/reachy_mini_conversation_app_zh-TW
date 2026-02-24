"""Tool: story_book_go_to_page - Navigate to a page and read it aloud.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies
from reachy_mini_conversation_app.story_store import StoryStore


logger = logging.getLogger(__name__)


class StoryBookGoToPage(Tool):
    """Navigate to a story page and trigger reading."""

    name = "story_book_go_to_page"
    description = (
        "翻到故事書的指定頁面，在閱讀器上顯示，並朗讀該頁內容。"
        "第一次呼叫時用 page=1 開始，之後遞增。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "page": {
                "type": "integer",
                "description": "要翻到的頁碼（從 1 開始，第一頁是 1）",
            },
        },
        "required": ["page"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        page_1based = kwargs.get("page", 1)
        page = max(page_1based - 1, 0)  # convert 1-based input to 0-based index
        logger.info("story_book_go_to_page called: page=%d (1-based=%d)", page, page_1based)

        store = StoryStore.get()
        story = store.story

        if not story or not story.pages:
            return {"error": "目前沒有故事書可以閱讀"}

        if story.status == "generating":
            return {"error": "故事還在產生中，請稍等一下"}

        sp = store.go_to_page(page)
        if sp is None:
            return {"error": "無效的頁碼"}

        actual_page = story.current_page  # 0-based, clamped by store.go_to_page
        total = len(story.pages)
        is_last = actual_page >= total - 1
        # Return 1-based page numbers to the LLM
        actual_page_1 = actual_page + 1
        next_page_1 = None if is_last else actual_page_1 + 1

        if is_last:
            instruction = (
                f"請用溫暖生動的語氣朗讀這一頁的故事內容給小朋友聽：「{sp.text}」"
                " 這是最後一頁，讀完後請呼叫 story_book_close 關閉閱讀器。"
            )
        else:
            instruction = (
                f"請用溫暖生動的語氣朗讀這一頁的故事內容給小朋友聽：「{sp.text}」"
                f" 朗讀完這一頁後，請呼叫 story_book_go_to_page(page={next_page_1}) 翻到下一頁。"
            )

        return {
            "status": "ok",
            "page": actual_page_1,
            "total": total,
            "is_last_page": is_last,
            "next_page": next_page_1,
            "page_text": sp.text,
            "instruction": instruction,
        }
