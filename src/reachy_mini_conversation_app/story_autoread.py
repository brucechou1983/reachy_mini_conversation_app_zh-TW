"""Shared story auto-read state machine for both conversation backends.

The storyteller reads a picture book one page at a time: narrate a page, wait for
its audio to finish playing, fetch the next page, narrate it, and close the reader
after the last page. This logic was originally OpenAI-only (and gated on the
OpenAI ``connection`` object), so the Gemini backend never read books. It now
lives here and both ``OpenaiRealtimeHandler`` and ``GeminiRealtimeHandler`` mix it
in.

Each handler provides one backend-specific primitive, ``_story_request_narration``
(inject the page text and make the model read it aloud), and drives the machine by
calling the hooks from its own event loop:

* ``note_story_audio(n_samples)`` — per output audio chunk, to time the advance,
* ``story_turn_finished()`` — when a model turn ends, to schedule the next page,
* ``cancel_story_advance()`` — on barge-in, so a child interrupting stops the loop,
* ``begin_story_autoread(page)`` — to kick the loop off (e.g. when a book is ready),
* ``apply_story_page_result(result)`` — for a *model*-initiated ``go_to_page``.
"""

from __future__ import annotations
import json
import asyncio
import logging
from typing import Any, Dict, Optional

from fastrtc import AdditionalOutputs

from reachy_mini_conversation_app.tools.core_tools import dispatch_tool_call


logger = logging.getLogger(__name__)

_STORY_CLOSE_PROMPT = (
    "故事說完了，用溫暖的口氣跟小朋友說故事結束了，問他喜不喜歡這個故事。請使用台灣中文。"
)


class StoryReaderMixin:
    """Backend-agnostic page-by-page story narration loop.

    Concrete handlers must define ``deps``, ``output_queue`` and
    ``output_sample_rate``, and implement ``_story_request_narration``.
    """

    # Provided by the concrete handler.
    deps: Any
    output_queue: "asyncio.Queue[Any]"
    output_sample_rate: int

    def _init_story_state(self) -> None:
        """Initialise auto-read state (call from the handler's ``__init__``)."""
        self._story_next_page: Optional[int] = None
        self._story_is_last_page: bool = False
        self._story_advance_task: Optional[asyncio.Task[None]] = None
        self._story_audio_start: Optional[float] = None
        self._story_audio_samples: int = 0

    # ------------------------------------------------------------------
    # Backend-specific primitive
    # ------------------------------------------------------------------
    async def _story_request_narration(self, instruction: str) -> None:
        """Inject the page text and make the model read it aloud (per backend)."""
        raise NotImplementedError

    async def _story_wait_idle(self) -> None:
        """Optionally wait until no response is in progress before narrating."""
        idle = getattr(self, "response_idle", None)
        if idle is not None:
            try:
                await idle.wait()
            except Exception:  # pragma: no cover - defensive
                pass

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------
    def cancel_story_advance(self) -> None:
        """Stop the auto-read loop and clear its state (e.g. on barge-in)."""
        task = getattr(self, "_story_advance_task", None)
        if task is not None and not task.done():
            task.cancel()
            logger.info("Story auto-advance cancelled")
        self._story_next_page = None
        self._story_is_last_page = False
        self._story_advance_task = None
        self._story_audio_start = None
        self._story_audio_samples = 0

    def _estimate_remaining_audio(self) -> float:
        """Seconds of narration audio still expected to play, plus a 1s buffer."""
        sr = self.output_sample_rate or 24000
        audio_dur = self._story_audio_samples / sr
        elapsed = (
            (asyncio.get_event_loop().time() - self._story_audio_start)
            if self._story_audio_start
            else 0.0
        )
        return max(0.0, audio_dur - elapsed) + 1.0

    def note_story_audio(self, num_samples: int) -> None:
        """Accumulate narration audio so the next page is timed to its end."""
        if self._story_next_page is not None or self._story_is_last_page:
            if self._story_audio_start is None:
                self._story_audio_start = asyncio.get_event_loop().time()
            self._story_audio_samples += int(num_samples)

    def story_turn_finished(self) -> None:
        """When a model turn ends, schedule the next page / close if we narrated one."""
        if self._story_audio_samples <= 0:
            return
        if self._story_advance_task is not None and not self._story_advance_task.done():
            return  # an advance is already pending
        if self._story_next_page is not None:
            wait = self._estimate_remaining_audio()
            self._story_advance_task = asyncio.create_task(
                self._story_auto_advance(self._story_next_page, wait)
            )
        elif self._story_is_last_page:
            wait = self._estimate_remaining_audio()
            self._story_advance_task = asyncio.create_task(self._story_auto_close(wait))

    async def apply_story_page_result(self, tool_result: Dict[str, Any]) -> None:
        """Record next-page state from a ``go_to_page`` result and narrate this page.

        Use this when the *model* called ``story_book_go_to_page`` itself (e.g. the
        child asked to jump to a page); the auto-advance loop calls it internally.
        """
        self._story_next_page = tool_result.get("next_page")
        self._story_is_last_page = bool(tool_result.get("is_last_page", False))
        self._story_audio_start = None
        self._story_audio_samples = 0
        await self._story_request_narration(tool_result.get("instruction", ""))

    async def begin_story_autoread(self, page: int = 1) -> None:
        """Kick off client-driven reading from ``page`` (book ready / manual start)."""
        self.cancel_story_advance()
        self._story_advance_task = asyncio.create_task(self._story_auto_advance(page, 0.0))

    async def _story_auto_advance(self, page: int, wait_seconds: float) -> None:
        """Wait for the current page's audio to finish, then narrate ``page``."""
        try:
            if wait_seconds:
                logger.info("Story auto-advance: waiting %.1fs before page %s", wait_seconds, page)
                await asyncio.sleep(wait_seconds)
            await self._story_wait_idle()
            result = await dispatch_tool_call(
                "story_book_go_to_page", json.dumps({"page": page}), self.deps
            )
            await self._push_story_log(result)
            if result.get("status") == "ok":
                await self.apply_story_page_result(result)
            else:
                logger.warning("Story auto-advance failed: %s", result)
                self._story_next_page = None
                self._story_is_last_page = False
        except asyncio.CancelledError:
            logger.info("Story auto-advance to page %s cancelled", page)

    async def _story_auto_close(self, wait_seconds: float) -> None:
        """Wait for the last page's audio to finish, then close and wrap up."""
        try:
            if wait_seconds:
                await asyncio.sleep(wait_seconds)
            await self._story_wait_idle()
            result = await dispatch_tool_call("story_book_close", "{}", self.deps)
            await self._push_story_log(result)
            self._story_next_page = None
            self._story_is_last_page = False
            await self._story_request_narration(_STORY_CLOSE_PROMPT)
        except asyncio.CancelledError:
            logger.info("Story auto-close cancelled")

    async def _push_story_log(self, result: Dict[str, Any]) -> None:
        """Mirror a story tool result into the UI chat log."""
        try:
            await self.output_queue.put(
                AdditionalOutputs({"role": "assistant", "content": json.dumps(result, ensure_ascii=False)})
            )
        except Exception:  # pragma: no cover - defensive
            pass
