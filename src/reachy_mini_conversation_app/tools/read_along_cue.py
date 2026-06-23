"""Tool: read_along_cue — flag a word in the reader with an Ello-style state.

The child reads; when the robot notices a tricky word it cues the reader UI.
``state="miss"`` auto-escalates per word (bounce -> highlight -> sound_out),
``"success"`` marks a word mastered.  The reader animates the matched word.
"""

from __future__ import annotations
import logging
from typing import Any, Dict

from reachy_mini_conversation_app.read_along_store import VALID_CUE_INPUTS, ReadAlongStore
from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies


logger = logging.getLogger(__name__)


class ReadAlongCue(Tool):
    """Highlight / animate a word on the current read-along page."""

    name = "read_along_cue"
    description = (
        "在繪本閱讀器上標記一個英文單字。"
        "state=miss（小朋友卡住，系統自動跳動→highlight→拆音）、"
        "success（讀對了，打勾慶祝）、sound_out（要拆音）、clear（清除標記）。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "word": {
                "type": "string",
                "description": "要標記的英文單字（例如 'happy'），或該字在頁面上的位置編號（0 起算）",
            },
            "state": {
                "type": "string",
                "enum": list(VALID_CUE_INPUTS),
                "description": "miss / success / sound_out / bounce / highlight / clear",
            },
        },
        "required": ["word", "state"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        """Resolve the word and broadcast its new visual state."""
        word = kwargs.get("word")
        state = (kwargs.get("state") or "").strip()
        if word is None or word == "":
            return {"error": "word is required"}
        if state not in VALID_CUE_INPUTS:
            return {"error": f"無效的 state，必須是 {list(VALID_CUE_INPUTS)} 之一"}

        store = ReadAlongStore.get()
        if store.session is None:
            return {"error": "目前沒有正在進行的繪本帶讀"}

        result = store.cue(word, state)
        if result is None:
            return {"error": f"在這一頁找不到單字「{word}」"}
        return {"status": "ok", **result}
