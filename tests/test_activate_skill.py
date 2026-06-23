"""Tests for the activate_skill tool (english_learner profile).

Hardware-free: the tool only reads SKILL.md files from disk and never
touches the robot, network, or OpenAI. ``deps`` is a throwaway MagicMock
because the tool ignores it.
"""

from unittest.mock import MagicMock

import pytest

from reachy_mini_conversation_app.config import config
from reachy_mini_conversation_app.skills import scan_skills
from reachy_mini_conversation_app.profiles.english_learner.activate_skill import (
    ActivateSkill,
)


@pytest.fixture()
def english_profile(monkeypatch):
    """Make the active profile english_learner for the duration of a test."""
    monkeypatch.setattr(config, "REACHY_MINI_CUSTOM_PROFILE", "english_learner")


@pytest.fixture()
def tool() -> ActivateSkill:
    return ActivateSkill()


@pytest.mark.asyncio
async def test_activate_known_skill(tool, english_profile):
    result = await tool(MagicMock(), skill_name="color-detective")
    assert result["status"] == "skill_activated"
    assert result["skill"] == "color-detective"
    # body of color-detective/SKILL.md was loaded
    assert "顏色" in result["instruction"]


@pytest.mark.asyncio
async def test_blank_skill_name_errors(tool, english_profile):
    result = await tool(MagicMock(), skill_name="   ")
    assert "error" in result


@pytest.mark.asyncio
async def test_missing_skill_name_errors(tool, english_profile):
    result = await tool(MagicMock())
    assert "error" in result


@pytest.mark.asyncio
async def test_unknown_skill_lists_available(tool, english_profile):
    result = await tool(MagicMock(), skill_name="does-not-exist")
    assert "error" in result
    # the error message should help the model recover by listing real skills
    assert "color-detective" in result["error"]


@pytest.mark.asyncio
async def test_every_advertised_skill_round_trips(tool, english_profile):
    """Every skill the catalog advertises must activate to a non-empty body."""
    entries = scan_skills("english_learner")
    assert entries  # sanity: the profile actually has skills

    for entry in entries:
        result = await tool(MagicMock(), skill_name=entry.name)
        assert result.get("status") == "skill_activated", entry.name
        assert result["instruction"], entry.name
