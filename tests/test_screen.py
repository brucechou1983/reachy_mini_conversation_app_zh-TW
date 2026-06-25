"""Tests for screen detection + disabling visual features when headless."""

import pytest

import reachy_mini_conversation_app.config as cfg


# --- detect_screen() resolution order ---


def test_override_wins(monkeypatch):
    for val, expected in [("false", False), ("0", False), ("no", False),
                          ("true", True), ("1", True), ("yes", True), ("on", True)]:
        monkeypatch.setenv("REACHY_MINI_HAS_SCREEN", val)
        assert cfg.detect_screen() is expected


def test_linux_uses_display_env(monkeypatch):
    monkeypatch.delenv("REACHY_MINI_HAS_SCREEN", raising=False)
    monkeypatch.setattr(cfg.sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert cfg.detect_screen() is False          # headless Pi
    monkeypatch.setenv("DISPLAY", ":0")
    assert cfg.detect_screen() is True


def test_macos_uses_coregraphics(monkeypatch):
    monkeypatch.delenv("REACHY_MINI_HAS_SCREEN", raising=False)
    monkeypatch.setattr(cfg.sys, "platform", "darwin")
    monkeypatch.setattr(cfg, "_macos_has_display", lambda: False)
    assert cfg.detect_screen() is False
    monkeypatch.setattr(cfg, "_macos_has_display", lambda: True)
    assert cfg.detect_screen() is True


def test_unknown_platform_defaults_true(monkeypatch):
    monkeypatch.delenv("REACHY_MINI_HAS_SCREEN", raising=False)
    monkeypatch.setattr(cfg.sys, "platform", "sunos5")
    assert cfg.detect_screen() is True            # fail-safe: never wrongly disable


def test_macos_helper_failsafe_on_error(monkeypatch):
    # If CoreGraphics can't be loaded, assume a screen (don't disable features).
    import ctypes
    monkeypatch.setattr(ctypes, "CDLL", lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))
    assert cfg._macos_has_display() is True


# --- tool gating: requires_screen tools hidden when no screen ---


class _FakeTool:
    def __init__(self, requires_screen, available=True):
        self.name = "fake"
        self.requires_screen = requires_screen
        self._available = available

    def is_available(self):
        return self._available


def test_tool_enabled_hides_screen_tool_when_no_screen(monkeypatch):
    from reachy_mini_conversation_app.tools import core_tools as ct

    monkeypatch.setattr(ct.config, "SCREEN_AVAILABLE", False)
    assert ct._tool_enabled(_FakeTool(requires_screen=True)) is False
    assert ct._tool_enabled(_FakeTool(requires_screen=False)) is True   # chat tools stay
    monkeypatch.setattr(ct.config, "SCREEN_AVAILABLE", True)
    assert ct._tool_enabled(_FakeTool(requires_screen=True)) is True


def test_tool_enabled_still_honors_is_available(monkeypatch):
    from reachy_mini_conversation_app.tools import core_tools as ct

    monkeypatch.setattr(ct.config, "SCREEN_AVAILABLE", True)
    assert ct._tool_enabled(_FakeTool(requires_screen=False, available=False)) is False


def test_real_visual_tools_marked_requires_screen():
    from reachy_mini_conversation_app.tools.read_along_start import ReadAlongStart
    from reachy_mini_conversation_app.tools.story_book_shelf import StoryBookShelf
    from reachy_mini_conversation_app.tools.story_book_create import StoryBookCreate
    from reachy_mini_conversation_app.tools.read_along_next_page import ReadAlongNextPage

    assert StoryBookShelf.requires_screen is True
    assert StoryBookCreate.requires_screen is True
    assert ReadAlongStart.requires_screen is True
    assert ReadAlongNextPage.requires_screen is True


# --- instructions note when no screen ---


def test_screen_mode_note(monkeypatch):
    from reachy_mini_conversation_app import prompts
    from reachy_mini_conversation_app.tools import core_tools as ct

    monkeypatch.setattr(prompts.config, "SCREEN_AVAILABLE", True)
    assert prompts._screen_mode_note() == ""

    monkeypatch.setattr(prompts.config, "SCREEN_AVAILABLE", False)
    # With a screen-dependent tool loaded → note appears.
    monkeypatch.setitem(ct._ALL_TOOL_INSTANCES, "fake_screen", _FakeTool(requires_screen=True))
    note = prompts._screen_mode_note()
    assert "沒有螢幕" in note and "故事書" in note


def test_screen_mode_note_skipped_for_profile_without_screen_tools(monkeypatch):
    """A persona with no screen tools never gets the children's-book note injected."""
    from reachy_mini_conversation_app import prompts
    from reachy_mini_conversation_app.tools import core_tools as ct

    monkeypatch.setattr(prompts.config, "SCREEN_AVAILABLE", False)
    monkeypatch.setattr(ct, "_ALL_TOOL_INSTANCES", {"chat": _FakeTool(requires_screen=False)})
    assert prompts._screen_mode_note() == ""


# --- dispatch-level backstop: a disabled tool can't execute or mutate state ---


@pytest.mark.asyncio
async def test_dispatch_refuses_disabled_tool_and_keeps_activity(monkeypatch):
    from reachy_mini_conversation_app.tools import core_tools as ct
    from reachy_mini_conversation_app.activity_state import ActivityState

    ActivityState.get().reset()
    monkeypatch.setattr(ct.config, "SCREEN_AVAILABLE", False)

    called = {"n": 0}

    class _ScreenEntryTool:
        name = "story_book_shelf"          # an ENTRY tool (would flip activity state)
        requires_screen = True

        def is_available(self):
            return True

        async def __call__(self, deps, **kw):
            called["n"] += 1
            return {"status": "ok"}

    monkeypatch.setitem(ct._ALL_TOOL_INSTANCES, "story_book_shelf", _ScreenEntryTool())

    res = await ct.dispatch_tool_call("story_book_shelf", "{}", deps=object())
    assert "error" in res                       # refused by the no-screen backstop
    assert called["n"] == 0                      # body never ran
    assert ActivityState.get().current is None   # activity state NOT mutated
    ActivityState.get().reset()
