"""Tool for the robot to save important information to long-term memory."""

import logging
from typing import Any, Dict

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies

logger = logging.getLogger(__name__)


class SaveMemory(Tool):
    """Save an important piece of information to long-term memory."""

    name = "save_memory"
    description = (
        "Save important information to long-term memory so you can remember it "
        "in future conversations. Use this for: the user's name, age, preferences, "
        "favorite things, important facts they share, or a brief summary of the "
        "current conversation topic."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The information to remember (e.g. '小明今年5歲，喜歡恐龍').",
            },
            "memory_type": {
                "type": "string",
                "enum": ["fact", "summary"],
                "description": "Type of memory: 'fact' for user info/preferences, 'summary' for conversation summaries.",
            },
        },
        "required": ["content", "memory_type"],
    }

    def is_available(self) -> bool:
        return True

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        content = kwargs.get("content", "").strip()
        memory_type = kwargs.get("memory_type", "fact")

        if not content:
            return {"error": "content is required"}
        if memory_type not in ("fact", "summary"):
            return {"error": "memory_type must be 'fact' or 'summary'"}

        store = getattr(deps, "memory_store", None)
        if store is None:
            return {"error": "memory store not available"}

        entry = store.add(content, memory_type=memory_type)
        logger.info("Tool call: save_memory type=%s content=%r", memory_type, content[:80])
        return {"status": "saved", "id": entry["id"]}
