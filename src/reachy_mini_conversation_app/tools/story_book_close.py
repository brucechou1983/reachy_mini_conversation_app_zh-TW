"""Tool: story_book_close - Close the story reader."""

from __future__ import annotations

import logging
from typing import Any, Dict

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies
from reachy_mini_conversation_app.story_store import StoryStore


logger = logging.getLogger(__name__)


class StoryBookClose(Tool):
    """Close the story reader UI."""

    name = "story_book_close"
    description = "關閉故事書閱讀器。故事說完後呼叫此工具。"
    parameters_schema = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        logger.info("story_book_close called")
        store = StoryStore.get()
        store.close_story()
        return {"status": "closed", "message": "故事書已經關上了。"}
