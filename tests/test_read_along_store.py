"""Tests for the ReadAlongStore state machine (no hardware/network).

Covers the Ello mechanics that live server-side: tiered miss escalation, word
resolution (case/punctuation, success-skipping), page navigation, stars,
finish/close, and SSE broadcast.
"""

import pytest

from reachy_mini_conversation_app.read_along_books import ReadAlongBook, ReadAlongBookPage
from reachy_mini_conversation_app.read_along_store import (
    STATE_BOUNCE,
    STATE_SUCCESS,
    MODE_DECODABLE,
    STATE_HIGHLIGHT,
    STATE_SOUND_OUT,
    ReadAlongStore,
)


def _book(pages_text, *, book_id="t-book", warmup=None):
    return ReadAlongBook(
        id=book_id,
        title="Test Book",
        sel_theme="testing feelings",
        level=1,
        warmup=warmup or ["happy"],
        wrapup="Great job!",
        pages=[ReadAlongBookPage(text=t, tricky=[], sel_prompt="How do you feel?") for t in pages_text],
    )


@pytest.fixture(autouse=True)
def _reset_store():
    ReadAlongStore._instance = None
    yield
    ReadAlongStore._instance = None


def _store_with(pages_text, **kw):
    store = ReadAlongStore.get()
    store.start(_book(pages_text, **kw), MODE_DECODABLE)
    return store


# --- session start / pages ---


def test_start_sets_session_and_tokenizes():
    store = _store_with(["I feel happy.", "I feel sad."])
    s = store.session
    assert s is not None
    assert s.current_page == 0
    assert s.current_words == ["I", "feel", "happy"]
    assert s.total_pages == 2
    assert s.is_last_page is False


def test_go_to_page_clamps():
    store = _store_with(["a a", "b b", "c c"])
    assert store.go_to_page(-5) == 0
    assert store.go_to_page(99) == 2
    assert store.session.is_last_page is True


def test_go_to_page_resets_word_state():
    store = _store_with(["go go", "stop now"])
    store.cue("go", "miss")  # leaves a word_state on page 0
    assert store.session.word_states
    store.go_to_page(1)
    assert store.session.word_states == {}
    assert store.session.miss_counts == {}


def test_next_page_advances_then_reports_last():
    store = _store_with(["one", "two", "three"])
    assert store.next_page() == (1, False)
    assert store.next_page() == (2, True)
    # already last: no further advance
    assert store.next_page() == (2, True)


def test_next_page_no_session_returns_none():
    ReadAlongStore._instance = None
    assert ReadAlongStore.get().next_page() is None


# --- word resolution ---


def test_resolve_by_word_case_and_punct_insensitive():
    store = _store_with(["I feel Happy today"])
    assert store.resolve_index("happy") == 2
    assert store.resolve_index("HAPPY!") == 2
    assert store.resolve_index("today.") == 3


def test_resolve_by_index():
    store = _store_with(["one two three"])
    assert store.resolve_index(1) == 1
    assert store.resolve_index("2") == 2
    assert store.resolve_index(9) is None


def test_resolve_unknown_returns_none():
    store = _store_with(["one two"])
    assert store.resolve_index("zebra") is None


def test_resolve_prefers_unmastered_occurrence():
    store = _store_with(["go go go"])
    assert store.resolve_index("go") == 0
    store.cue(0, STATE_SUCCESS)
    assert store.resolve_index("go") == 1  # skips the mastered one
    store.cue(1, STATE_SUCCESS)
    assert store.resolve_index("go") == 2


# --- tiered miss escalation (the Ello ladder) ---


def test_miss_escalation_ladder():
    store = _store_with(["read this word"])
    r1 = store.cue("word", "miss")
    assert r1["state"] == STATE_BOUNCE and r1["miss"] == 1
    r2 = store.cue("word", "miss")
    assert r2["state"] == STATE_HIGHLIGHT and r2["miss"] == 2
    r3 = store.cue("word", "miss")
    assert r3["state"] == STATE_SOUND_OUT and r3["miss"] == 3
    r4 = store.cue("word", "miss")
    assert r4["state"] == STATE_SOUND_OUT and r4["miss"] == 4


def test_success_clears_miss_and_marks_mastered():
    store = _store_with(["read this word"])
    store.cue("word", "miss")  # idx 2 now has a miss
    res = store.cue("word", "success")
    assert res["state"] == STATE_SUCCESS
    idx = 2  # "word"
    assert idx not in store.session.miss_counts  # miss cleared on mastery
    assert store.session.word_states[idx] == STATE_SUCCESS


def test_direct_state_and_clear():
    store = _store_with(["read this word"])
    store.cue("this", STATE_HIGHLIGHT)
    assert store.session.word_states[1] == STATE_HIGHLIGHT
    store.cue("this", "clear")
    assert 1 not in store.session.word_states


def test_cue_unknown_word_returns_none():
    store = _store_with(["one two"])
    assert store.cue("zebra", "miss") is None


def test_cue_no_session_returns_none():
    ReadAlongStore._instance = None
    assert ReadAlongStore.get().cue("x", "miss") is None


# --- stars / finish / close ---


def test_add_stars():
    store = _store_with(["one"])
    assert store.add_stars(2) == 2
    assert store.add_stars(1) == 3
    assert store.add_stars(-100) == 0  # never negative


def test_finish_sets_status_and_awards():
    store = _store_with(["one"])
    payload = store.finish(stars=4)
    assert payload["stars"] == 4
    assert payload["wrapup"] == "Great job!"
    assert store.session.status == "finished"


def test_close_clears_session():
    store = _store_with(["one"])
    store.close()
    assert store.session is None


def test_snapshot_none_without_session():
    ReadAlongStore._instance = None
    assert ReadAlongStore.get().snapshot() is None


def test_snapshot_shape():
    store = _store_with(["I feel happy"])
    store.cue("happy", STATE_SUCCESS)
    snap = store.snapshot()
    assert snap["event"] == "read_along_page"
    assert snap["words"] == ["I", "feel", "happy"]
    assert snap["status"] == "reading"
    assert snap["word_states"] == {2: STATE_SUCCESS}


# --- SSE fan-out ---


@pytest.mark.asyncio
async def test_broadcast_reaches_subscriber():
    store = ReadAlongStore.get()
    q = store.subscribe()
    store.start(_book(["one two"]), MODE_DECODABLE)  # broadcasts read_along_page
    evt = q.get_nowait()
    assert evt["event"] == "read_along_page"
    store.cue("two", "miss")
    evt2 = q.get_nowait()
    assert evt2["event"] == "word_cue"
    store.unsubscribe(q)


def test_bind_handler():
    store = _store_with(["one"])
    sentinel = object()
    store.bind_handler(sentinel, None)
    assert store.handler is sentinel


# --- page completion gate + grade ---


def test_page_complete_and_remaining():
    store = _store_with(["I feel happy"])
    s = store.session
    assert s.page_complete is False
    assert s.remaining_words() == ["I", "feel", "happy"]
    store.cue("I", STATE_SUCCESS)
    store.cue("feel", STATE_SUCCESS)
    assert s.remaining_words() == ["happy"]
    assert s.page_complete is False
    store.cue("happy", STATE_SUCCESS)
    assert s.page_complete is True
    assert s.remaining_words() == []


def test_grade_marks_misses_and_successes():
    store = _store_with(["I feel happy"])
    res = store.grade(correct=["I", "feel"], incorrect=["happy"])
    assert res["complete"] is False
    assert res["remaining"] == ["happy"]
    # the misread word got a visual cue (escalation), the others are success
    assert store.session.word_states[2] == STATE_BOUNCE
    assert store.session.word_states[0] == STATE_SUCCESS


def test_grade_all_correct_completes():
    store = _store_with(["I feel happy"])
    res = store.grade(correct=["I", "feel", "happy"], incorrect=[])
    assert res["complete"] is True
    assert res["remaining"] == []


def test_grade_no_session_returns_none():
    ReadAlongStore._instance = None
    assert ReadAlongStore.get().grade(["x"], []) is None


def test_page_complete_resets_on_page_change():
    store = _store_with(["one two", "three four"])
    store.grade(["one", "two"], [])
    assert store.session.page_complete is True
    store.go_to_page(1)
    assert store.session.page_complete is False  # fresh page, nothing read yet
