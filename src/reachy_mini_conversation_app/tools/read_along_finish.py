"""Tool: read_along_finish — end the read-along and show the star reward.

Called after the last page is read.  Awards stars, shows the reward screen in
the reader, and returns the book's warm closing message for the robot to read.
"""

from __future__ import annotations
import logging
from typing import Any, Dict

from reachy_mini_conversation_app.read_along_store import ReadAlongStore
from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies
from reachy_mini_conversation_app.read_along_progress import ReadAlongProgress


logger = logging.getLogger(__name__)

_DEFAULT_STARS = 3
_MAX_STARS = 5


class ReadAlongFinish(Tool):
    """Finish the read-along session and reward the child with stars."""

    name = "read_along_finish"
    description = (
        "結束繪本帶讀，在閱讀器上顯示星星獎勵畫面。"
        "讀完整本書、做完情緒對話後呼叫。stars 是給小朋友的星星數（1-5）。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "stars": {
                "type": "integer",
                "description": "給小朋友的星星數（1-5，預設 3）",
                "minimum": 1,
                "maximum": _MAX_STARS,
            },
        },
        "required": [],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        """Mark the session finished and return the reward + closing message."""
        store = ReadAlongStore.get()
        if store.session is None:
            return {"error": "目前沒有正在進行的繪本帶讀"}

        raw = kwargs.get("stars", _DEFAULT_STARS)
        try:
            stars = int(raw)
        except (TypeError, ValueError):
            stars = _DEFAULT_STARS
        stars = max(1, min(_MAX_STARS, stars))

        book_id = store.session.book_id
        result = store.finish(stars)
        assert result is not None
        # Persist completion so the bookshelf shows a green check next time.
        try:
            ReadAlongProgress.get().mark_completed(book_id, result["stars"])
        except Exception as e:  # never let persistence break the reward
            logger.warning("Failed to record read-along progress: %s", e)
        return {
            "status": "finished",
            "stars": result["stars"],
            "wrapup": result["wrapup"],
            "message": (
                f"太棒了！給你 {result['stars']} 顆星星！"
                "念出鼓勵的話，問問小朋友要不要再讀一本。"
            ),
        }
