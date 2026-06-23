"""Tool for the robot to remove outdated per-profile activity memories."""

import logging
from typing import Any, Dict

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies


logger = logging.getLogger(__name__)


class ForgetProfileMemory(Tool):
    """Remove a specific per-profile memory entry."""

    name = "forget_profile_memory"
    description = (
        "Remove a specific per-profile activity memory that is outdated or "
        "incorrect. You must provide the memory ID shown in brackets in your "
        "profile memory list."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "memory_id": {
                "type": "string",
                "description": "The ID of the profile memory to remove (e.g. 'a1b2c3d4').",
            },
        },
        "required": ["memory_id"],
    }

    def is_available(self) -> bool:
        """Return True only when a custom profile is active."""
        from reachy_mini_conversation_app.config import config

        return bool(config.REACHY_MINI_CUSTOM_PROFILE)

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        """Remove the given per-profile memory entry by id."""
        memory_id = kwargs.get("memory_id", "").strip()
        if not memory_id:
            return {"error": "memory_id is required"}

        store = getattr(deps, "profile_memory_store", None)
        if store is None:
            return {"error": "profile memory store not available (no active profile)"}

        removed = store.remove(memory_id)
        logger.info("Tool call: forget_profile_memory id=%s removed=%s", memory_id, removed)
        if removed:
            return {"status": "removed", "id": memory_id}
        return {"error": f"profile memory with id '{memory_id}' not found"}
