"""Single source of truth for the *current activity* (storybook vs read-along).

The kids app offers two reading activities that share one ``汪汪`` persona but must
never run at once and must never bleed into each other:

* **storybook** (``story``) — the robot generates and *narrates* picture books
  (tools ``story_book_*``, state in :class:`StoryStore`).
* **read-along** (``read_along``) — Ello-style, the *child* reads English while the
  robot scaffolds (tools ``read_along_*``, state in :class:`ReadAlongStore`).

This module is the authority for which one is live. Calling an *entry* tool
(:data:`ENTRY_TOOLS`) switches to that activity and tears the other one down; a
*within* tool (:data:`WITHIN_TOOLS`) is only allowed while its activity is current.
``dispatch_tool_call`` enforces this for both backends (and the auto-read loop), and
the browser tap/select routes refuse actions for a non-current activity. The rule is
deliberately enforced in code, not in the prompt.
"""

from __future__ import annotations
import logging
import threading
from typing import Any, Dict, Optional


logger = logging.getLogger(__name__)

STORY = "story"
READ_ALONG = "read_along"

# Tools that START or SWITCH to an activity (calling one makes it current and closes
# the other). These are the natural "begin this activity" actions.
ENTRY_TOOLS: Dict[str, str] = {
    "story_book_create": STORY,
    "story_book_open": STORY,
    "story_book_shelf": STORY,
    "read_along_start": READ_ALONG,
}

# Tools that operate WITHIN an activity — only valid while that activity is current.
WITHIN_TOOLS: Dict[str, str] = {
    "story_book_go_to_page": STORY,
    "story_book_close": STORY,
    "read_along_cue": READ_ALONG,
    "read_along_grade": READ_ALONG,
    "read_along_next_page": READ_ALONG,
    "read_along_finish": READ_ALONG,
}


def tool_activity(tool_name: str) -> Optional[str]:
    """Return the activity a tool belongs to, or ``None`` for activity-agnostic tools."""
    return ENTRY_TOOLS.get(tool_name) or WITHIN_TOOLS.get(tool_name)


class ActivityState:
    """Process-wide singleton tracking the one live reading activity."""

    _instance: Optional[ActivityState] = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        """Initialise with no activity selected."""
        self._current: Optional[str] = None

    @classmethod
    def get(cls) -> ActivityState:
        """Return the singleton instance, creating it on first call."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @property
    def current(self) -> Optional[str]:
        """The activity currently live (``"story"``/``"read_along"``), or ``None``."""
        return self._current

    def allows(self, activity: str) -> bool:
        """Return True if an action for ``activity`` is permitted now (no other live)."""
        return self._current is None or self._current == activity

    def activate(self, activity: str) -> None:
        """Make ``activity`` current; tear down the other activity if it was live."""
        if activity not in (STORY, READ_ALONG):
            return
        if self._current and self._current != activity:
            self._close_activity(self._current)
        if self._current != activity:
            logger.info("activity: switching to %s", activity)
        self._current = activity

    def deactivate(self, activity: str) -> None:
        """Clear ``current`` if ``activity`` is the one currently live."""
        if self._current == activity:
            logger.info("activity: %s ended", activity)
            self._current = None

    def reset(self) -> None:
        """Clear the current activity (used in tests)."""
        self._current = None

    @staticmethod
    def _close_activity(activity: str) -> None:
        """Tear down the given activity's live state (lazy imports avoid cycles)."""
        try:
            if activity == STORY:
                from reachy_mini_conversation_app.story_store import StoryStore

                StoryStore.get().close_story()
            elif activity == READ_ALONG:
                from reachy_mini_conversation_app.read_along_store import ReadAlongStore

                ReadAlongStore.get().close()
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("activity: failed to close %s: %s", activity, e)


def gate_tool_call(tool_name: str) -> Optional[Dict[str, Any]]:
    """Enforce activity rules for a tool call (called from ``dispatch_tool_call``).

    Entry tools switch the current activity (closing the other). Within tools are
    refused with an error dict when their activity is not current. Activity-agnostic
    tools always pass. Returns an error dict to short-circuit the call, or ``None``.
    """
    state = ActivityState.get()
    entry = ENTRY_TOOLS.get(tool_name)
    if entry is not None:
        state.activate(entry)
        return None
    within = WITHIN_TOOLS.get(tool_name)
    if within is not None and not state.allows(within):
        logger.info(
            "activity: refused %s (within %s) while current=%s",
            tool_name, within, state.current,
        )
        other = "英文朗讀" if within == STORY else "說故事繪本"
        want = "說故事繪本" if within == STORY else "英文朗讀"
        return {
            "error": (
                f"現在正在進行「{other}」活動，不能使用「{want}」的工具。"
                f"請先結束目前的活動，或讓小朋友說要改做{want}。"
            )
        }
    return None
