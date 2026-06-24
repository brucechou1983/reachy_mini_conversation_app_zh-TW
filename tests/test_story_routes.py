"""Tests for the story bookshelf select route + browser-tap -> robot bridge."""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reachy_mini_conversation_app.config import config
from reachy_mini_conversation_app.story_store import Story, StoryPage, StoryStore
from reachy_mini_conversation_app.book_library import BookLibrary
from reachy_mini_conversation_app.story_routes import mount_story_routes, _inject_story_select
from reachy_mini_conversation_app.activity_state import STORY, ActivityState


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STORY_BOOKS_DIR", str(tmp_path / "books"), raising=False)
    BookLibrary._instance = None
    StoryStore._instance = None
    ActivityState.get().reset()
    app = FastAPI()
    mount_story_routes(app)
    yield TestClient(app)
    BookLibrary._instance = None
    StoryStore._instance = None
    ActivityState.get().reset()


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
    _inject_story_select("bk1", "小熊去冒險")
    await asyncio.sleep(0.05)  # let the scheduled coroutine run
    assert "bk1" in captured["text"]
    assert "story_book_open" in captured["text"]
    assert "小熊去冒險" in captured["text"]
    StoryStore._instance = None


def test_inject_no_handler_is_safe():
    StoryStore._instance = None
    store = StoryStore.get()
    store.bind_handler(None, None)
    _inject_story_select("bk1", "x")  # must not raise
    StoryStore._instance = None


def test_select_refused_during_read_along(client):
    """A storybook cover tap is refused (409) while the read-along activity is current."""
    _save_book("bk1")
    ActivityState.get().activate("read_along")
    assert client.post("/reader/api/books/bk1/select").status_code == 409
    ActivityState.get().reset()


def test_select_not_a_story_book_404(client):
    """The story select route never opens a read-along (sel-*) book."""
    story = Story(id="sel-x", title="english", pages=[StoryPage(text="p")], status="ready")
    from reachy_mini_conversation_app.book_library import KIND_READ_ALONG
    BookLibrary.get().save_book(story, kind=KIND_READ_ALONG)
    assert ActivityState.get().allows(STORY)
    assert client.post("/reader/api/books/sel-x/select").status_code == 404


def test_select_allowed_again_after_read_along_deactivated(client):
    """After read-along ends (deactivate), a story cover tap is no longer 409."""
    _save_book("bk1")
    ActivityState.get().activate("read_along")
    assert client.post("/reader/api/books/bk1/select").status_code == 409  # while active
    ActivityState.get().deactivate("read_along")                          # read-along ended
    assert client.post("/reader/api/books/bk1/select").status_code == 200  # now allowed


def test_page_json_route_is_story_kind_only(client):
    """The story reader's page-data route never serves a read-along book's pages."""
    from reachy_mini_conversation_app.book_library import KIND_READ_ALONG
    ra = Story(id="sel-x", title="english", pages=[StoryPage(text="hello")], status="ready")
    BookLibrary.get().save_book(ra, kind=KIND_READ_ALONG)
    assert client.get("/reader/api/books/sel-x/pages/0").status_code == 404
    # a real story book still works
    _save_book("bk1")
    assert client.get("/reader/api/books/bk1/pages/0").status_code == 200


def test_bind_handler_roundtrip():
    StoryStore._instance = None
    store = StoryStore.get()
    h = object()
    store.bind_handler(h, None)
    assert store.handler is h
    assert store.loop is None
    StoryStore._instance = None
