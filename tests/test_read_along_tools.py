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
from reachy_mini_conversation_app.tools.read_along_start import ReadAlongStart  # noqa: E402
from reachy_mini_conversation_app.tools.read_along_finish import ReadAlongFinish  # noqa: E402
from reachy_mini_conversation_app.tools.read_along_next_page import ReadAlongNextPage  # noqa: E402


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
async def test_next_page_advances(deps):
    await ReadAlongStart()(deps, book_id="sel-big-feelings")
    result = await ReadAlongNextPage()(deps)
    assert result["status"] == "ok"
    assert result["page"] == 2
    assert result["words"]


@pytest.mark.asyncio
async def test_next_page_requires_session(deps):
    result = await ReadAlongNextPage()(deps)
    assert "error" in result


@pytest.mark.asyncio
async def test_next_page_on_last_reports_last(deps):
    await ReadAlongStart()(deps, book_id="sel-big-feelings")
    store = ReadAlongStore.get()
    store.go_to_page(store.session.total_pages - 1)
    result = await ReadAlongNextPage()(deps)
    assert result["status"] == "last_page"


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
    assert ReadAlongNextPage.name == "read_along_next_page"
    assert ReadAlongFinish.name == "read_along_finish"
