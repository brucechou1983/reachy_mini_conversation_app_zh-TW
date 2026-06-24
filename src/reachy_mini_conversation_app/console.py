"""Bidirectional local audio stream with optional settings UI.

In headless mode, there is no Gradio UI. If the OpenAI API key is not
available via environment/.env, we expose a minimal settings page via the
Reachy Mini Apps settings server to let non-technical users enter it.

The settings UI is served from this package's ``static/`` folder and offers a
single password field to set ``OPENAI_API_KEY``. Once set, we persist it to the
app instance's ``.env`` file (if available) and proceed to start streaming.
"""

import os
import sys
import time
import asyncio
import logging
from typing import Any, List, Optional
from pathlib import Path

import numpy as np
from fastrtc import AdditionalOutputs, audio_to_float32
from numpy.typing import NDArray
from scipy.signal import resample

from reachy_mini import ReachyMini
from reachy_mini_conversation_app.config import config
from reachy_mini_conversation_app.audio_pace import TimeStretcher, get_speech_slowdown
from reachy_mini_conversation_app.story_routes import mount_story_routes
from reachy_mini_conversation_app.conversation_handler import ConversationHandler
from reachy_mini_conversation_app.headless_personality_ui import mount_personality_routes


try:
    # FastAPI is provided by the Reachy Mini Apps runtime
    from fastapi import FastAPI, Response
    from pydantic import BaseModel
    from fastapi.responses import FileResponse, JSONResponse
    from starlette.staticfiles import StaticFiles
except Exception:  # pragma: no cover - only loaded when settings_app is used
    FastAPI = object  # type: ignore
    FileResponse = object  # type: ignore
    JSONResponse = object  # type: ignore
    StaticFiles = object  # type: ignore
    BaseModel = object  # type: ignore


logger = logging.getLogger(__name__)


def _prepare_output_audio(
    audio_data: "NDArray[Any]",
    input_sample_rate: int,
    output_sample_rate: int,
) -> "NDArray[np.float32] | None":
    """Downmix to mono, cast to float32, and resample to the speaker rate.

    Returns ``None`` for empty / sub-sample frames. The Gemini Live backend can
    emit a 0- or 1-sample audio chunk, which makes the resample target length 0
    and ``scipy.signal.resample`` raise ``ZeroDivisionError`` — guard against it.
    """
    # Reshape if needed (scipy channels-last convention) -> mono
    if audio_data.ndim == 2:
        if audio_data.shape[1] > audio_data.shape[0]:
            audio_data = audio_data.T
        if audio_data.shape[1] > 1:
            audio_data = audio_data[:, 0]

    audio_frame = audio_to_float32(audio_data)
    if audio_frame.size == 0:
        return None

    if input_sample_rate != output_sample_rate:
        num = int(len(audio_frame) * output_sample_rate / input_sample_rate)
        if num <= 0:
            return None
        audio_frame = resample(audio_frame, num)

    return audio_frame


class LocalStream:
    """LocalStream using Reachy Mini's recorder/player."""

    def __init__(
        self,
        handler: ConversationHandler,
        robot: ReachyMini,
        *,
        settings_app: Optional[FastAPI] = None,
        instance_path: Optional[str] = None,
    ):
        """Initialize the stream with an OpenAI realtime handler and pipelines.

        - ``settings_app``: the Reachy Mini Apps FastAPI to attach settings endpoints.
        - ``instance_path``: directory where per-instance ``.env`` should be stored.
        """
        self.handler = handler
        self._robot = robot
        self._stop_event = asyncio.Event()
        self._tasks: List[asyncio.Task[None]] = []
        # Optional pitch-preserving speech slowdown for young children.
        self._speech_factor = get_speech_slowdown()
        self._stretcher: Optional[TimeStretcher] = (
            TimeStretcher(self._speech_factor) if self._speech_factor > 1.0 else None
        )
        if self._stretcher is not None:
            logger.info("Speech slowdown enabled: %.2gx (SPEECH_SLOWDOWN)", self._speech_factor)
        # Allow the handler to flush the player queue when appropriate.
        self.handler._clear_queue = self.clear_audio_queue
        self._settings_app: Optional[FastAPI] = settings_app
        self._instance_path: Optional[str] = instance_path
        self._settings_initialized = False
        self._asyncio_loop = None

    # ---- Settings UI (only when API key is missing) ----
    def _read_env_lines(self, env_path: Path) -> list[str]:
        """Load env file contents or a template as a list of lines."""
        inst = env_path.parent
        try:
            if env_path.exists():
                try:
                    return env_path.read_text(encoding="utf-8").splitlines()
                except Exception:
                    return []
            template_text = None
            ex = inst / ".env.example"
            if ex.exists():
                try:
                    template_text = ex.read_text(encoding="utf-8")
                except Exception:
                    template_text = None
            if template_text is None:
                try:
                    cwd_example = Path.cwd() / ".env.example"
                    if cwd_example.exists():
                        template_text = cwd_example.read_text(encoding="utf-8")
                except Exception:
                    template_text = None
            if template_text is None:
                packaged = Path(__file__).parent / ".env.example"
                if packaged.exists():
                    try:
                        template_text = packaged.read_text(encoding="utf-8")
                    except Exception:
                        template_text = None
            return template_text.splitlines() if template_text else []
        except Exception:
            return []

    def _persist_api_key(self, key: str) -> None:
        """Persist API key to environment and instance ``.env`` if possible.

        Behavior:
        - Always sets ``OPENAI_API_KEY`` in process env and in-memory config.
        - Writes/updates ``<instance_path>/.env``:
          * If ``.env`` exists, replaces/append OPENAI_API_KEY line.
          * Else, copies template from ``<instance_path>/.env.example`` when present,
            otherwise falls back to the packaged template
            ``reachy_mini_conversation_app/.env.example``.
          * Ensures the resulting file contains the full template plus the key.
        - Loads the written ``.env`` into the current process environment.
        """
        k = (key or "").strip()
        if not k:
            return
        # Update live process env and config so consumers see it immediately
        try:
            os.environ["OPENAI_API_KEY"] = k
        except Exception:  # best-effort
            pass
        try:
            config.OPENAI_API_KEY = k
        except Exception:
            pass

        if not self._instance_path:
            return
        try:
            inst = Path(self._instance_path)
            env_path = inst / ".env"
            lines = self._read_env_lines(env_path)
            replaced = False
            for i, ln in enumerate(lines):
                if ln.strip().startswith("OPENAI_API_KEY="):
                    lines[i] = f"OPENAI_API_KEY={k}"
                    replaced = True
                    break
            if not replaced:
                lines.append(f"OPENAI_API_KEY={k}")
            final_text = "\n".join(lines) + "\n"
            env_path.write_text(final_text, encoding="utf-8")
            logger.info("Persisted OPENAI_API_KEY to %s", env_path)

            # Load the newly written .env into this process to ensure downstream imports see it
            try:
                from dotenv import load_dotenv

                load_dotenv(dotenv_path=str(env_path), override=True)
            except Exception:
                pass
        except Exception as e:
            logger.warning("Failed to persist OPENAI_API_KEY: %s", e)

    def _persist_tavily_key(self, key: str) -> None:
        """Persist Tavily API key to environment and instance ``.env`` if possible."""
        k = (key or "").strip()
        if not k:
            return
        try:
            os.environ["TAVILY_API_KEY"] = k
        except Exception:
            pass
        try:
            config.TAVILY_API_KEY = k
        except Exception:
            pass

        if not self._instance_path:
            return
        try:
            inst = Path(self._instance_path)
            env_path = inst / ".env"
            lines = self._read_env_lines(env_path)
            replaced = False
            for i, ln in enumerate(lines):
                if ln.strip().startswith("TAVILY_API_KEY="):
                    lines[i] = f"TAVILY_API_KEY={k}"
                    replaced = True
                    break
            if not replaced:
                lines.append(f"TAVILY_API_KEY={k}")
            final_text = "\n".join(lines) + "\n"
            env_path.write_text(final_text, encoding="utf-8")
            logger.info("Persisted TAVILY_API_KEY to %s", env_path)

            try:
                from dotenv import load_dotenv

                load_dotenv(dotenv_path=str(env_path), override=True)
            except Exception:
                pass
        except Exception as e:
            logger.warning("Failed to persist TAVILY_API_KEY: %s", e)

    def _persist_gemini_key(self, key: str) -> None:
        """Persist Gemini API key to environment and instance ``.env`` if possible."""
        k = (key or "").strip()
        if not k:
            return
        try:
            os.environ["GEMINI_API_KEY"] = k
        except Exception:
            pass
        try:
            config.GEMINI_API_KEY = k
        except Exception:
            pass

        if not self._instance_path:
            return
        try:
            inst = Path(self._instance_path)
            env_path = inst / ".env"
            lines = self._read_env_lines(env_path)
            replaced = False
            for i, ln in enumerate(lines):
                if ln.strip().startswith("GEMINI_API_KEY="):
                    lines[i] = f"GEMINI_API_KEY={k}"
                    replaced = True
                    break
            if not replaced:
                lines.append(f"GEMINI_API_KEY={k}")
            final_text = "\n".join(lines) + "\n"
            env_path.write_text(final_text, encoding="utf-8")
            logger.info("Persisted GEMINI_API_KEY to %s", env_path)

            try:
                from dotenv import load_dotenv

                load_dotenv(dotenv_path=str(env_path), override=True)
            except Exception:
                pass
        except Exception as e:
            logger.warning("Failed to persist GEMINI_API_KEY: %s", e)

    def _persist_personality(self, profile: Optional[str]) -> None:
        """Persist the startup personality to the instance .env and config."""
        selection = (profile or "").strip() or None
        try:
            from reachy_mini_conversation_app.config import set_custom_profile

            set_custom_profile(selection)
        except Exception:
            pass

        if not self._instance_path:
            return
        try:
            env_path = Path(self._instance_path) / ".env"
            lines = self._read_env_lines(env_path)
            replaced = False
            for i, ln in enumerate(list(lines)):
                if ln.strip().startswith("REACHY_MINI_CUSTOM_PROFILE="):
                    if selection:
                        lines[i] = f"REACHY_MINI_CUSTOM_PROFILE={selection}"
                    else:
                        lines.pop(i)
                    replaced = True
                    break
            if selection and not replaced:
                lines.append(f"REACHY_MINI_CUSTOM_PROFILE={selection}")
            if selection is None and not env_path.exists():
                return
            final_text = "\n".join(lines) + "\n"
            env_path.write_text(final_text, encoding="utf-8")
            logger.info("Persisted startup personality to %s", env_path)
            try:
                from dotenv import load_dotenv

                load_dotenv(dotenv_path=str(env_path), override=True)
            except Exception:
                pass
        except Exception as e:
            logger.warning("Failed to persist REACHY_MINI_CUSTOM_PROFILE: %s", e)

    def _read_persisted_personality(self) -> Optional[str]:
        """Read persisted startup personality from instance .env (if any)."""
        if not self._instance_path:
            return None
        env_path = Path(self._instance_path) / ".env"
        try:
            if env_path.exists():
                for ln in env_path.read_text(encoding="utf-8").splitlines():
                    if ln.strip().startswith("REACHY_MINI_CUSTOM_PROFILE="):
                        _, _, val = ln.partition("=")
                        v = val.strip()
                        return v or None
        except Exception:
            pass
        return None

    def _init_settings_ui_if_needed(self) -> None:
        """Attach minimal settings UI to the settings app.

        Always mounts the UI when a settings_app is provided so that users
        see a confirmation message even if the API key is already configured.
        """
        if self._settings_initialized:
            return
        if self._settings_app is None:
            return

        static_dir = Path(__file__).parent / "static"
        index_file = static_dir / "index.html"

        if hasattr(self._settings_app, "mount"):
            try:
                # Serve /static/* assets
                self._settings_app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
            except Exception:
                pass

        class ApiKeyPayload(BaseModel):
            openai_api_key: str

        # GET / -> index.html
        @self._settings_app.get("/")
        def _root() -> FileResponse:
            return FileResponse(str(index_file))

        # GET /favicon.ico -> optional, avoid noisy 404s on some browsers
        @self._settings_app.get("/favicon.ico")
        def _favicon() -> Response:
            return Response(status_code=204)

        # GET /status -> whether key is set
        @self._settings_app.get("/status")
        def _status() -> JSONResponse:
            has_key = bool(config.OPENAI_API_KEY and str(config.OPENAI_API_KEY).strip())
            return JSONResponse({"has_key": has_key})

        # GET /ready -> whether backend finished loading tools
        @self._settings_app.get("/ready")
        def _ready() -> JSONResponse:
            try:
                mod = sys.modules.get("reachy_mini_conversation_app.tools.core_tools")
                ready = bool(getattr(mod, "_TOOLS_INITIALIZED", False)) if mod else False
            except Exception:
                ready = False
            return JSONResponse({"ready": ready})

        # POST /openai_api_key -> set/persist key
        @self._settings_app.post("/openai_api_key")
        def _set_key(payload: ApiKeyPayload) -> JSONResponse:
            key = (payload.openai_api_key or "").strip()
            if not key:
                return JSONResponse({"ok": False, "error": "empty_key"}, status_code=400)
            self._persist_api_key(key)
            return JSONResponse({"ok": True})

        # POST /validate_api_key -> validate key without persisting it
        @self._settings_app.post("/validate_api_key")
        async def _validate_key(payload: ApiKeyPayload) -> JSONResponse:
            key = (payload.openai_api_key or "").strip()
            if not key:
                return JSONResponse({"valid": False, "error": "empty_key"}, status_code=400)

            # Try to validate by checking if we can fetch the models
            try:
                import httpx

                headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get("https://api.openai.com/v1/models", headers=headers)
                    if response.status_code == 200:
                        return JSONResponse({"valid": True})
                    elif response.status_code == 401:
                        return JSONResponse({"valid": False, "error": "invalid_api_key"}, status_code=401)
                    else:
                        return JSONResponse(
                            {"valid": False, "error": "validation_failed"}, status_code=response.status_code
                        )
            except Exception as e:
                logger.warning(f"API key validation failed: {e}")
                return JSONResponse({"valid": False, "error": "validation_error"}, status_code=500)

        # GET /tavily_status -> whether Tavily key is set
        @self._settings_app.get("/tavily_status")
        def _tavily_status() -> JSONResponse:
            has_key = bool(config.TAVILY_API_KEY and str(config.TAVILY_API_KEY).strip())
            return JSONResponse({"has_key": has_key})

        # POST /tavily_api_key -> set/persist Tavily key
        class TavilyKeyPayload(BaseModel):
            key: str

        @self._settings_app.post("/tavily_api_key")
        def _set_tavily_key(payload: TavilyKeyPayload) -> JSONResponse:
            key = (payload.key or "").strip()
            if not key:
                return JSONResponse({"ok": False, "error": "empty_key"}, status_code=400)
            self._persist_tavily_key(key)
            return JSONResponse({"ok": True})

        # GET /gemini_status -> whether Gemini key is set
        @self._settings_app.get("/gemini_status")
        def _gemini_status() -> JSONResponse:
            has_key = bool(config.GEMINI_API_KEY and str(config.GEMINI_API_KEY).strip())
            return JSONResponse({"has_key": has_key})

        # POST /gemini_api_key -> set/persist Gemini key
        class GeminiKeyPayload(BaseModel):
            key: str

        @self._settings_app.post("/gemini_api_key")
        def _set_gemini_key(payload: GeminiKeyPayload) -> JSONResponse:
            key = (payload.key or "").strip()
            if not key:
                return JSONResponse({"ok": False, "error": "empty_key"}, status_code=400)
            self._persist_gemini_key(key)
            return JSONResponse({"ok": True})

        # Mount story reader routes
        mount_story_routes(self._settings_app)

        # ---- Photo Gallery Routes ----

        _PHOTOS_DIR = Path.home() / "Pictures" / "reachy"

        def _safe_photo_path(filename: str) -> Path | None:
            """Validate filename and return resolved path inside PHOTOS_DIR, or None."""
            if "/" in filename or "\\" in filename or ".." in filename:
                return None
            candidate = (_PHOTOS_DIR / filename).resolve()
            try:
                if not candidate.is_relative_to(_PHOTOS_DIR.resolve()):
                    return None
            except (ValueError, RuntimeError):
                return None
            return candidate

        @self._settings_app.get("/photos")
        def _list_photos() -> JSONResponse:
            if not _PHOTOS_DIR.exists():
                return JSONResponse([])
            photos = []
            for p in _PHOTOS_DIR.glob("*.png"):
                if not p.is_file() or p.is_symlink():
                    continue
                stat = p.stat()
                photos.append({
                    "filename": p.name,
                    "timestamp": int(stat.st_mtime),
                    "size": stat.st_size,
                })
            photos.sort(key=lambda x: str(x["filename"]), reverse=True)
            return JSONResponse(photos)

        @self._settings_app.get("/photos/{filename}")
        def _serve_photo(filename: str) -> Response:
            photo_path = _safe_photo_path(filename)
            if photo_path is None:
                return JSONResponse({"error": "invalid_filename"}, status_code=400)
            if not photo_path.exists() or not photo_path.is_file():
                return JSONResponse({"error": "not_found"}, status_code=404)
            return FileResponse(str(photo_path), media_type="image/png")

        @self._settings_app.get("/photos/{filename}/download")
        def _download_photo(filename: str) -> Response:
            photo_path = _safe_photo_path(filename)
            if photo_path is None:
                return JSONResponse({"error": "invalid_filename"}, status_code=400)
            if not photo_path.exists() or not photo_path.is_file():
                return JSONResponse({"error": "not_found"}, status_code=404)
            return FileResponse(
                str(photo_path),
                media_type="image/png",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )

        @self._settings_app.delete("/photos/{filename}")
        def _delete_photo(filename: str) -> JSONResponse:
            photo_path = _safe_photo_path(filename)
            if photo_path is None:
                return JSONResponse({"ok": False, "error": "invalid_filename"}, status_code=400)
            if not photo_path.exists() or not photo_path.is_file():
                return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
            try:
                photo_path.unlink()
                logger.info("Photo deleted: %s", photo_path)
                return JSONResponse({"ok": True})
            except Exception as e:
                logger.error("Failed to delete photo: %s", e)
                return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

        self._settings_initialized = True

    def launch(self) -> None:
        """Start the recorder/player and run the async processing loops.

        If the OpenAI key is missing, expose a tiny settings UI via the
        Reachy Mini settings server to collect it before starting streams.
        """
        self._stop_event.clear()

        # Try to load an existing instance .env first (covers subsequent runs)
        if self._instance_path:
            try:
                from dotenv import load_dotenv

                from reachy_mini_conversation_app.config import set_custom_profile

                env_path = Path(self._instance_path) / ".env"
                if env_path.exists():
                    load_dotenv(dotenv_path=str(env_path), override=True)
                    # Update config with newly loaded values
                    new_key = os.getenv("OPENAI_API_KEY", "").strip()
                    if new_key:
                        try:
                            config.OPENAI_API_KEY = new_key
                        except Exception:
                            pass
                    new_tavily_key = os.getenv("TAVILY_API_KEY", "").strip()
                    if new_tavily_key:
                        try:
                            config.TAVILY_API_KEY = new_tavily_key
                        except Exception:
                            pass
                    new_gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
                    if new_gemini_key:
                        try:
                            config.GEMINI_API_KEY = new_gemini_key
                        except Exception:
                            pass
                    new_profile = os.getenv("REACHY_MINI_CUSTOM_PROFILE")
                    if new_profile is not None:
                        try:
                            set_custom_profile(new_profile.strip() or None)
                        except Exception:
                            pass
            except Exception:
                pass

        # If key is still missing, try to download one from HuggingFace
        if not (config.OPENAI_API_KEY and str(config.OPENAI_API_KEY).strip()):
            logger.info("OPENAI_API_KEY not set, attempting to download from HuggingFace...")
            try:
                from gradio_client import Client
                client = Client("HuggingFaceM4/gradium_setup", verbose=False)
                key, status = client.predict(api_name="/claim_b_key")
                if key and key.strip():
                    logger.info("Successfully downloaded API key from HuggingFace")
                    # Persist it immediately
                    self._persist_api_key(key)
            except Exception as e:
                logger.warning(f"Failed to download API key from HuggingFace: {e}")

        # Always expose settings UI if a settings app is available
        # (do this AFTER loading/downloading the key so status endpoint sees the right value)
        self._init_settings_ui_if_needed()
        if self._settings_app is not None:
            logger.info("Settings page available at http://localhost:7860/")

        # If key is still missing -> open settings page and wait
        if not (config.OPENAI_API_KEY and str(config.OPENAI_API_KEY).strip()):
            logger.warning("OPENAI_API_KEY not found. Open http://localhost:7860/ to enter it.")
            try:
                import webbrowser
                webbrowser.open("http://localhost:7860/")
            except Exception:
                pass
            # Poll until the key becomes available (set via the settings UI)
            try:
                while not (config.OPENAI_API_KEY and str(config.OPENAI_API_KEY).strip()):
                    time.sleep(0.2)
            except KeyboardInterrupt:
                logger.info("Interrupted while waiting for API key.")
                return

        # Start media after key is set/available
        self._robot.media.start_recording()
        self._robot.media.start_playing()
        time.sleep(1)  # give some time to the pipelines to start

        async def runner() -> None:
            # Capture loop for cross-thread personality actions
            loop = asyncio.get_running_loop()
            self._asyncio_loop = loop  # type: ignore[assignment]
            # Mount personality routes now that loop and handler are available
            try:
                if self._settings_app is not None:
                    mount_personality_routes(
                        self._settings_app,
                        self.handler,
                        lambda: self._asyncio_loop,
                        persist_personality=self._persist_personality,
                        get_persisted_personality=self._read_persisted_personality,
                        persist_tavily_key=self._persist_tavily_key,
                        persist_gemini_key=self._persist_gemini_key,
                    )
            except Exception:
                pass
            self._tasks = [
                asyncio.create_task(self.handler.start_up(), name="openai-handler"),
                asyncio.create_task(self.record_loop(), name="stream-record-loop"),
                asyncio.create_task(self.play_loop(), name="stream-play-loop"),
            ]
            try:
                await asyncio.gather(*self._tasks)
            except asyncio.CancelledError:
                logger.info("Tasks cancelled during shutdown")
            finally:
                # Ensure handler connection is closed
                await self.handler.shutdown()

        asyncio.run(runner())

    def close(self) -> None:
        """Stop the stream and underlying media pipelines.

        This method:
        - Stops audio recording and playback first
        - Sets the stop event to signal async loops to terminate
        - Cancels all pending async tasks (openai-handler, record-loop, play-loop)
        """
        logger.info("Stopping LocalStream...")

        # Stop media pipelines FIRST before cancelling async tasks
        # This ensures clean shutdown before PortAudio cleanup
        try:
            self._robot.media.stop_recording()
        except Exception as e:
            logger.debug(f"Error stopping recording (may already be stopped): {e}")

        try:
            self._robot.media.stop_playing()
        except Exception as e:
            logger.debug(f"Error stopping playback (may already be stopped): {e}")

        # Now signal async loops to stop
        self._stop_event.set()

        # Cancel all running tasks
        for task in self._tasks:
            if not task.done():
                task.cancel()

    def clear_audio_queue(self) -> None:
        """Flush the player's appsrc to drop any queued audio immediately."""
        logger.info("User intervention: flushing player queue")
        # Drop any half-stretched audio so the next response starts clean.
        if self._stretcher is not None:
            self._stretcher.reset()
        # Actually flush the backend's playback buffer. On every current SDK
        # backend (LOCAL GStreamer *and* WEBRTC) ``clear_player()`` is the ONLY
        # method that drops queued/in-flight audio — and on WEBRTC it also tells
        # the daemon to flush the robot's speaker queue, where the bulk of the
        # buffered audio actually sits. ``clear_output_buffer()`` is deprecated
        # and a *no-op* on both backends.
        #
        # Do NOT gate on ``media.backend``: the SDK resolves the legacy
        # GSTREAMER / GSTREAMER_NO_VIDEO enums to LOCAL, so the old
        # ``backend in (GSTREAMER, …)`` check was always False and we silently
        # called the no-op — leaving the robot talking straight through barge-in.
        audio = self._robot.media.audio
        if audio is not None:
            flush = getattr(audio, "clear_player", None)
            if callable(flush):
                flush()
            else:
                # Pre-1.8 SDK had no clear_player(); there clear_output_buffer()
                # was the real flush, so fall back to it.
                legacy = getattr(audio, "clear_output_buffer", None)
                if callable(legacy):
                    legacy()
        self.handler.output_queue = asyncio.Queue()

    async def record_loop(self) -> None:
        """Read mic frames from the recorder and forward them to the handler."""
        input_sample_rate = self._robot.media.get_input_audio_samplerate()
        logger.debug(f"Audio recording started at {input_sample_rate} Hz")

        while not self._stop_event.is_set():
            # Read the mic OFF the event loop: get_audio_sample() can block, and
            # if it (or playback) blocks the loop, the recorder stalls while the
            # robot is speaking — so Gemini never hears a barge-in and can't be
            # interrupted. Threading keeps record + play genuinely concurrent.
            audio_frame = await asyncio.to_thread(self._robot.media.get_audio_sample)
            if audio_frame is not None:
                await self.handler.receive((input_sample_rate, audio_frame))
            await asyncio.sleep(0)  # avoid busy loop

    async def play_loop(self) -> None:
        """Fetch outputs from the handler: log text and play audio frames."""
        while not self._stop_event.is_set():
            handler_output = await self.handler.emit()

            if isinstance(handler_output, AdditionalOutputs):
                for msg in handler_output.args:
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        logger.info(
                            "role=%s content=%s",
                            msg.get("role"),
                            content if len(content) < 500 else content[:500] + "…",
                        )

            elif isinstance(handler_output, tuple):
                input_sample_rate, audio_data = handler_output
                output_sample_rate = self._robot.media.get_output_audio_samplerate()

                audio_frame = _prepare_output_audio(
                    audio_data, input_sample_rate, output_sample_rate
                )
                if audio_frame is not None and self._stretcher is not None:
                    try:
                        audio_frame = self._stretcher.process(audio_frame)
                    except Exception as e:  # never let slowdown break playback
                        logger.warning("speech slowdown failed; playing normally: %s", e)
                if audio_frame is not None and audio_frame.size > 0:
                    # Push playback OFF the event loop so it can't block the
                    # recorder (see record_loop) — keeps barge-in responsive.
                    await asyncio.to_thread(self._robot.media.push_audio_sample, audio_frame)

            else:
                logger.debug("Ignoring output type=%s", type(handler_output).__name__)

            await asyncio.sleep(0)  # yield to event loop
