"""Tool: story_book_go_to_page - Navigate to a page and read it aloud.

TODO: Fix known issues:
1. Sometimes after go_to_page, the robot stops talking and doesn't read the page aloud.
2. Sometimes the robot advances to the next page too early before finishing the current page.
3. Off-by-one page index: telling the robot to go to the 5th page goes to the 6th instead.
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
        "第一次呼叫時用 page=0 開始，之後遞增。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "page": {
                "type": "integer",
                "description": "要翻到的頁碼（從 0 開始）",
            },
        },
        "required": ["page"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        page = kwargs.get("page", 0)
        logger.info("story_book_go_to_page called: page=%d", page)

        store = StoryStore.get()
        story = store.story

        if not story or not story.pages:
            return {"error": "目前沒有故事書可以閱讀"}

        if story.status == "generating":
            return {"error": "故事還在產生中，請稍等一下"}

        sp = store.go_to_page(page)
        if sp is None:
            return {"error": "無效的頁碼"}

        actual_page = story.current_page  # clamped value set by store.go_to_page
        total = len(story.pages)
        is_last = actual_page >= total - 1

        return {
            "status": "ok",
            "page": actual_page,
            "total": total,
            "is_last_page": is_last,
            "page_text": sp.text,
            "instruction": (
                f"請用溫暖生動的語氣朗讀這一頁的故事內容給小朋友聽：「{sp.text}」"
                + (
                    " 這是最後一頁了，讀完之後可以問小朋友喜不喜歡這個故事，然後呼叫 story_book_close 關閉故事書。"
                    if is_last
                    else " 只要朗讀這一頁就好，不要呼叫任何工具，系統會自動翻頁。"
                )
            ),
        }
