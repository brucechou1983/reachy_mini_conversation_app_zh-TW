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


# ------------------------------------------------------------------
# kind separation (storybook vs read-along share one library)
# ------------------------------------------------------------------


def _book(book_id: str, title: str) -> Story:
    return Story(id=book_id, title=title, pages=[StoryPage(text="p")], status="ready")


class TestKindSeparation:
    def test_list_filters_by_kind(self, lib: BookLibrary):
        from reachy_mini_conversation_app.book_library import KIND_STORY, KIND_READ_ALONG

        lib.save_book(_book("uuid-1", "我的故事"), kind=KIND_STORY)
        lib.save_book(_book("sel-feelings", "Big Feelings"), kind=KIND_READ_ALONG)

        story_ids = [b.id for b in lib.list_books(kind=KIND_STORY)]
        ra_ids = [b.id for b in lib.list_books(kind=KIND_READ_ALONG)]
        assert story_ids == ["uuid-1"]
        assert ra_ids == ["sel-feelings"]
        assert len(lib.list_books()) == 2          # no filter → both

    def test_get_book_respects_kind(self, lib: BookLibrary):
        from reachy_mini_conversation_app.book_library import KIND_STORY, KIND_READ_ALONG

        lib.save_book(_book("sel-x", "English"), kind=KIND_READ_ALONG)
        assert lib.get_book("sel-x", kind=KIND_READ_ALONG) is not None
        assert lib.get_book("sel-x", kind=KIND_STORY) is None   # wrong kind → not found
        assert lib.get_book("sel-x") is not None                # no kind → found

    def test_delete_respects_kind(self, lib: BookLibrary):
        from reachy_mini_conversation_app.book_library import KIND_STORY, KIND_READ_ALONG

        lib.save_book(_book("sel-x", "English"), kind=KIND_READ_ALONG)
        # story-shelf delete must not remove a read-along book
        assert lib.delete_book("sel-x", kind=KIND_STORY) is False
        assert lib.get_book("sel-x") is not None
        # correct kind deletes it
        assert lib.delete_book("sel-x", kind=KIND_READ_ALONG) is True
        assert lib.get_book("sel-x") is None

    def test_save_is_upsert_no_duplicate_rows(self, lib: BookLibrary):
        from reachy_mini_conversation_app.book_library import KIND_STORY

        lib.save_book(_book("uuid-1", "v1"), kind=KIND_STORY)
        lib.save_book(_book("uuid-1", "v2"), kind=KIND_STORY)   # same id again
        books = lib.list_books()
        assert len(books) == 1
        assert books[0].title == "v2"                            # updated, not duplicated

    def test_legacy_csv_without_kind_is_migrated(self, lib: BookLibrary):
        from reachy_mini_conversation_app.book_library import KIND_STORY, KIND_READ_ALONG

        # Simulate an old CSV with no 'kind' column (pre-migration on-device file).
        lib._csv_path.write_text(
            "id,title,created_date,last_read_date\n"
            "uuid-old,舊故事,2020-01-01,2020-01-01\n"
            "sel-big-feelings,Big Feelings,2020-01-02,2020-01-02\n",
            encoding="utf-8",
        )
        # kind derived from id prefix: sel-* → read_along, else story
        assert [b.id for b in lib.list_books(kind=KIND_STORY)] == ["uuid-old"]
        assert [b.id for b in lib.list_books(kind=KIND_READ_ALONG)] == ["sel-big-feelings"]
