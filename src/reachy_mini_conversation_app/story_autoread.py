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
        # Accurate page-turn timing: play_loop measures the ACTUAL pushed (post
        # time-stretch) audio for the current page and, when it reaches the
        # ``story_audio_done`` sentinel, reports how much is still buffered to play
        # via ``_story_playback_remaining`` + sets ``_story_playback_done``.
        self._story_playback_done: Optional[asyncio.Event] = None
        self._story_playback_remaining: float = 0.0

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
        self._story_playback_done = None
        self._story_playback_remaining = 0.0

    def _estimate_remaining_audio(self) -> float:
        """Seconds of narration audio still expected to play, plus a tail buffer.

        ``audio_dur`` is the *playout* duration: the raw sample count is stretched
        by ``SPEECH_SLOWDOWN`` because the player time-stretches output audio, so
        it actually plays longer than the raw samples imply. Without this the page
        turns before the (slowed) narration finishes.
        """
        from reachy_mini_conversation_app.config import config
        from reachy_mini_conversation_app.audio_pace import get_speech_slowdown

        sr = self.output_sample_rate or 24000
        slowdown = get_speech_slowdown()  # >=1.0; 1.0 = off (no stretch)
        audio_dur = (self._story_audio_samples / sr) * slowdown
        elapsed = (
            (asyncio.get_event_loop().time() - self._story_audio_start)
            if self._story_audio_start
            else 0.0
        )
        try:
            buffer = float(getattr(config, "STORY_PAGE_TURN_BUFFER_S", 1.0))
        except (TypeError, ValueError):
            buffer = 1.0
        remaining = max(0.0, audio_dur - elapsed) + buffer
        logger.info(
            "story: page-turn in %.1fs (dur=%.1f×%.2f elapsed=%.1f buffer=%.1f)",
            remaining, self._story_audio_samples / sr, slowdown, elapsed, buffer,
        )
        return remaining

    def note_story_audio(self, num_samples: int) -> None:
        """Accumulate narration audio so the next page is timed to its end."""
        if self._story_next_page is not None or self._story_is_last_page:
            if self._story_audio_start is None:
                logger.info("story: narration audio started (next_page=%s)", self._story_next_page)
                self._story_audio_start = asyncio.get_event_loop().time()
            self._story_audio_samples += int(num_samples)

    def story_turn_finished(self) -> None:
        """When a model turn ends, schedule the next page / close if we narrated one."""
        pending = self._story_advance_task is not None and not self._story_advance_task.done()
        logger.info(
            "story: turn finished (samples=%s next_page=%s last=%s task_pending=%s)",
            self._story_audio_samples, self._story_next_page, self._story_is_last_page, pending,
        )
        if self._story_audio_samples <= 0:
            return
        if pending:
            return  # an advance is already pending
        # Drop a sentinel BEHIND all of this page's audio chunks. play_loop will
        # reach it once everything has been pushed and report the exact remaining
        # playout time (accurate; includes time-stretch) via the event below.
        try:
            self.output_queue.put_nowait(AdditionalOutputs({"role": "story_audio_done"}))
        except Exception:  # pragma: no cover - defensive
            pass
        if self._story_next_page is not None:
            self._story_advance_task = asyncio.create_task(self._story_auto_advance(self._story_next_page))
        elif self._story_is_last_page:
            self._story_advance_task = asyncio.create_task(self._story_auto_close())

    async def apply_story_page_result(self, tool_result: Dict[str, Any]) -> None:
        """Record next-page state from a ``go_to_page`` result and narrate this page.

        Use this when the *model* called ``story_book_go_to_page`` itself (e.g. the
        child asked to jump to a page); the auto-advance loop calls it internally.
        """
        self._story_next_page = tool_result.get("next_page")
        self._story_is_last_page = bool(tool_result.get("is_last_page", False))
        self._story_audio_start = None
        self._story_audio_samples = 0
        # Arm playout tracking for THIS page so play_loop counts its pushed audio.
        self._story_playback_done = asyncio.Event()
        self._story_playback_remaining = 0.0
        logger.info(
            "story: narrating page=%s (next=%s last=%s)",
            tool_result.get("page"), self._story_next_page, self._story_is_last_page,
        )
        await self._story_request_narration(tool_result.get("instruction", ""))

    async def begin_story_autoread(self, page: int = 1) -> None:
        """Kick off client-driven reading from ``page`` (book ready / manual start)."""
        logger.info("story: begin auto-read from page=%s (%s)", page, type(self).__name__)
        self.cancel_story_advance()
        # First page: nothing is playing yet, so don't wait for prior playout.
        self._story_advance_task = asyncio.create_task(
            self._story_auto_advance(page, wait_playback=False)
        )

    def _page_turn_buffer(self) -> float:
        """Extra seconds to wait after a page finishes before turning it."""
        from reachy_mini_conversation_app.config import config

        try:
            return float(getattr(config, "STORY_PAGE_TURN_BUFFER_S", 1.0))
        except (TypeError, ValueError):
            return 1.0

    async def _story_wait_for_playback(self) -> None:
        """Block until the current page's narration has actually finished playing.

        Primary path: the play_loop sentinel reports the exact remaining buffered
        playout (accurate, time-stretch-aware). Fallback (e.g. a transport with no
        sentinel-aware play_loop): the duration estimate.
        """
        ev = self._story_playback_done
        if ev is not None:
            try:
                await asyncio.wait_for(ev.wait(), timeout=180.0)
                wait = max(0.0, self._story_playback_remaining) + self._page_turn_buffer()
                logger.info("story: playback done, turning page in %.1fs", wait)
                await asyncio.sleep(wait)
                return
            except asyncio.TimeoutError:
                logger.warning("story: playback sentinel timed out; using duration estimate")
        await asyncio.sleep(self._estimate_remaining_audio())

    async def _story_auto_advance(self, page: int, wait_playback: bool = True) -> None:
        """Wait for the current page's audio to finish, then narrate ``page``."""
        try:
            logger.info("story: auto-advance to page=%s (wait_playback=%s)", page, wait_playback)
            if wait_playback:
                await self._story_wait_for_playback()
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

    async def _story_auto_close(self) -> None:
        """Wait for the last page's audio to finish, then close and wrap up."""
        try:
            await self._story_wait_for_playback()
            await self._story_wait_idle()
            result = await dispatch_tool_call("story_book_close", "{}", self.deps)
            await self._push_story_log(result)
            self._story_next_page = None
            self._story_is_last_page = False
            # Only narrate the wrap-up if the close actually happened. If the activity
            # has switched away (e.g. to read-along) the gate refuses the close
            # (returns an ``error``), and we must NOT say "the story is over" in the
            # middle of the other activity.
            if "error" not in result:
                await self._story_request_narration(_STORY_CLOSE_PROMPT)
            else:
                logger.info("story: close refused (%s); skipping wrap-up", result)
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
