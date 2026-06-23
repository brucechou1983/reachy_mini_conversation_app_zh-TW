"""Tool for the robot to save profile-specific activity summaries."""

import logging
from typing import Any, Dict

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies


logger = logging.getLogger(__name__)


class SaveProfileMemory(Tool):
    """Save a profile-activity summary to per-profile long-term memory."""

    name = "save_profile_memory"
    description = (
        "Save a summary of what happened during this persona's activities to "
        "per-profile memory. Use this to remember what games were played, what "
        "topics were explored, what challenges the user completed, or notable "
        "moments specific to this robot persona's context."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The activity summary to remember (e.g. '小明完成了三道加法題，對乘法還不熟悉').",
            },
            "memory_type": {
                "type": "string",
                "enum": ["fact", "event"],
                "description": "Type: 'fact' for profile-specific preferences, 'event' for session activity recaps.",
            },
        },
        "required": ["content", "memory_type"],
    }

    def is_available(self) -> bool:
        """Return True only when a custom profile is active."""
        from reachy_mini_conversation_app.config import config

        return bool(config.REACHY_MINI_CUSTOM_PROFILE)

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        """Save the given activity summary to per-profile memory."""
        content = kwargs.get("content", "").strip()
        memory_type = kwargs.get("memory_type", "fact")

        if not content:
            return {"error": "content is required"}
        if memory_type not in ("fact", "event"):
            return {"error": "memory_type must be 'fact' or 'event'"}

        store = getattr(deps, "profile_memory_store", None)
        if store is None:
            return {"error": "profile memory store not available (no active profile)"}

        entry = store.add(content, memory_type=memory_type)
        logger.info("Tool call: save_profile_memory type=%s content=%r", memory_type, content[:80])
        return {"status": "saved", "id": entry["id"]}
