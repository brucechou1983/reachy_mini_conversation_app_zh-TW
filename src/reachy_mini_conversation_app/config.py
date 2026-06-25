import os
import logging
from pathlib import Path

from dotenv import find_dotenv, load_dotenv


logger = logging.getLogger(__name__)


def reachy_mini_home() -> Path:
    """Return the durable per-user config/data dir (``~/.reachy_mini``).

    Deliberately NOT configurable via an env var: an env var could itself be wiped
    on reboot (the very failure this guards against), and other durable state
    (book library, read-along progress) already lives under ``~/.reachy_mini``.
    """
    return Path.home() / ".reachy_mini"


def _load_env_files() -> None:
    """Load configuration from ``.env`` files into the process environment.

    Precedence, highest first:

    1. **Project-local** ``.env`` searched upward from the working directory —
       a developer override (``override=True``, as this app has always done).
    2. **OS environment** (e.g. ``launchctl setenv`` / shell exports) — kept as-is.
    3. **Durable** ``~/.reachy_mini/.env`` — a per-user *fallback* (``override=False``)
       that only fills in vars not already set. It survives reboots *and* app
       reinstalls, so settings like
       ``HANDLER_TYPE`` / ``REACHY_MINI_CUSTOM_PROFILE`` / ``GEMINI_API_KEY`` don't
       vanish when a launchd/login-session env is cleared on reboot (the usual cause
       of "the robot suddenly won't talk after a reboot"). It never overrides an
       explicit env var, so it's safe to keep alongside launchctl exports.
    """
    loaded: list[str] = []

    # Durable fallback first (override=False so explicit OS env / CWD .env win).
    durable = reachy_mini_home() / ".env"
    if durable.is_file():
        load_dotenv(dotenv_path=str(durable), override=False)
        loaded.append(f"{durable} (fallback)")

    cwd_env = find_dotenv(usecwd=True)
    if cwd_env:
        load_dotenv(dotenv_path=cwd_env, override=True)
        loaded.append(cwd_env)

    if loaded:
        logger.info("Configuration loaded from: %s", ", ".join(loaded))
    else:
        logger.warning(
            "No .env file found (checked %s and the working directory); "
            "using OS environment variables only", durable,
        )


_load_env_files()


class Config:
    """Configuration class for the conversation app."""

    # Required
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # The key is downloaded in console.py if needed

    # Optional
    MODEL_NAME = os.getenv("MODEL_NAME", "gpt-realtime")
    HF_HOME = os.getenv("HF_HOME", "./cache")
    LOCAL_VISION_MODEL = os.getenv("LOCAL_VISION_MODEL", "HuggingFaceTB/SmolVLM2-2.2B-Instruct")
    HF_TOKEN = os.getenv("HF_TOKEN")  # Optional, falls back to hf auth login if not set
    TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")  # Optional, enables web_search tool
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")  # Optional, enables story_book tools (AI Studio)
    STORY_BOOKS_DIR = os.getenv("STORY_BOOKS_DIR")  # Optional, defaults to ~/.reachy_mini/books/

    # Storyteller: seconds to wait after a page's narration finishes before
    # auto-turning to the next page. Raise if pages turn before the reading is
    # done (extra audio-pipeline latency); lower for a snappier pace.
    STORY_PAGE_TURN_BUFFER_S = os.getenv("STORY_PAGE_TURN_BUFFER_S", "1.0")

    # Slow the robot's speech for young children (pitch-preserving WSOLA time-stretch
    # on output audio). 1.0 = off (default). Set e.g. 1.4 to try a 1.4x slowdown.
    # NOTE: under investigation — on some robot audio backends the player re-times
    # the buffer so this has no audible effect; kept off by default for now.
    SPEECH_SLOWDOWN = os.getenv("SPEECH_SLOWDOWN", "1.0")

    # Conversation backend: "openai" (default, OpenAI Realtime) or "gemini" (Gemini Live).
    HANDLER_TYPE = os.getenv("HANDLER_TYPE", "openai")
    # Gemini Live model used when HANDLER_TYPE=gemini. NOTE: Gemini 3 / 3.1 Flash Live is
    # not yet published on Vertex AI; gemini-live-2.5-flash-native-audio is the current
    # working Vertex Live model. Override via env when Flash 3 lands on Vertex.
    GEMINI_LIVE_MODEL_NAME = os.getenv("GEMINI_LIVE_MODEL_NAME", "gemini-live-2.5-flash-native-audio")
    # Gemini Live prebuilt voice (e.g. Leda, Puck, Kore, Aoede, Charon, Fenrir, Orus, Zephyr).
    GEMINI_VOICE = os.getenv("GEMINI_VOICE", "Leda")

    # Gemini Live end-of-turn detection. Young children speak slowly with pauses
    # between words ("等… 一下"), and the default end-of-speech timing cuts the turn
    # mid-phrase and answers the fragment. GEMINI_VAD_SILENCE_MS is how long the
    # child must stay silent before their turn is considered over (higher = more
    # patient, but slower to reply). GEMINI_VAD_PREFIX_MS keeps a little audio
    # before speech onset so the first word isn't clipped. (Start/end sensitivity
    # are left at Gemini's defaults — like OpenAI's server VAD — so the robot
    # doesn't interrupt itself on its own echo.)
    GEMINI_VAD_SILENCE_MS = os.getenv("GEMINI_VAD_SILENCE_MS", "900")
    GEMINI_VAD_PREFIX_MS = os.getenv("GEMINI_VAD_PREFIX_MS", "300")

    # Client-side barge-in: stop playback locally when the mic hears sustained speech
    # while the robot is talking — for robots whose server-side VAD won't interrupt.
    # OFF by default (can self-interrupt if the robot lacks echo cancellation).
    # BARGE_IN_LEVEL is the mic loudness threshold (0..1 mean-abs); raise if it
    # self-triggers, lower if it doesn't catch you.
    BARGE_IN_LOCAL = os.getenv("BARGE_IN_LOCAL", "").strip().lower() in ("1", "true", "yes")
    BARGE_IN_LEVEL = os.getenv("BARGE_IN_LEVEL", "0.06")

    # Route every Gemini call (Live conversation, storyteller, memory consolidation)
    # through Vertex AI instead of AI Studio. Vertex uses ADC (gcloud auth
    # application-default login) + project/location instead of an API key.
    GOOGLE_GENAI_USE_VERTEXAI = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").strip().lower() in ("1", "true", "yes")
    GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT")
    GOOGLE_CLOUD_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")  # Live API is regional, not "global"

    # Gemini features (storyteller, memory consolidation) work via an AI Studio key OR Vertex AI.
    GEMINI_AVAILABLE = bool(GEMINI_API_KEY) or GOOGLE_GENAI_USE_VERTEXAI

    logger.debug(f"Model: {MODEL_NAME}, HF_HOME: {HF_HOME}, Vision Model: {LOCAL_VISION_MODEL}")

    REACHY_MINI_CUSTOM_PROFILE = os.getenv("REACHY_MINI_CUSTOM_PROFILE")
    logger.debug(f"Custom Profile: {REACHY_MINI_CUSTOM_PROFILE}")


config = Config()


def set_custom_profile(profile: str | None) -> None:
    """Update the selected custom profile at runtime and expose it via env.

    This ensures modules that read `config` and code that inspects the
    environment see a consistent value.
    """
    try:
        config.REACHY_MINI_CUSTOM_PROFILE = profile
    except Exception:
        pass
    try:
        import os as _os

        if profile:
            _os.environ["REACHY_MINI_CUSTOM_PROFILE"] = profile
        else:
            # Remove to reflect default
            _os.environ.pop("REACHY_MINI_CUSTOM_PROFILE", None)
    except Exception:
        pass
