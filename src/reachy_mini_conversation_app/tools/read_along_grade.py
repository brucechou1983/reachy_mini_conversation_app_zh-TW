"""Tool: read_along_grade — grade a whole read-along page in one call.

After the child reads a page aloud, the robot reports which words were read
correctly and which were misread or skipped.  Doing this in a single structured
call (instead of many ``read_along_cue`` calls) makes per-word grading reliable
and forces the model to account for *every* word — misread/skipped words get the
bounce→highlight→sound-out treatment, and the page only completes when all words
are green.
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List

from reachy_mini_conversation_app.read_along_store import ReadAlongStore
from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies


logger = logging.getLogger(__name__)


def _as_word_list(value: Any) -> List[str]:
    """Coerce a tool argument into a list of word strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [w for w in value.replace(",", " ").split() if w]
    if isinstance(value, list):
        return [str(w) for w in value if str(w).strip()]
    return []


class ReadAlongGrade(Tool):
    """Mark which words the child read correctly vs. misread, in one call."""

    name = "read_along_grade"
    requires_screen = True  # needs the on-screen reader
    description = (
        "小朋友讀完一整頁後，一次回報哪些英文字讀對(correct)、哪些讀錯或漏掉(incorrect)。"
        "仔細聽每一個字：只要有字沒讀對或漏掉，就要放進 incorrect，不要全部當成讀對。"
        "重聽重判：他重讀時若還是讀成原本的錯音（例如 scared 讀成 said）仍要放 incorrect，"
        "不要因為他試了第二次就放水——只有真的讀對才放 correct。"
        "系統會把對的標綠、錯的標記提示，並回傳還沒讀對的字。整頁全綠才能 read_along_next_page。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "correct": {
                "type": "array",
                "items": {"type": "string"},
                "description": "這一頁裡小朋友『讀對』的英文字",
            },
            "incorrect": {
                "type": "array",
                "items": {"type": "string"},
                "description": "讀錯、發音不對或漏掉的英文字",
            },
        },
        "required": [],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        """Grade the current page and report remaining (unread) words."""
        store = ReadAlongStore.get()
        if store.session is None:
            return {"error": "目前沒有正在進行的繪本帶讀"}

        correct = _as_word_list(kwargs.get("correct"))
        incorrect = _as_word_list(kwargs.get("incorrect"))
        if not correct and not incorrect:
            return {"error": "請至少回報 correct 或 incorrect 其中一組單字"}

        result = store.grade(correct, incorrect)
        assert result is not None
        remaining = result["remaining"]
        complete = result["complete"]
        if complete:
            message = "整頁都讀對了！可以呼叫 read_along_next_page() 翻頁，或在最後一頁呼叫 read_along_finish。"
        else:
            message = (
                f"還有 {len(remaining)} 個字要讀對：{', '.join(remaining)}。"
                "幫他們拆音、讀對後再 grade 一次。整頁全綠才能翻頁。"
            )
        return {
            "status": "ok",
            "complete": complete,
            "remaining_words": remaining,
            "message": message,
        }
