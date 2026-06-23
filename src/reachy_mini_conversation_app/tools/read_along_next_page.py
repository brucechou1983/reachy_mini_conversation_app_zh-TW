"""Tool: read_along_next_page — turn to the next page of the read-along book.

Called once the child has finished reading the current page.  Returns the next
page's words and SEL prompt so the robot can invite the child to read on.
"""

from __future__ import annotations
import logging
from typing import Any, Dict

from reachy_mini_conversation_app.read_along_store import ReadAlongStore
from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies


logger = logging.getLogger(__name__)


class ReadAlongNextPage(Tool):
    """Advance the read-along to the next page."""

    name = "read_along_next_page"
    description = (
        "小朋友讀完這一頁後，翻到繪本的下一頁並顯示。"
        "回傳下一頁的英文字讓你邀請小朋友繼續讀。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        """Advance one page (or report that the last page was reached)."""
        store = ReadAlongStore.get()
        session = store.session
        if session is None:
            return {"error": "目前沒有正在進行的繪本帶讀"}

        if session.is_last_page:
            return {
                "status": "last_page",
                "message": (
                    "這是最後一頁了。讀完後問一個情緒問題，"
                    "再呼叫 read_along_finish(stars=N) 給小朋友星星獎勵。"
                ),
            }

        advanced = store.next_page()
        assert advanced is not None  # session exists and not last page
        page_idx, is_last = advanced
        page = session.current
        return {
            "status": "ok",
            "page": page_idx + 1,
            "total": session.total_pages,
            "page_text": page.text,
            "words": list(session.current_words),
            "tricky": list(page.tricky),
            "sel_prompt": page.sel_prompt,
            "is_last_page": is_last,
            "instruction": "邀請小朋友讀這一頁，他讀你聽。讀對就 read_along_cue success，再翻頁。",
        }
