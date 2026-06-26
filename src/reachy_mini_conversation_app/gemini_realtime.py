"""Gemini Live conversation backend (AI Studio or Vertex AI).

Optional alternative to the OpenAI Realtime handler, selected via
``HANDLER_TYPE=gemini``. Shares the same tools, prompts and ToolDependencies
as the OpenAI handler. Adapted from the upstream pollen-robotics
``gemini_realtime`` branch, with Vertex AI support and long-term-memory
injection added.
"""

import io
import json
import base64
import asyncio
import logging
from typing import Any, Tuple, Optional
from datetime import datetime

import cv2
import numpy as np
import gradio as gr
import PIL.Image
from fastrtc import AdditionalOutputs, wait_for_item, audio_to_int16
from numpy.typing import NDArray
from scipy.signal import resample

from reachy_mini_conversation_app.config import config
from reachy_mini_conversation_app.prompts import get_session_instructions
from reachy_mini_conversation_app.genai_client import make_genai_client
from reachy_mini_conversation_app.story_autoread import StoryReaderMixin
from reachy_mini_conversation_app.tools.core_tools import (
    ToolDependencies,
    get_tool_specs,
    dispatch_tool_call,
)
from reachy_mini_conversation_app.conversation_handler import ConversationHandler


logger = logging.getLogger(__name__)


class GeminiRealtimeHandler(StoryReaderMixin, ConversationHandler):
    """A Gemini Live API handler for fastrtc Stream / LocalStream."""

    def __init__(
        self,
        deps: ToolDependencies,
        gradio_mode: bool = False,
        instance_path: Optional[str] = None,
    ):
        """Initialize the handler (gradio_mode/instance_path accepted for parity)."""
        super().__init__(
            expected_layout="mono",
            output_sample_rate=24000,
            input_sample_rate=16000,
        )
        self.deps = deps
        self.gradio_mode = gradio_mode
        self.instance_path = instance_path

        self.session: Any = None
        self.client: Any = None
        self.types: Any = None
        self.output_queue: "asyncio.Queue[Tuple[int, NDArray[np.int16]] | AdditionalOutputs]" = asyncio.Queue()

        self.last_activity_time = asyncio.get_event_loop().time()
        self.start_time = asyncio.get_event_loop().time()
        self._shutdown_requested = False

        self.input_transcription_buffer = ""
        self.output_transcription_buffer = ""
        # True while the model is producing speech, used for client-side barge-in.
        self._model_speaking = False
        self._logged_mic_while_speaking = False
        # Local (mic-energy) barge-in — independent of Gemini's own VAD.
        self._local_barge_in = config.BARGE_IN_LOCAL
        try:
            self._barge_level = float(config.BARGE_IN_LEVEL)
        except (TypeError, ValueError):
            self._barge_level = 0.06
        self._loud_frames = 0
        self._model_speech_start = 0.0
        self._init_story_state()  # page-by-page auto-read loop (StoryReaderMixin)
        # After a client-side barge-in we flush the player, but Gemini keeps
        # streaming the rest of the aborted turn until ITS own VAD sends
        # `interrupted`. Drop those in-flight chunks until this deadline so the
        # robot stays quiet instead of resuming a beat later. 0.0 = not muted.
        self._mute_until = 0.0

    def copy(self) -> "GeminiRealtimeHandler":
        """Create a fresh handler instance for a new session."""
        return GeminiRealtimeHandler(self.deps, self.gradio_mode, self.instance_path)

    def _convert_tool_specs_to_gemini_format(self) -> list[dict[str, Any]]:
        """Convert the shared OpenAI-style tool specs to Gemini function declarations."""
        function_declarations = []
        for spec in get_tool_specs():
            if spec.get("type") == "function":
                function_declarations.append(
                    {
                        "name": spec["name"],
                        "description": spec["description"],
                        "parameters": spec["parameters"],
                    }
                )
        return [{"function_declarations": function_declarations}]

    def _build_live_config(self, system_instruction: str, tools: Any) -> dict[str, Any]:
        """Build the Gemini Live connect config.

        Barge-in: ``START_OF_ACTIVITY_INTERRUPTS`` makes the server stop the model
        when it hears the user — the receive loop then flushes playback on the
        ``interrupted`` signal. This mirrors the OpenAI handler's default
        ``server_vad`` + ``interrupt_response``.

        We use Gemini's **default** start/end sensitivity (like OpenAI's default
        server VAD). An earlier version forced ``START_SENSITIVITY_HIGH`` to
        "help" barge-in fire; combined with no echo cancellation that made the
        VAD trigger on the robot's *own* voice and cut its reply off ("no
        response" / storyteller stalls). The real barge-in fix was flushing the
        player properly (``clear_player``), so the aggressive sensitivity is gone.

        The only tuning we keep is an explicit, env-configurable
        ``silence_duration_ms`` (+ ``prefix_padding_ms``): children speak slowly
        with pauses, and the default end-of-turn timing splits "等… 一下" into two
        fragments answered separately.
        """
        from google.genai import types

        try:
            silence_ms = int(config.GEMINI_VAD_SILENCE_MS)
        except (TypeError, ValueError):
            silence_ms = 900
        try:
            prefix_ms = int(config.GEMINI_VAD_PREFIX_MS)
        except (TypeError, ValueError):
            prefix_ms = 300

        return {
            "response_modalities": ["AUDIO"],
            "system_instruction": system_instruction,
            "tools": tools,
            "speech_config": {
                "voice_config": {"prebuilt_voice_config": {"voice_name": config.GEMINI_VOICE}}
            },
            "input_audio_transcription": {},
            "output_audio_transcription": {},
            "realtime_input_config": {
                "automatic_activity_detection": {
                    "disabled": False,
                    # Default sensitivity (no HIGH override — it self-interrupted on
                    # the robot's own echo). Only the silence window is tuned for kids.
                    "prefix_padding_ms": prefix_ms,
                    "silence_duration_ms": silence_ms,
                },
                "activity_handling": types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
            },
        }

    async def start_up(self) -> None:
        """Open the Gemini Live session (AI Studio or Vertex) and run the loop."""
        try:
            from google.genai import types
        except ImportError as e:
            raise RuntimeError("google-genai package required for the Gemini handler") from e

        self.client = make_genai_client()
        self.types = types

        backend = "Vertex AI" if config.GOOGLE_GENAI_USE_VERTEXAI else "AI Studio"
        logger.info("Gemini Live starting (%s, model=%s)", backend, config.GEMINI_LIVE_MODEL_NAME)

        system_instruction = get_session_instructions(
            memory_store=self.deps.memory_store,
            profile_memory_store=self.deps.profile_memory_store,
        )
        tools = self._convert_tool_specs_to_gemini_format()

        config_dict = self._build_live_config(system_instruction, tools)

        # Reconnect loop: Gemini Live sessions drop (1011 internal errors, idle
        # timeouts, network) — re-establish with backoff instead of going deaf.
        backoff = 1.0
        while not self._shutdown_requested:
            try:
                async with self.client.aio.live.connect(
                    model=config.GEMINI_LIVE_MODEL_NAME,
                    config=config_dict,
                ) as session:
                    self.session = session
                    logger.info("Gemini Live session established")
                    backoff = 1.0
                    await self._run_session_loop()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("Gemini Live session ended (%s); reconnecting in %.1fs", e, backoff)
            finally:
                self.session = None
            if self._shutdown_requested:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 10.0)

    async def _run_session_loop(self) -> None:
        """Process Gemini messages for the lifetime of the session."""
        while True:
            try:
                async for message in self.session.receive():
                    if getattr(message, "tool_call", None):
                        await self._handle_tool_call(message.tool_call)
                    if getattr(message, "server_content", None):
                        await self._handle_server_content(message.server_content)
                await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                logger.info("Gemini session loop cancelled")
                raise
            except Exception as e:
                logger.error("Gemini session loop error: %s", e)
                raise

    async def _story_request_narration(self, instruction: str) -> None:
        """Make Gemini read a page aloud: inject the page text as a user turn."""
        # We are deliberately starting narration now — don't let a lingering
        # barge-in mute window swallow this page's audio (which would leave
        # _story_audio_samples at 0 and stall the auto-advance).
        self._mute_until = 0.0
        await self.inject_user_text(instruction, respond=True)

    async def _handle_tool_call(self, tool_call: Any) -> None:
        """Dispatch Gemini function calls through the shared tool registry."""
        function_responses = []
        story_page_result: dict[str, Any] | None = None
        for fc in tool_call.function_calls:
            tool_name = fc.name
            args_json = json.dumps(fc.args)
            logger.info("Tool call: %s", tool_name)
            try:
                tool_result = await dispatch_tool_call(tool_name, args_json, self.deps)
            except Exception as e:
                logger.error("Tool '%s' failed: %s", tool_name, e)
                tool_result = {"error": str(e)}

            # Camera image is too large for a function response; send it separately.
            response_to_send = dict(tool_result)
            camera_image_b64 = None
            if tool_name == "camera" and "b64_im" in response_to_send:
                camera_image_b64 = response_to_send.pop("b64_im")
                response_to_send["image_captured"] = True

            # Story page: don't let the model narrate from the bulky function
            # response (it would compete with the narration we inject below).
            # Acknowledge minimally; the auto-read loop drives the actual reading.
            if tool_name == "story_book_go_to_page" and tool_result.get("status") == "ok":
                story_page_result = tool_result
                response_to_send = {"status": "ok", "page": tool_result.get("page")}

            function_responses.append(
                self.types.FunctionResponse(name=fc.name, id=fc.id, response=response_to_send)
            )
            await self.output_queue.put(
                AdditionalOutputs(
                    {
                        "role": "assistant",
                        "content": json.dumps(tool_result),
                        "metadata": {"title": f"🛠️ Used tool {tool_name}", "status": "done"},
                    }
                )
            )
            if camera_image_b64:
                await self._inject_camera_image(camera_image_b64)
                await self._show_camera_image_in_ui()

        if function_responses:
            # ALWAYS reply to function calls. Gemini Live keeps the model's turn
            # open until it receives the tool response, so skipping it (we used to
            # skip for idle-triggered calls) hangs the session mid-turn — and since
            # the child is idle, no further input ever arrives to unstick it, so the
            # robot freezes mid-speech. (The OpenAI handler always sends the
            # function_call_output too; it only suppresses the *follow-up verbal*
            # response for idle calls, which Gemini Live has no separate step for.)
            await self.session.send_tool_response(function_responses=function_responses)
            if self.deps.head_wobbler is not None:
                self.deps.head_wobbler.reset()

        # Model jumped to a page itself (e.g. child asked for page 5): drive the
        # auto-read loop from there instead of relying on the model to narrate.
        if story_page_result is not None:
            self.cancel_story_advance()
            await self.apply_story_page_result(story_page_result)

    async def _inject_camera_image(self, b64_image: str) -> None:
        """Send a captured camera image into the Live session as a video frame.

        ``send_realtime_input(media=...)`` maps to the deprecated
        ``realtime_input.media_chunks`` field, which the Live server now rejects
        with a 1007 error — that surfaces in the receive loop and tears down the
        whole session (so the robot goes silent). The current API takes a still
        image via ``video=``.
        """
        try:
            image = PIL.Image.open(io.BytesIO(base64.b64decode(b64_image)))
            await self.session.send_realtime_input(video=image)
        except Exception as e:
            logger.error("Failed to send camera image: %s", e)

    async def _show_camera_image_in_ui(self) -> None:
        """Push the latest camera frame to the UI transcript."""
        if self.deps.camera_worker is not None:
            np_img = self.deps.camera_worker.get_latest_frame()
            rgb_frame = cv2.cvtColor(np_img, cv2.COLOR_BGR2RGB) if np_img is not None else None
            await self.output_queue.put(
                AdditionalOutputs({"role": "assistant", "content": gr.Image(value=rgb_frame)})
            )

    async def _handle_server_content(self, server_content: Any) -> None:
        """Handle audio output, transcriptions, turn completion and barge-in."""
        transcription = getattr(server_content, "input_transcription", None)
        if transcription is not None and getattr(transcription, "text", None):
            self.deps.movement_manager.set_listening(True)
            # Client-side barge-in: as soon as the child is heard while the robot
            # is talking, stop playback ourselves — don't wait for the server's
            # 'interrupted' decision (which can be slow or never arrive).
            if self._model_speaking and not self.input_transcription_buffer:
                logger.info("Barge-in (heard child): stopping playback")
                # A real child was heard (the server is transcribing them): flush
                # and stop the story auto-read. (Don't arm the mute window here —
                # that's only for the local mic-energy path.)
                self._barge_in(cancel_story=True)
            self.input_transcription_buffer += transcription.text

        transcription = getattr(server_content, "output_transcription", None)
        if transcription is not None and getattr(transcription, "text", None):
            self.output_transcription_buffer += transcription.text

        if getattr(server_content, "model_turn", None):
            # While muted (just after a barge-in), drop the aborted turn's audio
            # so the robot doesn't resume talking until the server catches up.
            suppressed = asyncio.get_event_loop().time() < self._mute_until
            for part in server_content.model_turn.parts:
                inline_data = getattr(part, "inline_data", None)
                if inline_data is not None:
                    mime_type = getattr(inline_data, "mime_type", None)
                    if mime_type and mime_type.startswith("audio/pcm"):
                        if suppressed:
                            continue
                        audio_bytes = inline_data.data
                        audio_array = np.frombuffer(audio_bytes, dtype=np.int16).reshape(1, -1)
                        if self.deps.head_wobbler is not None:
                            self.deps.head_wobbler.feed(base64.b64encode(audio_bytes).decode())
                        now = asyncio.get_event_loop().time()
                        self.last_activity_time = now
                        if not self._model_speaking:
                            self._model_speech_start = now
                            self._loud_frames = 0
                        self._model_speaking = True
                        self.note_story_audio(audio_array.size)  # time auto-advance
                        await self.output_queue.put((self.output_sample_rate, audio_array))

        if getattr(server_content, "turn_complete", None):
            self._model_speaking = False
            self._logged_mic_while_speaking = False
            self._mute_until = 0.0  # turn done; let the next turn play
            self.story_turn_finished()  # schedule the next page if we just narrated one
            self.deps.movement_manager.set_listening(False)
            if self.input_transcription_buffer.strip():
                await self.output_queue.put(
                    AdditionalOutputs({"role": "user", "content": self.input_transcription_buffer.strip()})
                )
                self.input_transcription_buffer = ""
            if self.output_transcription_buffer.strip():
                await self.output_queue.put(
                    AdditionalOutputs({"role": "assistant", "content": self.output_transcription_buffer.strip()})
                )
                self.output_transcription_buffer = ""

        if getattr(server_content, "interrupted", None):
            # Without echo cancellation the robot self-triggers this on its own
            # narration bleeding into the mic — especially during the multi-second
            # wait between story pages. Always flush playback, but only tear down
            # the auto-read loop if a REAL child spoke this turn (transcript present);
            # a bare self-echo interrupt must NOT cancel the pending next page.
            real_user = bool(self.input_transcription_buffer.strip())
            logger.info("Barge-in (server interrupted): stopping playback (real_user=%s)", real_user)
            self._barge_in(cancel_story=real_user)
            self.input_transcription_buffer = ""
            self.output_transcription_buffer = ""

    # Local barge-in tuning.
    _BARGE_GRACE_S = 0.4   # ignore the first moments of the robot's turn
    _BARGE_SUSTAIN = 3     # consecutive loud mic frames required
    # After a client-side barge-in, mute incoming audio for this long to bridge
    # the gap until the server stops the aborted turn (sends `interrupted`).
    _BARGE_MUTE_WINDOW_S = 1.0

    @staticmethod
    def _frame_level(audio_frame: NDArray[Any]) -> float:
        """Return the mic frame's mean-abs loudness, normalized to ~0..1."""
        a = np.abs(np.asarray(audio_frame, dtype=np.float32).ravel())
        if a.size == 0:
            return 0.0
        m = float(a.mean())
        return m / 32768.0 if m > 1.5 else m  # handle int16-range input

    def _maybe_local_barge_in(self, level: float) -> None:
        """Stop playback when sustained speech (precomputed ``level``) is heard."""
        if asyncio.get_event_loop().time() - self._model_speech_start < self._BARGE_GRACE_S:
            return
        self._loud_frames = self._loud_frames + 1 if level >= self._barge_level else 0
        if self._loud_frames >= self._BARGE_SUSTAIN:
            logger.info("Local barge-in: sustained speech (level=%.3f) — stopping playback", level)
            # A real child speaking up: mute the rest of the turn AND stop auto-read.
            self._barge_in(suppress=True, cancel_story=True)

    def _barge_in(self, suppress: bool = False, cancel_story: bool = False) -> None:
        """Stop the robot talking immediately: drop queued audio + flush player.

        ``suppress=True`` (client-side barge-in: heard-child / local mic energy)
        also mutes incoming audio for ``_BARGE_MUTE_WINDOW_S`` so the rest of the
        aborted turn — which Gemini keeps streaming until its own VAD sends
        ``interrupted`` — doesn't resume playback right after the flush. For a
        server ``interrupted`` (``suppress=False``) the server has already
        stopped the turn, so we clear the mute and let the next turn play.

        ``cancel_story`` tears down the story auto-read loop. It must be True ONLY
        for a *genuine* user barge-in (a real child spoke) — NOT for a bare server
        ``interrupted``, which the robot self-triggers via mic echo of its own
        narration during the multi-second wait between pages, and which would
        otherwise cancel the pending next-page task and stall the book.
        """
        story_pending = self._story_advance_task is not None and not self._story_advance_task.done()
        logger.info(
            "barge-in: suppress=%s cancel_story=%s story_pending=%s input_buf=%r speaking=%s",
            suppress, cancel_story, story_pending,
            self.input_transcription_buffer[:20], self._model_speaking,
        )
        self._model_speaking = False
        self._logged_mic_while_speaking = False
        self._loud_frames = 0
        if cancel_story:
            self.cancel_story_advance()  # a real child interrupting stops the auto-read
        if suppress:
            self._mute_until = asyncio.get_event_loop().time() + self._BARGE_MUTE_WINDOW_S
        else:
            self._mute_until = 0.0
        # Drop audio we've already queued, then flush the player buffer so the
        # robot goes quiet at once instead of finishing its turn.
        self._drain_output_queue()
        clear = getattr(self, "_clear_queue", None)
        if callable(clear):
            clear()
        if self.deps.head_wobbler is not None:
            self.deps.head_wobbler.reset()
        self.deps.movement_manager.set_listening(True)

    def _drain_output_queue(self) -> None:
        """Drop any pending output (queued model audio/text) in place."""
        q = self.output_queue
        while not q.empty():
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                break

    def _to_gemini_pcm(self, frame: Tuple[int, NDArray[np.int16]]) -> bytes:
        """Convert a mic frame to Gemini Live's required format: 16 kHz, s16le, mono.

        The robot mic can deliver stereo and/or float at an arbitrary sample
        rate; sending it raw makes the Live server reject the session with a
        1007 "invalid audio format" error. Mirror the OpenAI handler's
        conversion (mono -> resample -> int16) before emitting raw PCM bytes.
        """
        input_sample_rate, audio_frame = frame

        # Downmix to mono (scipy channels-last convention).
        if audio_frame.ndim == 2:
            if audio_frame.shape[1] > audio_frame.shape[0]:
                audio_frame = audio_frame.T
            if audio_frame.shape[1] > 1:
                audio_frame = audio_frame[:, 0]
        audio_frame = audio_frame.squeeze()

        # Resample to the model's expected rate (16 kHz).
        if self.input_sample_rate != input_sample_rate and audio_frame.size:
            audio_frame = resample(
                audio_frame, int(len(audio_frame) * self.input_sample_rate / input_sample_rate)
            )

        # Cast to signed 16-bit little-endian PCM.
        return audio_to_int16(audio_frame).tobytes()

    async def receive(self, frame: Tuple[int, NDArray[np.int16]]) -> None:
        """Forward a microphone frame to Gemini as 16 kHz s16le mono PCM."""
        if not self.session:
            return
        if self._model_speaking:
            if not self._logged_mic_while_speaking:
                logger.info("Mic frames reaching Gemini while robot speaks (barge-in input path OK)")
                self._logged_mic_while_speaking = True
            # Local barge-in (only when BARGE_IN_LOCAL): stop playback if we hear
            # sustained speech over the robot, for robots whose server VAD won't fire.
            if self._local_barge_in:
                self._maybe_local_barge_in(self._frame_level(frame[1]))
        audio_bytes = self._to_gemini_pcm(frame)
        try:
            # ``data`` must be RAW PCM bytes — the SDK base64-encodes it for the
            # wire. Passing a pre-base64'd string double-encodes it and the Live
            # server rejects the session with a 1011 internal error.
            await self.session.send_realtime_input(
                audio={"mime_type": "audio/pcm;rate=16000", "data": audio_bytes}
            )
        except Exception as e:
            # Don't let a single bad/blocked frame tear down the whole app.
            logger.error("Failed to send audio to Gemini: %s", e)

    async def emit(self) -> Tuple[int, NDArray[np.int16]] | AdditionalOutputs | None:
        """Emit queued speaker audio / transcript updates; trigger idle behavior."""
        idle_duration = asyncio.get_event_loop().time() - self.last_activity_time
        if idle_duration > 15.0 and self.deps.movement_manager.is_idle():
            try:
                await self.send_idle_signal(idle_duration)
            except Exception as e:
                logger.warning("Idle signal skipped: %s", e)
            self.last_activity_time = asyncio.get_event_loop().time()
        return await wait_for_item(self.output_queue)  # type: ignore[no-any-return]

    async def inject_user_text(self, text: str, respond: bool = True) -> None:
        """Inject a user text turn into the live session (e.g. a reader tap)."""
        if not self.session:
            logger.debug("No session, cannot inject user text")
            return
        await self.session.send(input=text, end_of_turn=respond)

    async def send_idle_signal(self, idle_duration: float) -> None:
        """Nudge Gemini to do something autonomous after a period of silence."""
        if not self.session:
            return
        msg = (
            f"[Idle time update: {self.format_timestamp()} - "
            f"No activity for {idle_duration:.1f}s] "
            "You've been idle for a while. Feel free to get creative - "
            "dance, show an emotion, look around, do nothing, or just be yourself!"
        )
        await self.session.send(input=msg, end_of_turn=True)

    def format_timestamp(self) -> str:
        """Format the current wall-clock time and elapsed session seconds."""
        elapsed = asyncio.get_event_loop().time() - self.start_time
        return f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | +{elapsed:.1f}s]"

    async def shutdown(self) -> None:
        """Stop the reconnect loop, drop the session and flush buffers."""
        self._shutdown_requested = True
        self.session = None
        self.input_transcription_buffer = ""
        self.output_transcription_buffer = ""
        while not self.output_queue.empty():
            try:
                self.output_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
