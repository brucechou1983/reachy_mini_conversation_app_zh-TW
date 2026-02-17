"""Long-term memory store for the Reachy Mini conversation app.

Persists user facts, preferences, and conversation summaries as a JSON
file so the robot can remember important information across sessions.
"""

import json
import logging
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

logger = logging.getLogger(__name__)

DEFAULT_MAX_MEMORIES = 20
DEFAULT_MAX_PROFILE_MEMORIES = 10
_FILENAME = "memories.json"
_PROFILE_MEMORIES_DIR = "profile_memories"


def _fallback_path() -> Path:
    """Return a fallback path when no instance_path is available."""
    return Path.home() / ".reachy_mini_memories.json"


class MemoryStore:
    """Simple JSON-backed long-term memory store.

    Each memory entry is a dict with:
        id:        unique identifier (12-char hex)
        type:      "fact" | "summary"
        content:   the text of the memory
        timestamp: ISO-8601 creation time

    Thread-safe: all mutations are protected by a lock.
    """

    def __init__(
        self,
        instance_path: Optional[str | Path] = None,
        max_memories: int = DEFAULT_MAX_MEMORIES,
        header: str = "## 長期記憶",
    ) -> None:
        if instance_path is not None:
            self._path = Path(instance_path) / _FILENAME
        else:
            self._path = _fallback_path()

        self._max = max_memories
        self._header = header
        self._lock = threading.Lock()
        self._memories: List[Dict[str, Any]] = []
        self._load()

    @classmethod
    def for_profile(
        cls,
        profile_name: str,
        instance_path: Optional[str | Path] = None,
        max_memories: int = DEFAULT_MAX_PROFILE_MEMORIES,
    ) -> "MemoryStore":
        """Create a MemoryStore scoped to a specific profile.

        Stores data in ``{instance_path}/profile_memories/{safe_name}.json``.
        """
        safe_name = re.sub(r"[^\w\-]", "_", profile_name)
        if instance_path is not None:
            path = Path(instance_path) / _PROFILE_MEMORIES_DIR / f"{safe_name}.json"
        else:
            path = Path.home() / ".reachy_mini_profile_memories" / f"{safe_name}.json"

        store = cls.__new__(cls)
        store._path = path
        store._max = max_memories
        store._header = f"## 角色記憶（{profile_name}）"
        store._lock = threading.Lock()
        store._memories = []
        store._load()
        return store

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(self, content: str, memory_type: Literal["fact", "summary"] = "fact") -> Dict[str, Any]:
        """Add a new memory. Evicts the oldest entry if at capacity."""
        entry: Dict[str, Any] = {
            "id": uuid.uuid4().hex[:12],
            "type": memory_type,
            "content": content.strip(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self._memories.append(entry)

            # Evict oldest when over capacity
            while len(self._memories) > self._max:
                evicted = self._memories.pop(0)
                logger.info("Memory evicted (capacity): %s", evicted.get("content", "")[:60])

            self._save()

        logger.info("Memory saved [%s]: %s", memory_type, content[:80])
        return entry

    def remove(self, memory_id: str) -> bool:
        """Remove a memory by its ID. Returns True if found and removed."""
        with self._lock:
            for i, m in enumerate(self._memories):
                if m["id"] == memory_id:
                    removed = self._memories.pop(i)
                    self._save()
                    logger.info("Memory removed: %s", removed.get("content", "")[:60])
                    return True
        return False

    def list_all(self) -> List[Dict[str, Any]]:
        """Return all stored memories (newest last)."""
        with self._lock:
            return list(self._memories)

    def format_for_prompt(self) -> str:
        """Format all memories into a text block suitable for the system prompt.

        Returns an empty string when there are no memories.
        """
        with self._lock:
            memories = list(self._memories)

        if not memories:
            return ""

        lines = [self._header, "以下是你記得的重要資訊，請在對話中自然地運用這些記憶：", ""]
        for m in memories:
            tag = "📌" if m["type"] == "fact" else "📝"
            lines.append(f"- {tag} [{m['id']}] {m['content']}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not self._path.exists():
            self._memories = []
            return
        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, list):
                self._memories = data
            else:
                logger.warning("Unexpected memory file format; starting fresh.")
                self._memories = []
        except Exception as e:
            logger.warning("Failed to load memories from %s: %s", self._path, e)
            self._memories = []

    def _save(self) -> None:
        """Atomically persist memories to disk (write-then-rename)."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self._memories, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            tmp.replace(self._path)
        except Exception as e:
            logger.warning("Failed to save memories to %s: %s", self._path, e)
