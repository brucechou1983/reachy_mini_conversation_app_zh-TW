import asyncio
import logging
from typing import Any
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

import reachy_mini_conversation_app.openai_realtime as rt_mod
from reachy_mini_conversation_app.openai_realtime import OpenaiRealtimeHandler
from reachy_mini_conversation_app.tools.core_tools import ToolDependencies


def _build_handler(loop: asyncio.AbstractEventLoop) -> OpenaiRealtimeHandler:
    asyncio.set_event_loop(loop)
    deps = ToolDependencies(reachy_mini=MagicMock(), movement_manager=MagicMock())
    return OpenaiRealtimeHandler(deps)


def test_format_timestamp_uses_wall_clock() -> None:
    """Test that format_timestamp uses wall clock time."""
    loop = asyncio.new_event_loop()
    try:
        print("Testing format_timestamp...")
        handler = _build_handler(loop)
        formatted = handler.format_timestamp()
        print(f"Formatted timestamp: {formatted}")
    finally:
        asyncio.set_event_loop(None)
        loop.close()

    # Extract year from "[YYYY-MM-DD ...]"
    year = int(formatted[1:5])
    assert year == datetime.now(timezone.utc).year

@pytest.mark.asyncio
async def test_start_up_retries_on_abrupt_close(monkeypatch: Any, caplog: Any) -> None:
    """First connection dies with ConnectionClosedError during iteration -> retried.

    Second connection iterates cleanly (no events) -> start_up returns without raising.
    Ensures handler clears self.connection at the end.
    """
    caplog.set_level(logging.WARNING)

    # Use a local Exception as the module's ConnectionClosedError to avoid ws dependency
    FakeCCE = type("FakeCCE", (Exception,), {})
    monkeypatch.setattr(rt_mod, "ConnectionClosedError", FakeCCE)

    # Make asyncio.sleep return immediately (for backoff)
    async def _fast_sleep(*_a: Any, **_kw: Any) -> None: return None
    monkeypatch.setattr(asyncio, "sleep", _fast_sleep, raising=False)

    attempt_counter = {"n": 0}

    class FakeConn:
        """Minimal realtime connection stub."""

        def __init__(self, mode: str):
            self._mode = mode

            class _Session:
                async def update(self, **_kw: Any) -> None: return None
            self.session = _Session()

            class _InputAudioBuffer:
                async def append(self, **_kw: Any) -> None: return None
            self.input_audio_buffer = _InputAudioBuffer()

            class _Item:
                async def create(self, **_kw: Any) -> None: return None

            class _Conversation:
                item = _Item()
            self.conversation = _Conversation()

            class _Response:
                async def create(self, **_kw: Any) -> None: return None
                async def cancel(self, **_kw: Any) -> None: return None
            self.response = _Response()

        async def __aenter__(self) -> "FakeConn": return self
        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool: return False
        async def close(self) -> None: return None

        # Async iterator protocol
        def __aiter__(self) -> "FakeConn": return self
        async def __anext__(self) -> None:
            if self._mode == "raise_on_iter":
                raise FakeCCE("abrupt close (simulated)")
            raise StopAsyncIteration  # clean exit (no events)

    class FakeRealtime:
        def connect(self, **_kw: Any) -> FakeConn:
            attempt_counter["n"] += 1
            mode = "raise_on_iter" if attempt_counter["n"] == 1 else "clean"
            return FakeConn(mode)

    class FakeClient:
        def __init__(self, **_kw: Any) -> None: self.realtime = FakeRealtime()

    # Patch the OpenAI client used by the handler
    monkeypatch.setattr(rt_mod, "AsyncOpenAI", FakeClient)

    # Build handler with minimal deps
    deps = ToolDependencies(reachy_mini=MagicMock(), movement_manager=MagicMock())
    handler = rt_mod.OpenaiRealtimeHandler(deps)

    # Run: should retry once and exit cleanly
    await handler.start_up()

    # Validate: two attempts total (fail -> retry -> succeed), and connection cleared
    assert attempt_counter["n"] == 2
    assert handler.connection is None

    # Optional: confirm we logged the abrupt close once
    warnings = [r for r in caplog.records if r.levelname == "WARNING" and "websocket closed" in r.msg]
    assert len(warnings) == 1


@pytest.mark.asyncio
async def test_inject_user_text_creates_item_and_response() -> None:
    """inject_user_text adds a user message and triggers a response."""
    handler = _build_handler(asyncio.new_event_loop())
    try:
        captured: dict = {}

        class _Item:
            async def create(self, item: Any = None) -> None:
                captured["item"] = item

        class _Conversation:
            item = _Item()

        class _Response:
            async def create(self, **_kw: Any) -> None:
                captured["response"] = True

        class _Conn:
            conversation = _Conversation()
            response = _Response()

        handler.connection = _Conn()  # type: ignore[assignment]
        await handler.inject_user_text("讀這個字")

        assert captured["item"]["role"] == "user"
        assert captured["item"]["content"][0]["text"] == "讀這個字"
        assert captured["response"] is True
    finally:
        asyncio.set_event_loop(None)


@pytest.mark.asyncio
async def test_inject_user_text_no_connection_is_noop() -> None:
    """No live connection -> inject is a safe no-op."""
    handler = _build_handler(asyncio.new_event_loop())
    try:
        handler.connection = None
        await handler.inject_user_text("x")  # must not raise
    finally:
        asyncio.set_event_loop(None)


@pytest.mark.asyncio
async def test_inject_user_text_respond_false_skips_response() -> None:
    """respond=False adds the item without creating a response."""
    handler = _build_handler(asyncio.new_event_loop())
    try:
        captured: dict = {"response": False}

        class _Item:
            async def create(self, item: Any = None) -> None:
                captured["item"] = item

        class _Conversation:
            item = _Item()

        class _Response:
            async def create(self, **_kw: Any) -> None:
                captured["response"] = True

        class _Conn:
            conversation = _Conversation()
            response = _Response()

        handler.connection = _Conn()  # type: ignore[assignment]
        await handler.inject_user_text("hi", respond=False)
        assert "item" in captured
        assert captured["response"] is False
    finally:
        asyncio.set_event_loop(None)
