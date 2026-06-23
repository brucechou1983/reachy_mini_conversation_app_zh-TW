"""Hardware-free tests for the Gemini Live handler (no live session)."""

from unittest.mock import MagicMock

import pytest

import reachy_mini_conversation_app.gemini_realtime as gm
from reachy_mini_conversation_app.gemini_realtime import GeminiRealtimeHandler
from reachy_mini_conversation_app.conversation_handler import ConversationHandler


@pytest.mark.asyncio
async def test_is_conversation_handler():
    h = GeminiRealtimeHandler(MagicMock())
    assert isinstance(h, ConversationHandler)
    # input/output sample rates match Gemini Live requirements
    assert h.input_sample_rate == 16000
    assert h.output_sample_rate == 24000


@pytest.mark.asyncio
async def test_tool_spec_conversion(monkeypatch):
    monkeypatch.setattr(
        gm,
        "get_tool_specs",
        lambda: [
            {"type": "function", "name": "dance", "description": "d", "parameters": {"type": "object", "properties": {}}},
            {"type": "function", "name": "move_head", "description": "m", "parameters": {"type": "object", "properties": {}}},
            {"type": "other", "name": "ignored"},
        ],
    )
    h = GeminiRealtimeHandler(MagicMock())
    tools = h._convert_tool_specs_to_gemini_format()
    assert len(tools) == 1
    decls = tools[0]["function_declarations"]
    assert [d["name"] for d in decls] == ["dance", "move_head"]  # non-function entry dropped
    assert decls[0]["description"] == "d"


@pytest.mark.asyncio
async def test_copy_returns_fresh_instance():
    h = GeminiRealtimeHandler(MagicMock(), gradio_mode=True, instance_path="/tmp/x")
    h2 = h.copy()
    assert isinstance(h2, GeminiRealtimeHandler)
    assert h2 is not h
    assert h2.gradio_mode is True
    assert h2.instance_path == "/tmp/x"
