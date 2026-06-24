"""Tests for ActivityState: the single source of truth for the live activity."""

import pytest

import reachy_mini_conversation_app.activity_state as act
from reachy_mini_conversation_app.activity_state import (
    STORY,
    READ_ALONG,
    ActivityState,
    tool_activity,
    gate_tool_call,
)


@pytest.fixture(autouse=True)
def _reset():
    ActivityState.get().reset()
    yield
    ActivityState.get().reset()


def test_starts_with_no_activity():
    assert ActivityState.get().current is None


def test_allows_when_none_or_same():
    s = ActivityState.get()
    assert s.allows(STORY) and s.allows(READ_ALONG)   # None allows both
    s.activate(STORY)
    assert s.allows(STORY)
    assert not s.allows(READ_ALONG)                    # other activity blocked


def test_activate_switches_and_closes_other(monkeypatch):
    closed = []
    # stub the two stores' close paths via the lazy import targets
    import reachy_mini_conversation_app.story_store as ss
    import reachy_mini_conversation_app.read_along_store as ras
    monkeypatch.setattr(ss.StoryStore, "get", classmethod(
        lambda cls: type("S", (), {"close_story": lambda self: closed.append("story")})()
    ))
    monkeypatch.setattr(ras.ReadAlongStore, "get", classmethod(
        lambda cls: type("R", (), {"close": lambda self: closed.append("read_along")})()
    ))

    s = ActivityState.get()
    s.activate(STORY)
    assert s.current == STORY
    assert closed == []                      # nothing to close on first activation
    s.activate(READ_ALONG)
    assert s.current == READ_ALONG
    assert closed == ["story"]               # switching closed the story activity
    s.activate(STORY)
    assert closed == ["story", "read_along"]  # and now closed read-along


def test_deactivate_only_clears_matching():
    s = ActivityState.get()
    s.activate(STORY)
    s.deactivate(READ_ALONG)                  # not current → no-op
    assert s.current == STORY
    s.deactivate(STORY)
    assert s.current is None


def test_tool_activity_classification():
    assert tool_activity("story_book_create") == STORY
    assert tool_activity("story_book_go_to_page") == STORY
    assert tool_activity("read_along_start") == READ_ALONG
    assert tool_activity("read_along_next_page") == READ_ALONG
    assert tool_activity("dance") is None
    assert tool_activity("play_emotion") is None


def test_gate_entry_tool_activates(monkeypatch):
    # avoid real store teardown
    monkeypatch.setattr(ActivityState, "_close_activity", staticmethod(lambda a: None))
    assert gate_tool_call("read_along_start") is None
    assert ActivityState.get().current == READ_ALONG
    # entry tool for the other activity switches (never refused)
    assert gate_tool_call("story_book_create") is None
    assert ActivityState.get().current == STORY


def test_gate_within_tool_refused_when_other_active(monkeypatch):
    monkeypatch.setattr(ActivityState, "_close_activity", staticmethod(lambda a: None))
    ActivityState.get().activate(READ_ALONG)
    err = gate_tool_call("story_book_go_to_page")          # story within-tool during read-along
    assert err is not None and "error" in err
    # the read-along within-tools still pass
    assert gate_tool_call("read_along_next_page") is None


def test_gate_within_tool_allowed_when_none_or_same(monkeypatch):
    monkeypatch.setattr(ActivityState, "_close_activity", staticmethod(lambda a: None))
    # current is None → within tool allowed
    assert gate_tool_call("story_book_go_to_page") is None
    ActivityState.get().activate(STORY)
    assert gate_tool_call("story_book_close") is None


def test_gate_agnostic_tool_always_passes(monkeypatch):
    monkeypatch.setattr(ActivityState, "_close_activity", staticmethod(lambda a: None))
    ActivityState.get().activate(READ_ALONG)
    assert gate_tool_call("dance") is None
    assert gate_tool_call("play_emotion") is None
    assert gate_tool_call("save_memory") is None


def test_module_constants_distinct():
    assert STORY != READ_ALONG
    assert act.ENTRY_TOOLS and act.WITHIN_TOOLS


# --- integration: the gate is actually wired into dispatch_tool_call ---


class _FakeTool:
    def __init__(self):
        self.calls = 0

    async def __call__(self, deps, **kwargs):
        self.calls += 1
        return {"status": "ok"}


@pytest.mark.asyncio
async def test_dispatch_blocks_within_tool_of_other_activity(monkeypatch):
    from reachy_mini_conversation_app.tools import core_tools as ct

    monkeypatch.setattr(ActivityState, "_close_activity", staticmethod(lambda a: None))
    tool = _FakeTool()
    monkeypatch.setitem(ct._ALL_TOOL_INSTANCES, "story_book_go_to_page", tool)

    ActivityState.get().activate(READ_ALONG)
    res = await ct.dispatch_tool_call("story_book_go_to_page", "{}", deps=object())
    assert "error" in res          # refused by the activity gate
    assert tool.calls == 0         # the tool body never ran


@pytest.mark.asyncio
async def test_dispatch_entry_tool_activates(monkeypatch):
    from reachy_mini_conversation_app.tools import core_tools as ct

    monkeypatch.setattr(ActivityState, "_close_activity", staticmethod(lambda a: None))
    tool = _FakeTool()
    monkeypatch.setitem(ct._ALL_TOOL_INSTANCES, "read_along_start", tool)

    ActivityState.get().activate(STORY)
    res = await ct.dispatch_tool_call("read_along_start", "{}", deps=object())
    assert res == {"status": "ok"}             # entry tool ran
    assert ActivityState.get().current == READ_ALONG  # and switched activity


@pytest.mark.asyncio
async def test_story_book_close_deactivates_story(monkeypatch):
    """Closing the story clears the current activity (so the other shelf is tappable)."""
    from reachy_mini_conversation_app.story_store import StoryStore
    from reachy_mini_conversation_app.tools.story_book_close import StoryBookClose

    monkeypatch.setattr(ActivityState, "_close_activity", staticmethod(lambda a: None))
    StoryStore._instance = None
    ActivityState.get().activate(STORY)
    res = await StoryBookClose()(object())
    assert res["status"] == "closed"
    assert ActivityState.get().current is None
    StoryStore._instance = None
