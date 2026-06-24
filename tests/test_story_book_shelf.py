"""Tests for the story_book_shelf tool — opens the visual bookshelf, hardware-free."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import reachy_mini_conversation_app.tools.story_book_shelf as sbs
from reachy_mini_conversation_app.story_store import StoryStore
from reachy_mini_conversation_app.tools.story_book_shelf import SHELF_URL, StoryBookShelf


def _library(books, page_counts=None):
    page_counts = page_counts or {}
    lib = MagicMock()
    lib.list_books.return_value = books
    lib.page_count.side_effect = lambda bid: page_counts.get(bid, 0)
    return lib


def _book(book_id, title):
    return SimpleNamespace(id=book_id, title=title)


def _deps(handler=None):
    return SimpleNamespace(realtime_handler=handler)


@pytest.fixture(autouse=True)
def _reset_store():
    StoryStore._instance = None
    yield
    StoryStore._instance = None


@pytest.mark.asyncio
async def test_opens_shelf_returns_book_list_with_page_count(monkeypatch):
    opened = []
    monkeypatch.setattr(sbs.webbrowser, "open", lambda url: opened.append(url) or True)
    monkeypatch.setattr(
        sbs.BookLibrary, "get",
        classmethod(lambda cls: _library(
            [_book("a1", "小熊去冒險"), _book("b2", "彩虹魚")],
            {"a1": 8, "b2": 12},
        )),
    )

    result = await StoryBookShelf()(_deps())

    assert opened == [SHELF_URL]
    assert result["status"] == "ok"
    assert result["shelf_opened"] is True
    assert result["book_count"] == 2
    assert result["books"] == [
        {"id": "a1", "title": "小熊去冒險", "page_count": 8},
        {"id": "b2", "title": "彩虹魚", "page_count": 12},
    ]
    assert "點封面" in result["message"]


@pytest.mark.asyncio
async def test_binds_handler_for_taps(monkeypatch):
    monkeypatch.setattr(sbs.webbrowser, "open", lambda url: True)
    monkeypatch.setattr(sbs.BookLibrary, "get", classmethod(lambda cls: _library([])))

    handler = object()
    await StoryBookShelf()(_deps(handler))

    store = StoryStore.get()
    assert store.handler is handler
    assert store.loop is not None  # the running loop was captured


@pytest.mark.asyncio
async def test_empty_shelf_suggests_creating(monkeypatch):
    monkeypatch.setattr(sbs.webbrowser, "open", lambda url: True)
    monkeypatch.setattr(sbs.BookLibrary, "get", classmethod(lambda cls: _library([])))

    result = await StoryBookShelf()(_deps())

    assert result["status"] == "empty"
    assert result["book_count"] == 0
    assert "books" not in result
    assert "做一本" in result["message"]


@pytest.mark.asyncio
async def test_headless_open_false_recites_titles(monkeypatch):
    """When no browser can show the shelf, the message recites titles (no 'opened' fib)."""
    monkeypatch.setattr(sbs.webbrowser, "open", lambda url: False)  # headless: returns False
    monkeypatch.setattr(
        sbs.BookLibrary, "get",
        classmethod(lambda cls: _library([_book("a1", "小熊去冒險")], {"a1": 5})),
    )

    result = await StoryBookShelf()(_deps())

    assert result["status"] == "ok"
    assert result["shelf_opened"] is False
    assert "小熊去冒險" in result["message"]
    assert "打開囉" not in result["message"]  # must not claim the screen opened


@pytest.mark.asyncio
async def test_browser_failure_does_not_raise(monkeypatch):
    def boom(url):
        raise RuntimeError("no display")

    monkeypatch.setattr(sbs.webbrowser, "open", boom)
    monkeypatch.setattr(
        sbs.BookLibrary, "get",
        classmethod(lambda cls: _library([_book("a1", "書一")], {"a1": 3})),
    )

    result = await StoryBookShelf()(_deps())  # must not raise
    assert result["status"] == "ok"
    assert result["shelf_opened"] is False
    assert result["book_count"] == 1


def test_is_available_gates_on_gemini(monkeypatch):
    from reachy_mini_conversation_app.config import config as cfg

    monkeypatch.setattr(cfg, "GEMINI_AVAILABLE", True)
    assert StoryBookShelf().is_available() is True
    monkeypatch.setattr(cfg, "GEMINI_AVAILABLE", False)
    assert StoryBookShelf().is_available() is False


def test_takes_no_parameters():
    schema = StoryBookShelf.parameters_schema
    assert schema["properties"] == {}
    assert schema["required"] == []


def test_name_matches_module_filename():
    # loader requires Tool.name == module filename == tools.txt entry
    assert StoryBookShelf.name == "story_book_shelf"
    assert sbs.__name__.endswith(".story_book_shelf")
