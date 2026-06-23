"""Tool to activate an Agent Skill by loading its full SKILL.md instructions."""

import logging
from typing import Any, Dict

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies
from reachy_mini_conversation_app.skills import scan_skills
from reachy_mini_conversation_app.config import config

logger = logging.getLogger(__name__)


class ActivateSkill(Tool):
    name = "activate_skill"
    description = (
        "Start a game/skill by name. "
        "Returns the full game rules and instructions. "
        "Available skills are listed in the system prompt."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "skill_name": {
                "type": "string",
                "description": "Name of the skill to activate (e.g. 'color-detective', 'simon-says')",
            },
        },
        "required": ["skill_name"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        skill_name = (kwargs.get("skill_name") or "").strip()
        if not skill_name:
            return {"error": "skill_name is required"}

        profile = config.REACHY_MINI_CUSTOM_PROFILE or "default"
        entries = scan_skills(profile)

        for entry in entries:
            if entry.name == skill_name:
                body = entry.load_body()
                logger.info("Activated skill: %s (%d chars)", skill_name, len(body))
                return {
                    "status": "skill_activated",
                    "skill": skill_name,
                    "instruction": body,
                }

        available = [e.name for e in entries]
        return {"error": f"Skill '{skill_name}' not found. Available: {available}"}
