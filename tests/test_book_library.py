"""Tests for the persistent story book library (hardware-free)."""

import base64
from pathlib import Path

import pytest

from reachy_mini_conversation_app.story_store import Story, StoryPage
from reachy_mini_conversation_app.book_library import BookLibrary, _validate_book_id


# ------------------------------------------------------------------
# _validate_book_id — path-traversal guard (security relevant)
# ------------------------------------------------------------------


class TestValidateBookId:
    @pytest.mark.parametrize("bad", ["", "..", "../etc", "a/b", "a\\b", "a\0b"])
    def test_rejects_unsafe_ids(self, bad):
        with pytest.raises(ValueError):
            _validate_book_id(bad)

    @pytest.mark.parametrize("good", ["story1", "abc-123", "故事_001"])
    def test_accepts_safe_ids(self, good):
        assert _validate_book_id(good) == good


# ------------------------------------------------------------------
# save / list / get / page / delete round trip
# ------------------------------------------------------------------


@pytest.fixture()
def lib(tmp_path: Path) -> BookLibrary:
    return BookLibrary(tmp_path / "books")


def _story() -> Story:
    png = base64.b64encode(b"fake-png-bytes").decode("ascii")
    return Story(
        id="story1",
        title="小恐龍歷險記",
        pages=[
            StoryPage(text="第一頁", image_b64=png, image_mime="image/png"),
            StoryPage(text="第二頁", image_b64="", image_mime="image/png"),
        ],
    )


class TestRoundTrip:
    def test_save_then_read_back(self, lib: BookLibrary):
        lib.save_book(_story())

        # metadata
        books = lib.list_books()
        assert len(books) == 1
        assert books[0].id == "story1"
        assert books[0].title == "小恐龍歷險記"
        assert lib.get_book("story1") is not None

        # pages: 2 text files, 1 image (page 0 only)
        assert lib.page_count("story1") == 2
        assert lib.page_text("story1", 0) == "第一頁"
        assert lib.page_text("story1", 1) == "第二頁"
        assert lib.page_image_path("story1", 0) is not None
        assert lib.page_image_path("story1", 1) is None

    def test_get_missing_returns_none(self, lib: BookLibrary):
        assert lib.get_book("nope") is None
        assert lib.page_count("nope") == 0
        assert lib.page_text("nope", 0) == ""

    def test_delete(self, lib: BookLibrary):
        lib.save_book(_story())
        assert lib.delete_book("story1") is True
        assert lib.get_book("story1") is None
        assert not (lib.books_dir / "story1").exists()
        # deleting again is a no-op
        assert lib.delete_book("story1") is False

    def test_update_last_read(self, lib: BookLibrary):
        lib.save_book(_story())
        before = lib.get_book("story1").last_read_date
        lib.update_last_read("story1")
        after = lib.get_book("story1").last_read_date
        assert after >= before

    def test_unsafe_id_blocks_disk_access(self, lib: BookLibrary):
        with pytest.raises(ValueError):
            lib.page_count("../escape")
