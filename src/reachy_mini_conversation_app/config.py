import os
import sys
import logging
from pathlib import Path

from dotenv import find_dotenv, load_dotenv


# Locked profile: set to a profile name (e.g., "astronomer") to lock the app
# to that profile and disable all profile switching. Leave as None for normal behavior.
LOCKED_PROFILE: str | None = None
DEFAULT_PROFILES_DIRECTORY = Path(__file__).parent / "profiles"

logger = logging.getLogger(__name__)

# Validate LOCKED_PROFILE at startup
if LOCKED_PROFILE is not None:
    _profiles_dir = DEFAULT_PROFILES_DIRECTORY
    _profile_path = _profiles_dir / LOCKED_PROFILE
    _instructions_file = _profile_path / "instructions.txt"
    if not _profile_path.is_dir():
        print(f"Error: LOCKED_PROFILE '{LOCKED_PROFILE}' does not exist in {_profiles_dir}", file=sys.stderr)
        sys.exit(1)
    if not _instructions_file.is_file():
        print(f"Error: LOCKED_PROFILE '{LOCKED_PROFILE}' has no instructions.txt", file=sys.stderr)
        sys.exit(1)

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

    logger.debug(f"Model: {MODEL_NAME}, HF_HOME: {HF_HOME}, Vision Model: {LOCAL_VISION_MODEL}")

    PROFILES_DIRECTORY = Path(os.getenv("PROFILES_DIRECTORY", "") or Path(__file__).parent / "profiles")
    TOOLS_DIRECTORY = Path(os.getenv("TOOLS_DIRECTORY", ""))
    REACHY_MINI_CUSTOM_PROFILE = LOCKED_PROFILE or os.getenv("REACHY_MINI_CUSTOM_PROFILE")

    logger.debug(f"Custom Profile: {REACHY_MINI_CUSTOM_PROFILE}")


    def __init__(self) -> None:
        """Initialize the configuration."""
        profile = self.REACHY_MINI_CUSTOM_PROFILE
        if profile:
            # check if the custom profile doesn't shadow a default library profile
            profile_dir = self.PROFILES_DIRECTORY / profile
            shadowed_profile = DEFAULT_PROFILES_DIRECTORY / profile
            if profile_dir is not shadowed_profile and shadowed_profile.exists():
                raise RuntimeError(f"Config.__init__(): Ambiguous profile '{profile}': found in both {self.PROFILES_DIRECTORY} and reachy_mini_conversation_app default profiles library. "
                f"Please rename the profile '{profile}' in {self.PROFILES_DIRECTORY} to avoid confusion "
                "or unset 'PROFILES_DIRECTORY' env variable to use the default library profile.")

        if self.PROFILES_DIRECTORY is not DEFAULT_PROFILES_DIRECTORY:
            logger.warning(f"Environment variable 'PROFILES_DIRECTORY' is set. Profiles (instructions.txt, ...) will be loaded from {self.PROFILES_DIRECTORY}.")


config = Config()


def set_custom_profile(profile: str | None) -> None:
    """Update the selected custom profile at runtime and expose it via env.

    This ensures modules that read `config` and code that inspects the
    environment see a consistent value.
    """
    if LOCKED_PROFILE is not None:
        return
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
