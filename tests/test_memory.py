"""Tests for the Zettelkasten-style Markdown memory store."""

import json
import threading
from pathlib import Path

import pytest

from reachy_mini_conversation_app.memory import (
    MemoryEntry,
    MemoryStore,
    MarkdownMemoryStore,
    _slugify,
    _entry_to_markdown,
    _markdown_to_entry,
)


# ------------------------------------------------------------------
# _slugify
# ------------------------------------------------------------------


class TestSlugify:
    def test_chinese_content(self):
        result = _slugify("小明喜歡恐龍", "a1b2c3d4")
        assert result == "小明喜歡恐龍_a1b2c3d4"

    def test_illegal_chars_stripped(self):
        result = _slugify('a/b\\c:d*e?"f<g>h|i', "abcd1234")
        assert result == "abcdefghi_abcd1234"

    def test_truncation(self):
        long_content = "一二三四五六七八九十壹貳參肆伍陸柒捌玖拾ABC"
        result = _slugify(long_content, "12345678", max_chars=10)
        assert result == "一二三四五六七八九十_12345678"

    def test_empty_content_fallback(self):
        result = _slugify("", "abcd1234")
        assert result == "memory_abcd1234"

    def test_only_illegal_chars_fallback(self):
        result = _slugify("   /\\:  ", "abcd1234")
        assert result == "memory_abcd1234"

    def test_whitespace_stripped(self):
        result = _slugify("hello world foo", "abcd1234")
        assert result == "helloworldfoo_abcd1234"


# ------------------------------------------------------------------
# Markdown roundtrip
# ------------------------------------------------------------------


class TestMarkdownRoundtrip:
    def test_serialize_parse_identical(self):
        entry = MemoryEntry(
            id="a1b2c3d4",
            type="fact",
            content="小明今年5歲，喜歡恐龍和火車",
            created="2026-02-25T10:30:00+00:00",
            updated="2026-02-25T10:30:00+00:00",
            tags=[],
        )
        md = _entry_to_markdown(entry)
        parsed = _markdown_to_entry(md)
        assert parsed is not None
        assert parsed.id == entry.id
        assert parsed.type == entry.type
        assert parsed.content == entry.content
        assert parsed.created == entry.created
        assert parsed.updated == entry.updated
        assert parsed.tags == entry.tags

    def test_roundtrip_with_tags(self):
        entry = MemoryEntry(
            id="deadbeef",
            type="fact",
            content="Consolidated fact",
            created="2026-01-01T00:00:00+00:00",
            updated="2026-02-25T00:00:00+00:00",
            tags=["consolidated", "merged"],
        )
        md = _entry_to_markdown(entry)
        parsed = _markdown_to_entry(md)
        assert parsed is not None
        assert parsed.tags == ["consolidated", "merged"]

    def test_event_type_roundtrip(self):
        entry = MemoryEntry(
            id="11223344",
            type="event",
            content="聊了恐龍的故事",
            created="2026-02-25T10:30:00+00:00",
            updated="2026-02-25T10:30:00+00:00",
        )
        md = _entry_to_markdown(entry)
        parsed = _markdown_to_entry(md)
        assert parsed is not None
        assert parsed.type == "event"

    def test_malformed_no_frontmatter(self):
        assert _markdown_to_entry("just some text") is None

    def test_malformed_missing_id(self):
        md = "---\ntype: fact\ncreated: x\nupdated: x\ntags: []\n---\ncontent"
        assert _markdown_to_entry(md) is None

    def test_malformed_bad_type(self):
        md = "---\nid: abc\ntype: unknown\ncreated: x\nupdated: x\ntags: []\n---\ncontent"
        assert _markdown_to_entry(md) is None


# ------------------------------------------------------------------
# MarkdownMemoryStore
# ------------------------------------------------------------------


class TestMarkdownMemoryStore:
    @pytest.fixture()
    def store(self, tmp_path: Path) -> MarkdownMemoryStore:
        return MarkdownMemoryStore(
            facts_dir=tmp_path / "facts",
            events_dir=tmp_path / "events",
            max_memories=5,
        )

    def test_add_creates_file(self, store: MarkdownMemoryStore):
        result = store.add("小明喜歡恐龍", memory_type="fact")
        assert "id" in result
        md_files = list(store._facts_dir.glob("*.md"))
        assert len(md_files) == 1
        assert result["id"] in md_files[0].name

    def test_add_event_goes_to_events_dir(self, store: MarkdownMemoryStore):
        store.add("聊了恐龍", memory_type="event")
        assert len(list(store._events_dir.glob("*.md"))) == 1
        assert len(list(store._facts_dir.glob("*.md"))) == 0

    def test_remove_deletes_file(self, store: MarkdownMemoryStore):
        result = store.add("to be removed", memory_type="fact")
        mid = result["id"]
        assert store.remove(mid) is True
        assert len(list(store._facts_dir.glob("*.md"))) == 0

    def test_remove_nonexistent_returns_false(self, store: MarkdownMemoryStore):
        assert store.remove("nonexistent") is False

    def test_list_all_sorted_by_created(self, store: MarkdownMemoryStore):
        store.add("first", memory_type="fact")
        store.add("second", memory_type="event")
        store.add("third", memory_type="fact")

        entries = store.list_all()
        assert len(entries) == 3
        # Oldest first
        assert entries[0]["content"] == "first"
        assert entries[2]["content"] == "third"

    def test_format_for_prompt_empty(self, store: MarkdownMemoryStore):
        assert store.format_for_prompt() == ""

    def test_format_for_prompt_content(self, store: MarkdownMemoryStore):
        store.add("小明今年5歲", memory_type="fact")
        store.add("聊了恐龍", memory_type="event")

        prompt = store.format_for_prompt()
        assert "## 長期記憶" in prompt
        assert "📌" in prompt
        assert "📝" in prompt
        assert "小明今年5歲" in prompt
        assert "聊了恐龍" in prompt

    def test_eviction_oldest_removed(self, store: MarkdownMemoryStore):
        # max_memories=5
        for i in range(7):
            store.add(f"memory_{i}", memory_type="fact")

        entries = store.list_all()
        assert len(entries) == 5
        # First two should be evicted
        contents = [e["content"] for e in entries]
        assert "memory_0" not in contents
        assert "memory_1" not in contents
        assert "memory_6" in contents

    def test_eviction_counts_across_fact_and_event_dirs(
        self, store: MarkdownMemoryStore
    ):
        # max_memories=5. Capacity spans both dirs, so the oldest entries are
        # evicted regardless of type — here the two oldest are events.
        for i in range(4):
            store.add(f"event_{i}", memory_type="event")
        for i in range(3):
            store.add(f"fact_{i}", memory_type="fact")

        entries = store.list_all()
        assert len(entries) == 5
        contents = [e["content"] for e in entries]
        # Two oldest (events) evicted, proving eviction is not fact-only.
        assert "event_0" not in contents
        assert "event_1" not in contents
        assert "event_2" in contents
        assert "event_3" in contents
        # All facts (added later) survive.
        assert {"fact_0", "fact_1", "fact_2"}.issubset(set(contents))

    def test_get_entries_returns_typed(self, store: MarkdownMemoryStore):
        store.add("test", memory_type="fact")
        entries = store.get_entries()
        assert len(entries) == 1
        assert isinstance(entries[0], MemoryEntry)
        assert entries[0].type == "fact"

    def test_replace_entries(self, store: MarkdownMemoryStore):
        store.add("old fact", memory_type="fact")
        store.add("old event", memory_type="event")
        assert len(store.list_all()) == 2

        new_entries = [
            MemoryEntry(
                id="new12345",
                type="fact",
                content="merged fact",
                created="2026-01-01T00:00:00+00:00",
                updated="2026-01-01T00:00:00+00:00",
                tags=["consolidated"],
            ),
        ]
        store.replace_entries(new_entries)

        entries = store.list_all()
        assert len(entries) == 1
        assert entries[0]["content"] == "merged fact"

    def test_thread_safety(self, store: MarkdownMemoryStore):
        errors = []

        def writer(n: int) -> None:
            try:
                for i in range(10):
                    store.add(f"thread_{n}_item_{i}", memory_type="fact")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # max_memories=5, so at most 5 entries survive
        entries = store.list_all()
        assert len(entries) <= 5

    def test_malformed_file_skipped(self, store: MarkdownMemoryStore):
        # Add a valid entry
        store.add("valid entry", memory_type="fact")
        # Write a malformed file
        bad_file = store._facts_dir / "bad_file_12345678.md"
        bad_file.write_text("not valid markdown frontmatter", encoding="utf-8")

        entries = store.list_all()
        assert len(entries) == 1
        assert entries[0]["content"] == "valid entry"


# ------------------------------------------------------------------
# Factory methods
# ------------------------------------------------------------------


class TestFactoryMethods:
    def test_for_global(self, tmp_path: Path):
        store = MarkdownMemoryStore.for_global(instance_path=tmp_path)
        assert store._facts_dir == tmp_path / "memories" / "facts"
        assert store._events_dir == tmp_path / "memories" / "events"
        assert store._facts_dir.exists()

    def test_for_profile(self, tmp_path: Path):
        store = MarkdownMemoryStore.for_profile("storyteller", instance_path=tmp_path)
        assert "storyteller" in str(store._facts_dir)
        assert store._facts_dir.exists()

    def test_for_profile_prompt_header(self, tmp_path: Path):
        store = MarkdownMemoryStore.for_profile("storyteller", instance_path=tmp_path)
        store.add("小明完成了三道加法題", memory_type="event")

        prompt = store.format_for_prompt()
        # Profile stores use a profile-scoped header, distinct from the global one.
        assert "## 角色記憶（storyteller）" in prompt
        assert "## 長期記憶" not in prompt
        assert "小明完成了三道加法題" in prompt

    def test_backward_compat_alias(self):
        assert MemoryStore is MarkdownMemoryStore


# ------------------------------------------------------------------
# JSON migration
# ------------------------------------------------------------------


class TestMigration:
    def test_migrate_json(self, tmp_path: Path):
        legacy_json = tmp_path / "memories.json"
        legacy_data = [
            {"id": "aabbccdd1234", "type": "fact", "content": "小明今年5歲", "timestamp": "2026-01-01T00:00:00+00:00"},
            {"id": "eeff00112233", "type": "summary", "content": "聊了恐龍", "timestamp": "2026-01-02T00:00:00+00:00"},
        ]
        legacy_json.write_text(json.dumps(legacy_data, ensure_ascii=False), encoding="utf-8")

        store = MarkdownMemoryStore(
            facts_dir=tmp_path / "facts",
            events_dir=tmp_path / "events",
            legacy_json_path=legacy_json,
        )

        entries = store.list_all()
        assert len(entries) == 2

        # summary → event type mapping
        types = {e["content"]: e["type"] for e in entries}
        assert types["小明今年5歲"] == "fact"
        assert types["聊了恐龍"] == "event"

        # Old file renamed to .json.migrated
        assert not legacy_json.exists()
        assert (tmp_path / "memories.json.migrated").exists()

    def test_migration_idempotent(self, tmp_path: Path):
        """Migration doesn't run again if .json.migrated already exists."""
        legacy_json = tmp_path / "memories.json"
        legacy_data = [{"id": "aabbccdd", "type": "fact", "content": "test", "timestamp": "2026-01-01T00:00:00+00:00"}]
        legacy_json.write_text(json.dumps(legacy_data, ensure_ascii=False), encoding="utf-8")

        # First migration
        store1 = MarkdownMemoryStore(
            facts_dir=tmp_path / "facts",
            events_dir=tmp_path / "events",
            legacy_json_path=legacy_json,
        )
        assert len(store1.list_all()) == 1

        # Second init (legacy json is gone, renamed to .json.migrated)
        store2 = MarkdownMemoryStore(
            facts_dir=tmp_path / "facts",
            events_dir=tmp_path / "events",
            legacy_json_path=legacy_json,
        )
        # Should still have exactly 1 entry (not duplicated)
        assert len(store2.list_all()) == 1

    def test_no_legacy_file(self, tmp_path: Path):
        """No crash when legacy file doesn't exist."""
        store = MarkdownMemoryStore(
            facts_dir=tmp_path / "facts",
            events_dir=tmp_path / "events",
            legacy_json_path=tmp_path / "nonexistent.json",
        )
        assert len(store.list_all()) == 0

    def test_id_truncation(self, tmp_path: Path):
        """12-char legacy IDs get truncated to 8 chars."""
        legacy_json = tmp_path / "memories.json"
        legacy_data = [
            {"id": "aabbccdd1234", "type": "fact", "content": "test", "timestamp": "2026-01-01T00:00:00+00:00"}
        ]
        legacy_json.write_text(json.dumps(legacy_data, ensure_ascii=False), encoding="utf-8")

        store = MarkdownMemoryStore(
            facts_dir=tmp_path / "facts",
            events_dir=tmp_path / "events",
            legacy_json_path=legacy_json,
        )
        entries = store.list_all()
        assert len(entries) == 1
        assert len(entries[0]["id"]) == 8
