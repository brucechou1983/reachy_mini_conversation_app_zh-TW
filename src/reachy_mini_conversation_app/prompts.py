import re
import sys
import logging
from typing import Any
from pathlib import Path

from reachy_mini_conversation_app.config import config
from reachy_mini_conversation_app.skills import scan_skills, format_catalog


logger = logging.getLogger(__name__)


PROFILES_DIRECTORY = Path(__file__).parent / "profiles"
PROMPTS_LIBRARY_DIRECTORY = Path(__file__).parent / "prompts"
INSTRUCTIONS_FILENAME = "instructions.txt"
VOICE_FILENAME = "voice.txt"


def _expand_prompt_includes(content: str) -> str:
    """Expand [<name>] placeholders with content from prompts library files.

    Args:
        content: The template content with [<name>] placeholders

    Returns:
        Expanded content with placeholders replaced by file contents

    """
    # Pattern to match [<name>] where name is a valid file stem (alphanumeric, underscores, hyphens)
    # pattern = re.compile(r'^\[([a-zA-Z0-9_-]+)\]$')
    # Allow slashes for subdirectories
    pattern = re.compile(r'^\[([a-zA-Z0-9/_-]+)\]$')

    lines = content.split('\n')
    expanded_lines = []

    for line in lines:
        stripped = line.strip()
        match = pattern.match(stripped)

        if match:
            # Extract the name from [<name>]
            template_name = match.group(1)
            template_file = PROMPTS_LIBRARY_DIRECTORY / f"{template_name}.txt"

            try:
                if template_file.exists():
                    template_content = template_file.read_text(encoding="utf-8").rstrip()
                    expanded_lines.append(template_content)
                    logger.debug("Expanded template: [%s]", template_name)
                else:
                    logger.warning("Template file not found: %s, keeping placeholder", template_file)
                    expanded_lines.append(line)
            except Exception as e:
                logger.warning("Failed to read template '%s': %s, keeping placeholder", template_name, e)
                expanded_lines.append(line)
        else:
            expanded_lines.append(line)

    return '\n'.join(expanded_lines)


def _screen_mode_note() -> str:
    """Note appended when no screen is available — only for profiles with screen tools.

    Skipped entirely when a screen is present, or when the active profile has no
    screen-dependent tools (so we never inject children's-book wording into an
    unrelated persona).
    """
    if config.SCREEN_AVAILABLE:
        return ""
    # Lazy import to avoid a circular import at module load.
    from reachy_mini_conversation_app.tools.core_tools import _ALL_TOOL_INSTANCES

    if not any(getattr(t, "requires_screen", False) for t in _ALL_TOOL_INSTANCES.values()):
        return ""
    return (
        "## 目前沒有螢幕\n"
        "這台汪汪現在沒有接螢幕，需要看畫面的功能（做故事書、故事書架、英文繪本帶讀）都暫停了，"
        "相關工具也不會出現。請專心用「不用螢幕」的方式陪小朋友：聊天、口頭說故事、唱歌、數數、"
        "猜謎、玩問答等等。不要說要做故事書或開繪本給他看，也不要主動問他要「聽故事還是讀英文」，"
        "更不要嘗試呼叫那些需要螢幕的工具。"
    )


def get_session_instructions(
    memory_store: Any | None = None,
    profile_memory_store: Any | None = None,
) -> str:
    """Get session instructions, loading from REACHY_MINI_CUSTOM_PROFILE if set.

    If a ``MemoryStore`` is provided, its contents are appended to the
    instructions so the robot has access to long-term memories.  A separate
    ``profile_memory_store`` adds per-profile activity summaries.
    """
    profile = config.REACHY_MINI_CUSTOM_PROFILE
    if not profile:
        logger.info(f"Loading default prompt from {PROMPTS_LIBRARY_DIRECTORY / 'default_prompt.txt'}")
        instructions_file = PROMPTS_LIBRARY_DIRECTORY / "default_prompt.txt"
    else:
        logger.info(f"Loading prompt from profile '{profile}'")
        instructions_file = PROFILES_DIRECTORY / profile / INSTRUCTIONS_FILENAME

    try:
        if instructions_file.exists():
            instructions = instructions_file.read_text(encoding="utf-8").strip()
            if instructions:
                # Expand [<name>] placeholders with content from prompts library
                expanded_instructions = _expand_prompt_includes(instructions)

                # Append long-term memories if available
                if memory_store is not None:
                    memory_block = memory_store.format_for_prompt()
                    if memory_block:
                        expanded_instructions = expanded_instructions + "\n\n" + memory_block

                # Append per-profile activity memories if available
                if profile_memory_store is not None:
                    profile_block = profile_memory_store.format_for_prompt()
                    if profile_block:
                        expanded_instructions = expanded_instructions + "\n\n" + profile_block

                # Append skill catalog if the profile has Agent Skills
                skill_entries = scan_skills(profile or "default")
                skill_catalog = format_catalog(skill_entries)
                if skill_catalog:
                    expanded_instructions = expanded_instructions + "\n\n" + skill_catalog

                # When there is no screen, tell the model the visual features are off.
                screen_note = _screen_mode_note()
                if screen_note:
                    expanded_instructions = expanded_instructions + "\n\n" + screen_note

                return expanded_instructions
            logger.error(f"Profile '{profile}' has empty {INSTRUCTIONS_FILENAME}")
            sys.exit(1)
        logger.error(f"Profile {profile} has no {INSTRUCTIONS_FILENAME}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Failed to load instructions from profile '{profile}': {e}")
        sys.exit(1)


def get_session_voice(default: str = "coral") -> str:
    """Resolve the voice to use for the session.

    If a custom profile is selected and contains a voice.txt, return its
    trimmed content; otherwise return the provided default ("coral").
    """
    profile = config.REACHY_MINI_CUSTOM_PROFILE
    if not profile:
        return default
    try:
        voice_file = PROFILES_DIRECTORY / profile / VOICE_FILENAME
        if voice_file.exists():
            voice = voice_file.read_text(encoding="utf-8").strip()
            return voice or default
    except Exception:
        pass
    return default
