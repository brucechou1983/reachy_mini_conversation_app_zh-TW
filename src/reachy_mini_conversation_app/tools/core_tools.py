from __future__ import annotations
import abc
import sys
import json
import inspect
import logging
import importlib
from typing import Any, Dict, List
from pathlib import Path
from dataclasses import dataclass

from reachy_mini import ReachyMini
# Import config to ensure .env is loaded before reading REACHY_MINI_CUSTOM_PROFILE
from reachy_mini_conversation_app.config import config  # noqa: F401


logger = logging.getLogger(__name__)


PROFILES_DIRECTORY = "reachy_mini_conversation_app.profiles"

if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s:%(lineno)d | %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


ALL_TOOLS: Dict[str, "Tool"] = {}
ALL_TOOL_SPECS: List[Dict[str, Any]] = []
_ALL_TOOL_INSTANCES: Dict[str, "Tool"] = {}  # includes unavailable tools
_TOOLS_INITIALIZED = False



def get_concrete_subclasses(base: type[Tool]) -> List[type[Tool]]:
    """Recursively find all concrete (non-abstract) subclasses of a base class."""
    result: List[type[Tool]] = []
    for cls in base.__subclasses__():
        if not inspect.isabstract(cls):
            result.append(cls)
        # recurse into subclasses
        result.extend(get_concrete_subclasses(cls))
    return result


@dataclass
class ToolDependencies:
    """External dependencies injected into tools."""

    reachy_mini: ReachyMini
    movement_manager: Any  # MovementManager from moves.py
    # Optional deps
    camera_worker: Any | None = None  # CameraWorker for frame buffering
    vision_manager: Any | None = None
    head_wobbler: Any | None = None  # HeadWobbler for audio-reactive motion
    memory_store: Any | None = None  # MemoryStore for long-term memory
    profile_memory_store: Any | None = None  # MemoryStore for per-profile memory
    realtime_handler: Any | None = None  # OpenaiRealtimeHandler for message injection
    motion_duration_s: float = 1.0


# Tool base class
class Tool(abc.ABC):
    """Base abstraction for tools used in function-calling.

    Each tool must define:
      - name: str
      - description: str
      - parameters_schema: Dict[str, Any]  # JSON Schema
    """

    name: str
    description: str
    parameters_schema: Dict[str, Any]
    # Tools whose UX needs the on-screen reader (story bookshelf / read-along) set
    # this True; they are hidden when no display is detected (config.SCREEN_AVAILABLE).
    requires_screen: bool = False

    def spec(self) -> Dict[str, Any]:
        """Return the function spec for LLM consumption."""
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters_schema,
        }

    def is_available(self) -> bool:
        """Return True if this tool should be exposed to the LLM.

        Override in subclasses that require external configuration (e.g. an
        API key) to gate availability at runtime.
        """
        return True

    @abc.abstractmethod
    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        """Async tool execution entrypoint."""
        raise NotImplementedError


# Registry & specs (dynamic)
def _load_profile_tools() -> None:
    """Load tools based on profile's tools.txt file."""
    # Determine which profile to use
    profile = config.REACHY_MINI_CUSTOM_PROFILE or "default"
    logger.info(f"Loading tools for profile: {profile}")

    # Build path to tools.txt
    # Get the profile directory path
    profile_module_path = Path(__file__).parent.parent / "profiles" / profile
    tools_txt_path = profile_module_path / "tools.txt"

    if not tools_txt_path.exists():
        logger.error(f"✗ tools.txt not found at {tools_txt_path}")
        sys.exit(1)

    # Read and parse tools.txt
    try:
        with open(tools_txt_path, "r") as f:
            lines = f.readlines()
    except Exception as e:
        logger.error(f"✗ Failed to read tools.txt: {e}")
        sys.exit(1)

    # Parse tool names (skip comments and blank lines)
    tool_names = []
    for line in lines:
        line = line.strip()
        # Skip blank lines and comments
        if not line or line.startswith("#"):
            continue
        tool_names.append(line)

    logger.info(f"Found {len(tool_names)} tools to load: {tool_names}")

    # Import each tool
    for tool_name in tool_names:
        loaded = False
        profile_error = None

        # Try profile-local tool first
        try:
            profile_tool_module = f"{PROFILES_DIRECTORY}.{profile}.{tool_name}"
            importlib.import_module(profile_tool_module)
            logger.info(f"✓ Loaded profile-local tool: {tool_name}")
            loaded = True
        except ModuleNotFoundError as e:
            # Check if it's the tool module itself that's missing (expected) or a dependency
            if tool_name in str(e):
                pass  # Tool not in profile directory, try shared tools
            else:
                # Missing import dependency within the tool file
                profile_error = f"Missing dependency: {e}"
                logger.error(f"❌ Failed to load profile-local tool '{tool_name}': {profile_error}")
                logger.error(f"  Module path: {profile_tool_module}")
        except ImportError as e:
            profile_error = f"Import error: {e}"
            logger.error(f"❌ Failed to load profile-local tool '{tool_name}': {profile_error}")
            logger.error(f"  Module path: {profile_tool_module}")
        except Exception as e:
            profile_error = f"{type(e).__name__}: {e}"
            logger.error(f"❌ Failed to load profile-local tool '{tool_name}': {profile_error}")
            logger.error(f"  Module path: {profile_tool_module}")

        # Try shared tools library if not found in profile
        if not loaded:
            try:
                shared_tool_module = f"reachy_mini_conversation_app.tools.{tool_name}"
                importlib.import_module(shared_tool_module)
                logger.info(f"✓ Loaded shared tool: {tool_name}")
                loaded = True
            except ModuleNotFoundError as e:
                if tool_name in str(e):
                    # The tool module itself doesn't exist
                    if profile_error:
                        logger.error(f"❌ Tool '{tool_name}' also not found in shared tools")
                    else:
                        logger.warning(f"⚠️ Tool '{tool_name}' not found in profile or shared tools")
                else:
                    # The tool module exists but a dependency is missing
                    logger.error(f"❌ Failed to load shared tool '{tool_name}': Missing dependency: {e}")
                    logger.error(f"  Module path: {shared_tool_module}")
            except ImportError as e:
                logger.error(f"❌ Failed to load shared tool '{tool_name}': Import error: {e}")
                logger.error(f"  Module path: {shared_tool_module}")
            except Exception as e:
                logger.error(f"❌ Failed to load shared tool '{tool_name}': {type(e).__name__}: {e}")
                logger.error(f"  Module path: {shared_tool_module}")


def _initialize_tools() -> None:
    """Populate registry once, even if module is imported repeatedly."""
    global ALL_TOOLS, ALL_TOOL_SPECS, _ALL_TOOL_INSTANCES, _TOOLS_INITIALIZED

    if _TOOLS_INITIALIZED:
        logger.debug("Tools already initialized; skipping reinitialization.")
        return

    _load_profile_tools()

    _ALL_TOOL_INSTANCES = {cls.name: cls() for cls in get_concrete_subclasses(Tool)}  # type: ignore[type-abstract]
    ALL_TOOLS = {name: t for name, t in _ALL_TOOL_INSTANCES.items() if _tool_enabled(t)}
    ALL_TOOL_SPECS = [tool.spec() for tool in ALL_TOOLS.values()]

    for name, t in _ALL_TOOL_INSTANCES.items():
        if _tool_enabled(t):
            logger.info(f"tool registered: {name} - {t.description}")
        elif t.requires_screen and not config.SCREEN_AVAILABLE:
            logger.info(f"tool skipped (no screen): {name}")
        else:
            logger.info(f"tool skipped (unavailable): {name}")

    _TOOLS_INITIALIZED = True


def _tool_enabled(t: "Tool") -> bool:
    """Return True if a tool is available AND (a screen exists OR it needs none)."""
    if t.requires_screen and not config.SCREEN_AVAILABLE:
        return False
    return t.is_available()


_initialize_tools()


def get_tool_specs(exclusion_list: list[str] = []) -> list[Dict[str, Any]]:
    """Get tool specs, dynamically checking availability.

    Tools whose ``is_available()`` returns ``False`` at call time (or that need a
    screen when none is present) are excluded, allowing runtime configuration (e.g.
    setting an API key) to enable tools without restarting the process.
    """
    return [
        t.spec()
        for t in _ALL_TOOL_INSTANCES.values()
        if _tool_enabled(t) and t.name not in exclusion_list
    ]


# Dispatcher
def _safe_load_obj(args_json: str) -> Dict[str, Any]:
    try:
        parsed_args = json.loads(args_json or "{}")
        return parsed_args if isinstance(parsed_args, dict) else {}
    except Exception:
        logger.warning("bad args_json=%r", args_json)
        return {}


async def dispatch_tool_call(tool_name: str, args_json: str, deps: ToolDependencies) -> Dict[str, Any]:
    """Dispatch a tool call by name with JSON args and dependencies."""
    tool = _ALL_TOOL_INSTANCES.get(tool_name)

    if not tool:
        return {"error": f"unknown tool: {tool_name}"}

    # Code-level backstop for disabled tools (e.g. no screen / missing config): the
    # model shouldn't see them, but a hallucinated/echoed call or a browser-injected
    # nudge could still name one. Refuse BEFORE the activity gate, so a disabled entry
    # tool can't mutate activity state on its way to erroring.
    if not _tool_enabled(tool):
        logger.info("tool refused (disabled/unavailable): %s", tool_name)
        return {"error": f"tool unavailable: {tool_name}"}

    # Enforce the current-activity separation (storybook vs read-along): entry tools
    # switch activity (closing the other); within tools are refused when their
    # activity isn't current. Activity-agnostic tools pass through.
    from reachy_mini_conversation_app.activity_state import gate_tool_call

    gate_error = gate_tool_call(tool_name)
    if gate_error is not None:
        return gate_error

    args = _safe_load_obj(args_json)
    try:
        return await tool(deps, **args)
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        logger.exception("Tool error in %s: %s", tool_name, msg)
        return {"error": msg}
