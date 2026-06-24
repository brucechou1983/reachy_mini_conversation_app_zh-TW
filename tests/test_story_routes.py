"""Tests for the story bookshelf select route + browser-tap -> robot bridge."""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reachy_mini_conversation_app.config import config
from reachy_mini_conversation_app.story_store import Story, StoryPage, StoryStore
from reachy_mini_conversation_app.book_library import BookLibrary
from reachy_mini_conversation_app.story_routes import mount_story_routes, _inject_story_select


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STORY_BOOKS_DIR", str(tmp_path / "books"), raising=False)
    BookLibrary._instance = None
    StoryStore._instance = None
    app = FastAPI()
    mount_story_routes(app)
    yield TestClient(app)
    BookLibrary._instance = None
    StoryStore._instance = None


def _save_book(book_id="bk1", title="小熊去冒險"):
    story = Story(id=book_id, title=title, pages=[StoryPage(text="頁一")], status="ready")
    BookLibrary.get().save_book(story)
    return story


# --- select route ---


def test_select_unknown_book_404(client):
    assert client.post("/reader/api/books/nope/select").status_code == 404


def test_select_bad_id_rejected(client):
    assert client.post("/reader/api/books/..%2Fevil/select").status_code in (400, 404)


def test_select_known_book_returns_reader_url(client):
    _save_book("bk1", "小熊去冒險")
    resp = client.post("/reader/api/books/bk1/select")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["book_id"] == "bk1"
    assert data["reader_url"] == "/reader/books/bk1"


def test_select_without_bound_handler_is_safe(client):
    """No robot bound (e.g. shelf opened manually): select still succeeds, no crash."""
    _save_book("bk1")
    assert StoryStore.get().handler is None
    assert client.post("/reader/api/books/bk1/select").status_code == 200


# --- tap -> robot injection bridge ---


@pytest.mark.asyncio
async def test_select_injects_open_instruction_to_handler():
    StoryStore._instance = None
    store = StoryStore.get()
    captured = {}

    class FakeHandler:
        async def inject_user_text(self, text, respond=True):
            captured["text"] = text

    store.bind_handler(FakeHandler(), asyncio.get_running_loop())
    _inject_story_select(store, "bk1", "小熊去冒險")
    await asyncio.sleep(0.05)  # let the scheduled coroutine run
    assert "bk1" in captured["text"]
    assert "story_book_open" in captured["text"]
    assert "小熊去冒險" in captured["text"]
    StoryStore._instance = None


def test_inject_no_handler_is_safe():
    StoryStore._instance = None
    store = StoryStore.get()
    store.bind_handler(None, None)
    _inject_story_select(store, "bk1", "x")  # must not raise
    StoryStore._instance = None


def test_bind_handler_roundtrip():
    StoryStore._instance = None
    store = StoryStore.get()
    h = object()
    store.bind_handler(h, None)
    assert store.handler is h
    assert store.loop is None
    StoryStore._instance = None
