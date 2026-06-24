"""Tests for the read-along FastAPI routes + browser->robot tap bridge.

These avoid hardware: story_routes only needs fastapi/pydantic + the read-along
store, and the realtime handler is a fake.
"""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reachy_mini_conversation_app.config import config
from reachy_mini_conversation_app.book_library import BookLibrary
from reachy_mini_conversation_app.story_routes import (
    _inject_tap,
    mount_story_routes,
    read_along_event_stream,
)
from reachy_mini_conversation_app.read_along_books import ReadAlongBook, ReadAlongBookPage
from reachy_mini_conversation_app.read_along_store import (
    MODE_DECODABLE,
    STATE_SOUND_OUT,
    ReadAlongStore,
)
from reachy_mini_conversation_app.read_along_progress import ReadAlongProgress


def _book():
    return ReadAlongBook(
        id="sel-big-feelings",  # filesystem-safe id used by the page route
        title="Test Book",
        sel_theme="feelings",
        level=1,
        warmup=["happy"],
        wrapup="Great job!",
        pages=[
            ReadAlongBookPage(text="I feel happy", tricky=["happy"], sel_prompt="When?"),
            ReadAlongBookPage(text="I feel calm", tricky=["calm"], sel_prompt="How?"),
        ],
    )


@pytest.fixture
def client(tmp_path, monkeypatch):
    from reachy_mini_conversation_app.activity_state import ActivityState

    monkeypatch.setattr(config, "STORY_BOOKS_DIR", str(tmp_path / "books"), raising=False)
    BookLibrary._instance = None
    ReadAlongStore._instance = None
    ReadAlongProgress._instance = None
    ActivityState.get().reset()
    app = FastAPI()
    mount_story_routes(app)
    yield TestClient(app)
    BookLibrary._instance = None
    ReadAlongStore._instance = None
    ReadAlongProgress._instance = None
    ActivityState.get().reset()


# --- state route ---


def test_state_no_session_404(client):
    assert client.get("/reader/read-along/state").status_code == 404


def test_state_with_session(client):
    ReadAlongStore.get().start(_book(), MODE_DECODABLE)
    resp = client.get("/reader/read-along/state")
    assert resp.status_code == 200
    data = resp.json()
    assert data["event"] == "read_along_page"
    assert data["words"] == ["I", "feel", "happy"]
    assert data["status"] == "reading"
    assert data["image_url"] is None  # no illustration generated in tests


# --- tap route ---


def test_tap_no_session_404(client):
    assert client.post("/reader/read-along/tap", json={"index": 0}).status_code == 404


def test_tap_bad_index_400(client):
    ReadAlongStore.get().start(_book(), MODE_DECODABLE)
    assert client.post("/reader/read-along/tap", json={"index": 99}).status_code == 400


def test_tap_marks_sound_out(client):
    ReadAlongStore.get().start(_book(), MODE_DECODABLE)
    resp = client.post("/reader/read-along/tap", json={"index": 2})
    assert resp.status_code == 200
    assert resp.json()["word"] == "happy"
    # the tapped word is now flagged sound_out for immediate UI feedback
    snap = ReadAlongStore.get().snapshot()
    assert snap["word_states"][2] == STATE_SOUND_OUT


# --- page HTML route ---


def test_read_along_page_serves_html(client):
    resp = client.get("/reader/read-along/sel-big-feelings")
    assert resp.status_code == 200
    assert "read_along.js" in resp.text


def test_read_along_page_rejects_bad_id(client):
    assert client.get("/reader/read-along/..%2Fevil").status_code in (400, 404)


# --- bookshelf ---


def test_shelf_serves_html(client):
    resp = client.get("/reader/read-along")
    assert resp.status_code == 200
    assert "read_along_shelf.js" in resp.text


def test_shelf_books_api_lists_curated_books(client):
    resp = client.get("/reader/api/read-along/books")
    assert resp.status_code == 200
    books = resp.json()
    assert any(b["id"] == "sel-big-feelings" for b in books)
    for b in books:
        assert "completed" in b and "stars" in b and "cover_url" in b


def test_shelf_books_api_reflects_completion(client):
    ReadAlongProgress.get().mark_completed("sel-big-feelings", stars=5)
    books = client.get("/reader/api/read-along/books").json()
    done = next(b for b in books if b["id"] == "sel-big-feelings")
    assert done["completed"] is True
    assert done["stars"] == 5


def test_select_unknown_book_404(client):
    assert client.post("/reader/api/read-along/select", json={"book_id": "nope"}).status_code == 404


def test_select_known_book_returns_reader_url(client):
    resp = client.post("/reader/api/read-along/select", json={"book_id": "sel-big-feelings"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["reader_url"] == "/reader/read-along/sel-big-feelings"


@pytest.mark.asyncio
async def test_select_injects_to_handler():
    ReadAlongStore._instance = None
    store = ReadAlongStore.get()
    captured = {}

    class FakeHandler:
        async def inject_user_text(self, text, respond=True):
            captured["text"] = text

    store.bind_handler(FakeHandler(), asyncio.get_running_loop())
    from reachy_mini_conversation_app.story_routes import _inject_select

    _inject_select(store, "sel-big-feelings", "My Big Feelings")
    await asyncio.sleep(0.05)
    assert "sel-big-feelings" in captured["text"]
    assert "read_along_start" in captured["text"]
    ReadAlongStore._instance = None


# --- SSE generator emits the snapshot on connect, then live events ---
# Drive the generator directly (no HTTP layer) so the endless stream can't hang
# the test harness.


@pytest.mark.asyncio
async def test_sse_emits_snapshot_then_live_events():
    ReadAlongStore._instance = None
    store = ReadAlongStore.get()
    store.start(_book(), MODE_DECODABLE)

    gen = read_along_event_stream(store)
    try:
        first = await asyncio.wait_for(gen.__anext__(), timeout=2)
        assert first.startswith("data:")
        assert "read_along_page" in first
        # a live cue is delivered to the subscriber
        store.cue("happy", "success")
        nxt = await asyncio.wait_for(gen.__anext__(), timeout=2)
        assert "word_cue" in nxt
    finally:
        await gen.aclose()
    # subscriber is cleaned up on close
    assert store._subscribers == []
    ReadAlongStore._instance = None


# --- tap -> robot injection bridge ---


@pytest.mark.asyncio
async def test_inject_tap_calls_handler():
    ReadAlongStore._instance = None
    store = ReadAlongStore.get()
    store.start(_book(), MODE_DECODABLE)

    captured = {}

    class FakeHandler:
        async def inject_user_text(self, text, respond=True):
            captured["text"] = text

    store.bind_handler(FakeHandler(), asyncio.get_running_loop())
    _inject_tap(store, "happy")
    await asyncio.sleep(0.05)  # let the scheduled task run
    assert "happy" in captured["text"]
    ReadAlongStore._instance = None


def test_inject_tap_no_handler_is_safe():
    ReadAlongStore._instance = None
    store = ReadAlongStore.get()
    store.start(_book(), MODE_DECODABLE)
    store.bind_handler(None, None)
    _inject_tap(store, "happy")  # must not raise
    ReadAlongStore._instance = None
