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
from reachy_mini_conversation_app.tools.core_tools import (
    ToolDependencies,
    get_tool_specs,
    dispatch_tool_call,
)
from reachy_mini_conversation_app.conversation_handler import ConversationHandler


logger = logging.getLogger(__name__)


class GeminiRealtimeHandler(ConversationHandler):
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
        self.is_idle_tool_call = False
        self._shutdown_requested = False

        self.input_transcription_buffer = ""
        self.output_transcription_buffer = ""

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

        config_dict = {
            "response_modalities": ["AUDIO"],
            "system_instruction": system_instruction,
            "tools": tools,
            "speech_config": {
                "voice_config": {"prebuilt_voice_config": {"voice_name": "Puck"}}
            },
            "input_audio_transcription": {},
            "output_audio_transcription": {},
        }

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

    async def _handle_tool_call(self, tool_call: Any) -> None:
        """Dispatch Gemini function calls through the shared tool registry."""
        function_responses = []
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
            if not self.is_idle_tool_call:
                await self.session.send_tool_response(function_responses=function_responses)
            else:
                self.is_idle_tool_call = False
            if self.deps.head_wobbler is not None:
                self.deps.head_wobbler.reset()

    async def _inject_camera_image(self, b64_image: str) -> None:
        """Send a captured camera image into the Live session as media input."""
        try:
            image = PIL.Image.open(io.BytesIO(base64.b64decode(b64_image)))
            await self.session.send_realtime_input(media=image)
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
            self.input_transcription_buffer += transcription.text

        transcription = getattr(server_content, "output_transcription", None)
        if transcription is not None and getattr(transcription, "text", None):
            self.output_transcription_buffer += transcription.text

        if getattr(server_content, "model_turn", None):
            for part in server_content.model_turn.parts:
                inline_data = getattr(part, "inline_data", None)
                if inline_data is not None:
                    mime_type = getattr(inline_data, "mime_type", None)
                    if mime_type and mime_type.startswith("audio/pcm"):
                        audio_bytes = inline_data.data
                        audio_array = np.frombuffer(audio_bytes, dtype=np.int16).reshape(1, -1)
                        if self.deps.head_wobbler is not None:
                            self.deps.head_wobbler.feed(base64.b64encode(audio_bytes).decode())
                        self.last_activity_time = asyncio.get_event_loop().time()
                        await self.output_queue.put((self.output_sample_rate, audio_array))

        if getattr(server_content, "turn_complete", None):
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
            clear = getattr(self, "_clear_queue", None)
            if callable(clear):
                clear()
            if self.deps.head_wobbler is not None:
                self.deps.head_wobbler.reset()
            self.input_transcription_buffer = ""
            self.output_transcription_buffer = ""

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
        self.is_idle_tool_call = True
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
