"""Tool for the robot to remove outdated or incorrect memories."""

import logging
from typing import Any, Dict

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies


logger = logging.getLogger(__name__)


class ForgetMemory(Tool):
    """Remove a specific memory from long-term storage."""

    name = "forget_memory"
    description = (
        "Remove a specific memory that is outdated, incorrect, or no longer relevant. "
        "You must provide the memory ID. Use this when the user corrects previously "
        "stored information or asks you to forget something."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "memory_id": {
                "type": "string",
                "description": "The ID of the memory to remove (shown in brackets in your memory list, e.g. 'a1b2c3d4').",
            },
        },
        "required": ["memory_id"],
    }

    def is_available(self) -> bool:
        """Return True; this tool is always enabled."""
        return True

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        """Remove the memory with the given id from long-term storage."""
        memory_id = kwargs.get("memory_id", "").strip()
        if not memory_id:
            return {"error": "memory_id is required"}

        store = getattr(deps, "memory_store", None)
        if store is None:
            return {"error": "memory store not available"}

        removed = store.remove(memory_id)
        logger.info("Tool call: forget_memory id=%s removed=%s", memory_id, removed)
        if removed:
            return {"status": "removed", "id": memory_id}
        return {"error": f"memory with id '{memory_id}' not found"}
