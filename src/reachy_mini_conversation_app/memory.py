"""Long-term memory store for the Reachy Mini conversation app.

Persists user facts, preferences, and conversation events as individual
Markdown files with YAML frontmatter (Zettelkasten-style) so the robot
can remember important information across sessions.

Architecture — two independent memory layers:

* **Global memory** (``MemoryStore.for_global``) — user-level facts and
  events (name, age, preferences, conversation highlights).  Shared
  across all profiles.  Stored at ``{instance_path}/memories/facts/``
  and ``events/``.

* **Profile memory** (``MemoryStore.for_profile``) — per-profile
  activity records (games played, topics explored, challenges completed).
  Each profile gets its own isolated directory at
  ``{instance_path}/memories/profiles/{profile_name}/facts/`` and
  ``events/``.  Switching profiles swaps to a different store; profiles
  never share memory with each other.
"""

import json
import logging
import os
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Literal, Optional

logger = logging.getLogger(__name__)

DEFAULT_MAX_MEMORIES = 20
DEFAULT_MAX_PROFILE_MEMORIES = 10

# Legacy paths (for migration)
_LEGACY_FILENAME = "memories.json"
_LEGACY_PROFILE_DIR = "profile_memories"


# ------------------------------------------------------------------
# Data model
# ------------------------------------------------------------------


@dataclass
class MemoryEntry:
    """A single memory entry."""

    id: str
    type: Literal["fact", "event"]
    content: str
    created: str  # ISO-8601
    updated: str  # ISO-8601
    tags: List[str] = field(default_factory=list)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

_ILLEGAL_CHARS = re.compile(r'[/\\:*?"<>|\s]+')


def _slugify(content: str, entry_id: str, max_chars: int = 20) -> str:
    """Create a filename-safe slug from *content* with *entry_id* suffix.

    Takes up to *max_chars* characters from content (stripping illegal
    chars), then appends ``_{entry_id}``.  Falls back to ``"memory"``
    when the cleaned content is empty.
    """
    cleaned = _ILLEGAL_CHARS.sub("", content)[:max_chars]
    if not cleaned:
        cleaned = "memory"
    return f"{cleaned}_{entry_id}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------------
# Markdown serialisation (no PyYAML dependency)
# ------------------------------------------------------------------


def _entry_to_markdown(entry: MemoryEntry) -> str:
    """Serialize a MemoryEntry to Markdown with YAML frontmatter."""
    tags_str = "[" + ", ".join(f'"{t}"' for t in entry.tags) + "]" if entry.tags else "[]"
    return (
        "---\n"
        f"id: {entry.id}\n"
        f"type: {entry.type}\n"
        f"created: {entry.created}\n"
        f"updated: {entry.updated}\n"
        f"tags: {tags_str}\n"
        "---\n"
        "\n"
        f"{entry.content}\n"
    )


def _markdown_to_entry(text: str) -> Optional[MemoryEntry]:
    """Parse a Markdown file with YAML frontmatter into a MemoryEntry.

    Returns ``None`` when the file is malformed.
    """
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None

    frontmatter = parts[1].strip()
    body = parts[2].strip()

    meta: dict = {}
    for line in frontmatter.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()

    entry_id = meta.get("id")
    entry_type = meta.get("type")
    if not entry_id or entry_type not in ("fact", "event"):
        return None

    # Parse tags: "[\"consolidated\", \"merged\"]" → list
    tags: List[str] = []
    raw_tags = meta.get("tags", "[]")
    # Strip brackets and split by comma
    inner = raw_tags.strip("[] ")
    if inner:
        tags = [t.strip().strip('"').strip("'") for t in inner.split(",") if t.strip()]

    return MemoryEntry(
        id=entry_id,
        type=entry_type,  # type: ignore[arg-type]
        content=body,
        created=meta.get("created", ""),
        updated=meta.get("updated", ""),
        tags=tags,
    )


# ------------------------------------------------------------------
# Markdown-backed memory store
# ------------------------------------------------------------------


class MarkdownMemoryStore:
    """Directory-of-Markdown long-term memory store.

    Each memory entry is a ``.md`` file with YAML frontmatter.  Files
    are organized into ``facts/`` and ``events/`` subdirectories.

    Thread-safe: all mutations are protected by a lock.
    """

    def __init__(
        self,
        facts_dir: Path,
        events_dir: Path,
        max_memories: int = DEFAULT_MAX_MEMORIES,
        header: str = "## 長期記憶",
        legacy_json_path: Optional[Path] = None,
    ) -> None:
        self._facts_dir = facts_dir
        self._events_dir = events_dir
        self._max = max_memories
        self._header = header
        self._lock = threading.Lock()
        self._legacy_json_path = legacy_json_path

        # Ensure directories exist
        self._facts_dir.mkdir(parents=True, exist_ok=True)
        self._events_dir.mkdir(parents=True, exist_ok=True)

        # One-time migration from old JSON format
        self._migrate_json_if_needed()

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def for_global(
        cls,
        instance_path: Optional[str | Path] = None,
        max_memories: int = DEFAULT_MAX_MEMORIES,
    ) -> "MarkdownMemoryStore":
        """Create a store for global (non-profile) memories."""
        if instance_path is not None:
            base = Path(instance_path) / "memories"
            legacy = Path(instance_path) / _LEGACY_FILENAME
        else:
            base = Path.home() / ".reachy_mini_memories"
            legacy = Path.home() / ".reachy_mini_memories.json"

        return cls(
            facts_dir=base / "facts",
            events_dir=base / "events",
            max_memories=max_memories,
            header="## 長期記憶",
            legacy_json_path=legacy,
        )

    @classmethod
    def for_profile(
        cls,
        profile_name: str,
        instance_path: Optional[str | Path] = None,
        max_memories: int = DEFAULT_MAX_PROFILE_MEMORIES,
    ) -> "MarkdownMemoryStore":
        """Create a store scoped to a specific profile."""
        safe_name = re.sub(r"[^\w\-]", "_", profile_name)

        if instance_path is not None:
            base = Path(instance_path) / "memories" / "profiles" / safe_name
            legacy = Path(instance_path) / _LEGACY_PROFILE_DIR / f"{safe_name}.json"
        else:
            base = Path.home() / ".reachy_mini_memories" / "profiles" / safe_name
            legacy = Path.home() / ".reachy_mini_profile_memories" / f"{safe_name}.json"

        return cls(
            facts_dir=base / "facts",
            events_dir=base / "events",
            max_memories=max_memories,
            header=f"## 角色記憶（{profile_name}）",
            legacy_json_path=legacy,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(self, content: str, memory_type: Literal["fact", "event"] = "fact") -> dict:
        """Add a new memory.  Evicts the oldest entry if at capacity.

        Returns a dict with ``id`` and ``content`` keys for backward
        compatibility with tool callers.
        """
        entry = MemoryEntry(
            id=uuid.uuid4().hex[:8],
            type=memory_type,
            content=content.strip(),
            created=_now_iso(),
            updated=_now_iso(),
        )

        with self._lock:
            self._write_entry(self._dir_for_type(memory_type), entry)

            # Evict oldest when over capacity
            all_entries = self._read_all_unlocked()
            while len(all_entries) > self._max:
                oldest = all_entries[0]
                self._delete_by_id(oldest.id)
                logger.info("Memory evicted (capacity): %s", oldest.content[:60])
                all_entries = all_entries[1:]

        logger.info("Memory saved [%s]: %s", memory_type, content[:80])
        return {"id": entry.id, "content": entry.content}

    def remove(self, memory_id: str) -> bool:
        """Remove a memory by its ID.  Returns True if found and removed."""
        with self._lock:
            return self._delete_by_id(memory_id)

    def list_all(self) -> list:
        """Return all stored memories (oldest first) as dicts for backward compat."""
        with self._lock:
            entries = self._read_all_unlocked()
        return [
            {"id": e.id, "type": e.type, "content": e.content, "timestamp": e.created}
            for e in entries
        ]

    def get_entries(self) -> List[MemoryEntry]:
        """Return all stored memories as typed MemoryEntry objects."""
        with self._lock:
            return self._read_all_unlocked()

    def replace_entries(self, entries: List[MemoryEntry]) -> None:
        """Atomically replace all files with the given entries.

        Used by the consolidation system to swap in merged memories.
        """
        with self._lock:
            # Remove all existing files
            for md in self._facts_dir.glob("*.md"):
                md.unlink()
            for md in self._events_dir.glob("*.md"):
                md.unlink()
            # Write new entries
            for entry in entries:
                self._write_entry(self._dir_for_type(entry.type), entry)

    def format_for_prompt(self) -> str:
        """Format all memories into a text block suitable for the system prompt.

        Returns an empty string when there are no memories.
        """
        with self._lock:
            entries = self._read_all_unlocked()

        if not entries:
            return ""

        lines = [self._header, "以下是你記得的重要資訊，請在對話中自然地運用這些記憶：", ""]
        for e in entries:
            tag = "📌" if e.type == "fact" else "📝"
            lines.append(f"- {tag} [{e.id}] {e.content}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _dir_for_type(self, memory_type: str) -> Path:
        return self._facts_dir if memory_type == "fact" else self._events_dir

    def _write_entry(self, target_dir: Path, entry: MemoryEntry) -> None:
        """Write an entry to disk atomically (write-then-rename)."""
        slug = _slugify(entry.content, entry.id)
        final_path = target_dir / f"{slug}.md"
        tmp_path = final_path.with_suffix(".tmp")
        tmp_path.write_text(_entry_to_markdown(entry), encoding="utf-8")
        tmp_path.replace(final_path)

    def _read_all_unlocked(self) -> List[MemoryEntry]:
        """Read all entries from both dirs, sorted by created (oldest first).

        Must be called while holding ``self._lock``.
        """
        entries: List[MemoryEntry] = []
        for d in (self._facts_dir, self._events_dir):
            for md_file in d.glob("*.md"):
                try:
                    text = md_file.read_text(encoding="utf-8")
                    entry = _markdown_to_entry(text)
                    if entry is not None:
                        entries.append(entry)
                    else:
                        logger.warning("Skipping malformed memory file: %s", md_file)
                except Exception as exc:
                    logger.warning("Failed to read memory file %s: %s", md_file, exc)

        entries.sort(key=lambda e: e.created)
        return entries

    def _delete_by_id(self, memory_id: str) -> bool:
        """Delete the file matching ``*_{memory_id}.md``.  Returns True if found."""
        for d in (self._facts_dir, self._events_dir):
            for md_file in d.glob(f"*_{memory_id}.md"):
                md_file.unlink()
                logger.info("Memory removed: %s", md_file.name)
                return True
        return False

    # ------------------------------------------------------------------
    # Migration from legacy JSON format
    # ------------------------------------------------------------------

    def _migrate_json_if_needed(self) -> None:
        """One-time migration from old ``memories.json`` format."""
        if self._legacy_json_path is None:
            return
        if not self._legacy_json_path.exists():
            return

        try:
            raw = self._legacy_json_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, list):
                logger.warning("Legacy memory file has unexpected format; skipping migration.")
                return

            migrated = 0
            for item in data:
                if not isinstance(item, dict):
                    continue
                content = item.get("content", "").strip()
                if not content:
                    continue

                # Map old "summary" type to "event"
                raw_type = item.get("type", "fact")
                memory_type = "event" if raw_type == "summary" else raw_type
                if memory_type not in ("fact", "event"):
                    memory_type = "fact"

                old_id = item.get("id", uuid.uuid4().hex[:8])
                # Truncate long IDs from old format (12-char hex → 8-char)
                entry_id = old_id[:8]

                timestamp = item.get("timestamp", _now_iso())

                entry = MemoryEntry(
                    id=entry_id,
                    type=memory_type,  # type: ignore[arg-type]
                    content=content,
                    created=timestamp,
                    updated=timestamp,
                )
                target_dir = self._facts_dir if memory_type == "fact" else self._events_dir
                self._write_entry(target_dir, entry)
                migrated += 1

            # Rename old file so migration is not repeated
            migrated_path = self._legacy_json_path.with_suffix(".json.migrated")
            self._legacy_json_path.rename(migrated_path)
            logger.info(
                "Migrated %d memories from %s → Markdown files (old file renamed to %s)",
                migrated,
                self._legacy_json_path,
                migrated_path,
            )

        except Exception as exc:
            logger.warning("Failed to migrate legacy memories from %s: %s", self._legacy_json_path, exc)


# Backward-compatible alias
MemoryStore = MarkdownMemoryStore
