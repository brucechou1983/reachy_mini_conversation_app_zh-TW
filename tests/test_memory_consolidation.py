"""Tests for memory consolidation via Gemini."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from reachy_mini_conversation_app.memory import MarkdownMemoryStore
from reachy_mini_conversation_app.memory_consolidation import consolidate_memories


@pytest.fixture()
def store(tmp_path: Path) -> MarkdownMemoryStore:
    return MarkdownMemoryStore(
        facts_dir=tmp_path / "facts",
        events_dir=tmp_path / "events",
        max_memories=50,
    )


def _add_facts(store: MarkdownMemoryStore, n: int) -> None:
    """Add *n* fact entries to the store."""
    for i in range(n):
        store.add(f"fact_{i}", memory_type="fact")


class TestConsolidation:
    @pytest.mark.asyncio
    async def test_below_threshold_skips(self, store: MarkdownMemoryStore):
        _add_facts(store, 5)
        result = await consolidate_memories(store, api_key="fake-key", threshold=15)
        assert result is False
        assert len(store.list_all()) == 5

    @pytest.mark.asyncio
    async def test_consolidation_replaces_facts(self, store: MarkdownMemoryStore):
        _add_facts(store, 20)
        store.add("went to the park", memory_type="event")

        mock_call = AsyncMock(return_value=json.dumps(["merged fact A", "merged fact B"]))

        with patch(
            "reachy_mini_conversation_app.memory_consolidation._call_gemini",
            mock_call,
        ):
            result = await consolidate_memories(store, api_key="fake-key", threshold=15)

        assert result is True

        entries = store.get_entries()
        facts = [e for e in entries if e.type == "fact"]
        events = [e for e in entries if e.type == "event"]

        assert len(facts) == 2
        assert {f.content for f in facts} == {"merged fact A", "merged fact B"}
        # Events preserved
        assert len(events) == 1
        assert events[0].content == "went to the park"

    @pytest.mark.asyncio
    async def test_consolidated_entries_tagged(self, store: MarkdownMemoryStore):
        _add_facts(store, 20)

        mock_call = AsyncMock(return_value=json.dumps(["consolidated entry"]))

        with patch(
            "reachy_mini_conversation_app.memory_consolidation._call_gemini",
            mock_call,
        ):
            await consolidate_memories(store, api_key="fake-key", threshold=15)

        facts = [e for e in store.get_entries() if e.type == "fact"]
        assert len(facts) == 1
        assert "consolidated" in facts[0].tags

    @pytest.mark.asyncio
    async def test_api_failure_raises(self, store: MarkdownMemoryStore):
        _add_facts(store, 20)

        mock_call = AsyncMock(side_effect=RuntimeError("API down"))

        with patch(
            "reachy_mini_conversation_app.memory_consolidation._call_gemini",
            mock_call,
        ):
            with pytest.raises(RuntimeError, match="API down"):
                await consolidate_memories(store, api_key="fake-key", threshold=15)

        # Original entries should still be intact (no replace_entries called)
        assert len(store.list_all()) == 20
