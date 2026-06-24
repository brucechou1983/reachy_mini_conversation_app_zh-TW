"""Tests for the JSON-backed read-along progress store (no hardware)."""

import pytest

from reachy_mini_conversation_app.read_along_progress import ReadAlongProgress


@pytest.fixture
def progress(tmp_path):
    return ReadAlongProgress(tmp_path / "read_along_progress.json")


def test_unknown_book_defaults(progress):
    assert progress.get_book("nope") is None
    assert progress.is_completed("nope") is False
    assert progress.stars("nope") == 0
    assert progress.all() == {}


def test_mark_completed(progress):
    rec = progress.mark_completed("sel-big-feelings", stars=3)
    assert rec["completed"] is True
    assert rec["stars"] == 3
    assert rec["times_read"] == 1
    assert "last_read" in rec
    assert progress.is_completed("sel-big-feelings") is True
    assert progress.stars("sel-big-feelings") == 3


def test_keeps_best_stars_and_counts_reads(progress):
    progress.mark_completed("b", stars=2)
    rec = progress.mark_completed("b", stars=5)
    assert rec["stars"] == 5  # best kept
    assert rec["times_read"] == 2
    rec = progress.mark_completed("b", stars=1)
    assert rec["stars"] == 5  # not lowered
    assert rec["times_read"] == 3


def test_persists_across_instances(tmp_path):
    path = tmp_path / "read_along_progress.json"
    ReadAlongProgress(path).mark_completed("b", stars=4)
    # A fresh instance reading the same file sees the record.
    reloaded = ReadAlongProgress(path)
    assert reloaded.is_completed("b") is True
    assert reloaded.stars("b") == 4


def test_corrupt_file_is_tolerated(tmp_path):
    path = tmp_path / "read_along_progress.json"
    path.write_text("{ not json", encoding="utf-8")
    store = ReadAlongProgress(path)
    assert store.all() == {}
    store.mark_completed("b", stars=1)  # still writable
    assert store.is_completed("b") is True


def test_get_resolves_default_path(monkeypatch, tmp_path):
    from reachy_mini_conversation_app.config import config

    monkeypatch.setattr(config, "STORY_BOOKS_DIR", str(tmp_path / "books"), raising=False)
    ReadAlongProgress._instance = None
    store = ReadAlongProgress.get()
    store.mark_completed("b", stars=1)
    # Stored next to the book library (parent of STORY_BOOKS_DIR).
    assert (tmp_path / "read_along_progress.json").exists()
    ReadAlongProgress._instance = None
