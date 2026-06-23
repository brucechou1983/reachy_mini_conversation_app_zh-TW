"""Tests for the curated SEL read-along book content (no hardware/network).

These guard the *quality contract* of the hand-authored books: every page has
text, a feelings prompt, an illustration prompt, target words that actually
appear in the page, and a filesystem-safe id.
"""

import pytest

from reachy_mini_conversation_app.read_along_books import (
    catalog,
    get_book,
    tokenize,
    all_books,
    normalize_word,
)


def test_catalog_non_empty_and_unique_ids():
    books = all_books()
    assert len(books) >= 3
    ids = [b.id for b in books]
    assert len(ids) == len(set(ids))


def test_catalog_listing_shape():
    entries = catalog()
    assert entries
    for e in entries:
        assert set(e.keys()) == {"id", "title", "sel_theme", "level", "page_count"}
        assert e["page_count"] >= 1


@pytest.mark.parametrize("book", all_books(), ids=lambda b: b.id)
def test_book_id_is_filesystem_safe(book):
    assert "/" not in book.id and "\\" not in book.id and ".." not in book.id
    assert book.id.strip() == book.id and book.id


@pytest.mark.parametrize("book", all_books(), ids=lambda b: b.id)
def test_every_page_is_well_formed(book):
    assert book.page_count >= 1
    assert book.title and book.sel_theme and book.wrapup
    assert book.warmup, "each book pre-teaches warm-up words"
    for page in book.pages:
        assert page.text.strip(), "page has reading text"
        assert page.sel_prompt.strip(), "page has an SEL/comprehension prompt"
        assert page.illustration.strip(), "page has an illustration prompt"
        assert "no text" in page.illustration.lower(), "illustrations must not contain text"
        assert page.tricky, "page declares target words"


@pytest.mark.parametrize("book", all_books(), ids=lambda b: b.id)
def test_tricky_words_appear_in_their_page(book):
    """Pedagogical integrity: a page's target words must be in that page's text."""
    for page in book.pages:
        page_tokens = {normalize_word(w) for w in tokenize(page.text)}
        for tw in page.tricky:
            assert normalize_word(tw) in page_tokens, (
                f"{book.id}: tricky word {tw!r} not in page {page.text!r}"
            )


@pytest.mark.parametrize("book", all_books(), ids=lambda b: b.id)
def test_warmup_words_appear_somewhere_in_book(book):
    all_tokens = set()
    for page in book.pages:
        all_tokens |= {normalize_word(w) for w in tokenize(page.text)}
    for w in book.warmup:
        assert normalize_word(w) in all_tokens, f"{book.id}: warm-up {w!r} not used in book"


def test_get_book_known_and_unknown():
    assert get_book("sel-big-feelings") is not None
    assert get_book("does-not-exist") is None


# --- tokenizer ---


def test_tokenize_basic():
    assert tokenize("I feel happy.") == ["I", "feel", "happy"]


def test_tokenize_keeps_apostrophe():
    assert tokenize("I don't cry.") == ["I", "don't", "cry"]


def test_tokenize_empty():
    assert tokenize("") == []
    assert tokenize("   ") == []


def test_normalize_word():
    assert normalize_word("Happy!") == "happy"
    assert normalize_word("TODAY.") == "today"
    assert normalize_word("happy") == "happy"
    assert normalize_word(",") == ","
