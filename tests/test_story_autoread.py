"""Tests for the shared StoryReaderMixin auto-read state machine."""

import asyncio
from unittest.mock import MagicMock

import pytest

import reachy_mini_conversation_app.story_autoread as sa
from reachy_mini_conversation_app.story_autoread import StoryReaderMixin


class _FakeHandler(StoryReaderMixin):
    """Minimal handler exercising the mixin without a real backend."""

    def __init__(self):
        self.deps = MagicMock()
        self.output_queue = asyncio.Queue()
        self.output_sample_rate = 24000
        self.narrated: list[str] = []
        self._init_story_state()

    async def _story_request_narration(self, instruction: str) -> None:
        self.narrated.append(instruction)


def _page(page, next_page, last, instruction="read me"):
    return {
        "status": "ok",
        "page": page,
        "next_page": next_page,
        "is_last_page": last,
        "instruction": instruction,
    }


def _mock_dispatch(monkeypatch, results):
    """Patch dispatch_tool_call to return queued results by call order."""
    calls = []

    async def fake(tool_name, args_json, deps):
        calls.append((tool_name, args_json))
        return results.pop(0) if results else {"status": "ok"}

    monkeypatch.setattr(sa, "dispatch_tool_call", fake)
    return calls


@pytest.mark.asyncio
async def test_apply_page_result_sets_state_and_narrates():
    h = _FakeHandler()
    await h.apply_story_page_result(_page(1, 2, False, "頁面一"))
    assert h._story_next_page == 2
    assert h._story_is_last_page is False
    assert h.narrated == ["頁面一"]
    assert h._story_audio_samples == 0  # reset for the new page


@pytest.mark.asyncio
async def test_note_story_audio_only_counts_when_active():
    h = _FakeHandler()
    h.note_story_audio(1000)            # inactive (no page set) -> ignored
    assert h._story_audio_samples == 0
    h._story_next_page = 2              # now reading a page
    h.note_story_audio(1000)
    h.note_story_audio(500)
    assert h._story_audio_samples == 1500


@pytest.mark.asyncio
async def test_begin_autoread_reads_first_page(monkeypatch):
    calls = _mock_dispatch(monkeypatch, [_page(1, 2, False, "第一頁")])
    h = _FakeHandler()
    await h.begin_story_autoread(1)
    await h._story_advance_task        # let the kicked-off task finish
    assert calls[0] == ("story_book_go_to_page", '{"page": 1}')
    assert h.narrated == ["第一頁"]
    assert h._story_next_page == 2


@pytest.mark.asyncio
async def test_turn_finished_schedules_next_page(monkeypatch):
    calls = _mock_dispatch(monkeypatch, [_page(2, 3, False, "第二頁")])
    h = _FakeHandler()
    h._story_next_page = 2
    h.note_story_audio(10)             # narrated something
    monkeypatch.setattr(h, "_estimate_remaining_audio", lambda: 0.0)
    h.story_turn_finished()
    assert h._story_advance_task is not None
    await h._story_advance_task
    assert calls[0] == ("story_book_go_to_page", '{"page": 2}')
    assert h.narrated == ["第二頁"]


@pytest.mark.asyncio
async def test_turn_finished_noop_without_narration():
    h = _FakeHandler()
    h._story_next_page = 2
    # no note_story_audio -> samples 0 -> nothing scheduled
    h.story_turn_finished()
    assert h._story_advance_task is None


@pytest.mark.asyncio
async def test_last_page_schedules_close(monkeypatch):
    calls = _mock_dispatch(monkeypatch, [{"status": "ok"}])
    h = _FakeHandler()
    h._story_is_last_page = True
    h.note_story_audio(10)
    monkeypatch.setattr(h, "_estimate_remaining_audio", lambda: 0.0)
    h.story_turn_finished()
    await h._story_advance_task
    assert calls[0][0] == "story_book_close"
    assert h.narrated and "故事說完了" in h.narrated[-1]


@pytest.mark.asyncio
async def test_cancel_resets_state(monkeypatch):
    _mock_dispatch(monkeypatch, [])
    h = _FakeHandler()
    h._story_next_page = 3
    h._story_is_last_page = True
    h._story_audio_samples = 99
    h.cancel_story_advance()
    assert h._story_next_page is None
    assert h._story_is_last_page is False
    assert h._story_audio_samples == 0


@pytest.mark.asyncio
async def test_failed_go_to_page_stops_loop(monkeypatch):
    _mock_dispatch(monkeypatch, [{"status": "error", "error": "no such page"}])
    h = _FakeHandler()
    await h._story_auto_advance(99, 0.0)
    assert h.narrated == []             # nothing narrated
    assert h._story_next_page is None
