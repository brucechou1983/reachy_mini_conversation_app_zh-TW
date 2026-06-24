import os
import logging

from dotenv import find_dotenv, load_dotenv


logger = logging.getLogger(__name__)

# Locate .env file (search upward from current working directory)
dotenv_path = find_dotenv(usecwd=True)

if dotenv_path:
    # Load .env and override environment variables
    load_dotenv(dotenv_path=dotenv_path, override=True)
    logger.info(f"Configuration loaded from {dotenv_path}")
else:
    logger.warning("No .env file found, using environment variables")


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

    # Slow the robot's speech for young children (pitch-preserving WSOLA time-stretch
    # on output audio). 1.0 = normal; default 1.5 ≈ 1.5x slower. Clamped to [1.0, 2.5].
    # Set SPEECH_SLOWDOWN=1.0 to disable, or 1.3 for a gentler slowdown.
    SPEECH_SLOWDOWN = os.getenv("SPEECH_SLOWDOWN", "1.5")

    # Conversation backend: "openai" (default, OpenAI Realtime) or "gemini" (Gemini Live).
    HANDLER_TYPE = os.getenv("HANDLER_TYPE", "openai")
    # Gemini Live model used when HANDLER_TYPE=gemini. NOTE: Gemini 3 / 3.1 Flash Live is
    # not yet published on Vertex AI; gemini-live-2.5-flash-native-audio is the current
    # working Vertex Live model. Override via env when Flash 3 lands on Vertex.
    GEMINI_LIVE_MODEL_NAME = os.getenv("GEMINI_LIVE_MODEL_NAME", "gemini-live-2.5-flash-native-audio")

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
