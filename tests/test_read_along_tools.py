"""Tests for the read-along tools (no hardware/network).

Illustration generation and browser-opening are stubbed; the tools' contract
(listing, starting, cueing, paging, finishing) is verified.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Mock heavy deps so importing the tool registry doesn't require hardware.
for _mod in (
    "reachy_mini",
    "reachy_mini.media",
    "reachy_mini.media.media_manager",
    "cv2",
    "gradio",
    "openai",
    "fastrtc",
):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

from reachy_mini_conversation_app.tools import read_along_start as start_mod  # noqa: E402
from reachy_mini_conversation_app.read_along_store import ReadAlongStore  # noqa: E402
from reachy_mini_conversation_app.tools.read_along_cue import ReadAlongCue  # noqa: E402
from reachy_mini_conversation_app.tools.read_along_grade import ReadAlongGrade  # noqa: E402
from reachy_mini_conversation_app.tools.read_along_start import ReadAlongStart  # noqa: E402
from reachy_mini_conversation_app.tools.read_along_finish import ReadAlongFinish  # noqa: E402
from reachy_mini_conversation_app.tools.read_along_next_page import ReadAlongNextPage  # noqa: E402


def _mark_page_done(store):
    """Mark every word on the current page as read correctly (test helper)."""
    store.grade(list(store.session.current_words), [])


@pytest.fixture(autouse=True)
def _reset_store(monkeypatch):
    ReadAlongStore._instance = None
    # Don't touch disk / Gemini / browser during tool tests.
    monkeypatch.setattr(start_mod, "ensure_book_assets", lambda book: {"imported": True, "illustrating": False})
    monkeypatch.setattr(start_mod.webbrowser, "open", lambda *a, **k: True)
    yield
    ReadAlongStore._instance = None


@pytest.fixture
def deps():
    return MagicMock()


# --- read_along_start ---


@pytest.mark.asyncio
async def test_start_lists_books_without_id(deps):
    result = await ReadAlongStart()(deps)
    assert result["status"] == "listing"
    assert result["books"]
    assert any(b["id"] == "sel-big-feelings" for b in result["books"])


@pytest.mark.asyncio
async def test_start_unknown_book_errors(deps):
    result = await ReadAlongStart()(deps)  # warm the catalog
    result = await ReadAlongStart()(deps, book_id="nope")
    assert "error" in result
    assert result["books"]  # offers the catalog to recover


@pytest.mark.asyncio
async def test_start_opens_book(deps):
    result = await ReadAlongStart()(deps, book_id="sel-big-feelings")
    assert result["status"] == "reading"
    assert result["page"] == 1
    assert result["words"] == ["I", "have", "many", "feelings"]
    assert result["warmup"]
    assert "繪本帶讀模式" in result["protocol"]
    # session is live and the handler was bound for tap-injection
    store = ReadAlongStore.get()
    assert store.session is not None
    assert store.session.book_id == "sel-big-feelings"
    assert store.handler is deps.realtime_handler


@pytest.mark.asyncio
async def test_start_invalid_mode_defaults_to_decodable(deps):
    result = await ReadAlongStart()(deps, book_id="sel-big-feelings", mode="bogus")
    assert result["mode"] == "decodable"


# --- read_along_cue ---


@pytest.mark.asyncio
async def test_cue_requires_session(deps):
    result = await ReadAlongCue()(deps, word="happy", state="miss")
    assert "error" in result


@pytest.mark.asyncio
async def test_cue_success_after_start(deps):
    await ReadAlongStart()(deps, book_id="sel-big-feelings")
    result = await ReadAlongCue()(deps, word="feelings", state="success")
    assert result["status"] == "ok"
    assert result["state"] == "success"
    assert result["index"] == 3


@pytest.mark.asyncio
async def test_cue_unknown_word_errors(deps):
    await ReadAlongStart()(deps, book_id="sel-big-feelings")
    result = await ReadAlongCue()(deps, word="zebra", state="miss")
    assert "error" in result


@pytest.mark.asyncio
async def test_cue_invalid_state_errors(deps):
    await ReadAlongStart()(deps, book_id="sel-big-feelings")
    result = await ReadAlongCue()(deps, word="happy", state="explode")
    assert "error" in result


# --- read_along_next_page ---


@pytest.mark.asyncio
async def test_next_page_advances_when_page_complete(deps):
    await ReadAlongStart()(deps, book_id="sel-big-feelings")
    _mark_page_done(ReadAlongStore.get())
    result = await ReadAlongNextPage()(deps)
    assert result["status"] == "ok"
    assert result["page"] == 2
    assert result["words"]


@pytest.mark.asyncio
async def test_next_page_blocked_until_all_words_read(deps):
    """The signature fix: can't advance until every word is green."""
    await ReadAlongStart()(deps, book_id="sel-big-feelings")
    store = ReadAlongStore.get()
    # Only one word read correctly -> must NOT advance.
    store.cue("feelings", "success")
    result = await ReadAlongNextPage()(deps)
    assert result["status"] == "not_complete"
    assert result["remaining_words"]
    assert store.session.current_page == 0  # did not move


@pytest.mark.asyncio
async def test_next_page_requires_session(deps):
    result = await ReadAlongNextPage()(deps)
    assert "error" in result


@pytest.mark.asyncio
async def test_next_page_on_last_reports_last(deps):
    await ReadAlongStart()(deps, book_id="sel-big-feelings")
    store = ReadAlongStore.get()
    store.go_to_page(store.session.total_pages - 1)
    _mark_page_done(store)
    result = await ReadAlongNextPage()(deps)
    assert result["status"] == "last_page"


# --- read_along_grade ---


@pytest.mark.asyncio
async def test_grade_marks_correct_and_incorrect(deps):
    await ReadAlongStart()(deps, book_id="sel-big-feelings")  # "I have many feelings"
    result = await ReadAlongGrade()(deps, correct=["I", "have", "many"], incorrect=["feelings"])
    assert result["status"] == "ok"
    assert result["complete"] is False
    assert "feelings" in result["remaining_words"]


@pytest.mark.asyncio
async def test_grade_completes_page(deps):
    await ReadAlongStart()(deps, book_id="sel-big-feelings")
    result = await ReadAlongGrade()(deps, correct=["I", "have", "many", "feelings"], incorrect=[])
    assert result["complete"] is True
    assert result["remaining_words"] == []


@pytest.mark.asyncio
async def test_grade_accepts_string_lists(deps):
    await ReadAlongStart()(deps, book_id="sel-big-feelings")
    result = await ReadAlongGrade()(deps, correct="I have many feelings", incorrect="")
    assert result["complete"] is True


@pytest.mark.asyncio
async def test_grade_requires_session(deps):
    result = await ReadAlongGrade()(deps, correct=["x"], incorrect=[])
    assert "error" in result


@pytest.mark.asyncio
async def test_grade_empty_errors(deps):
    await ReadAlongStart()(deps, book_id="sel-big-feelings")
    result = await ReadAlongGrade()(deps, correct=[], incorrect=[])
    assert "error" in result


# --- read_along_finish ---


@pytest.mark.asyncio
async def test_finish_awards_stars(deps):
    await ReadAlongStart()(deps, book_id="sel-big-feelings")
    result = await ReadAlongFinish()(deps, stars=4)
    assert result["status"] == "finished"
    assert result["stars"] == 4
    assert result["wrapup"]


@pytest.mark.asyncio
async def test_finish_clamps_stars(deps):
    await ReadAlongStart()(deps, book_id="sel-big-feelings")
    result = await ReadAlongFinish()(deps, stars=99)
    assert result["stars"] == 5  # clamped to max


@pytest.mark.asyncio
async def test_finish_requires_session(deps):
    result = await ReadAlongFinish()(deps)
    assert "error" in result


def test_tools_are_registered_names():
    assert ReadAlongStart.name == "read_along_start"
    assert ReadAlongCue.name == "read_along_cue"
    assert ReadAlongGrade.name == "read_along_grade"
    assert ReadAlongNextPage.name == "read_along_next_page"
    assert ReadAlongFinish.name == "read_along_finish"
