"""Import curated read-along books into the on-disk library and illustrate them.

The book *text* is curated and hand-authored (see :mod:`read_along_books`); only
the *illustrations* are machine-generated, reusing the same Gemini image pipeline
as the storybook creator and caching the results on disk via
:class:`BookLibrary`.  Generation is best-effort and runs in the background:
the reader shows text immediately and pictures appear as they are cached.  If no
Gemini backend is configured, books remain text-only.
"""

from __future__ import annotations
import base64
import asyncio
import logging
from typing import Any

from reachy_mini_conversation_app.config import config
from reachy_mini_conversation_app.story_store import Story, StoryPage
from reachy_mini_conversation_app.book_library import BookLibrary
from reachy_mini_conversation_app.read_along_books import ReadAlongBook


logger = logging.getLogger(__name__)


def import_book_text(book: ReadAlongBook) -> bool:
    """Ensure the curated book's text exists in the library. Idempotent.

    Returns True if the book was freshly imported, False if it already existed.
    """
    library = BookLibrary.get()
    if library.get_book(book.id) is not None:
        return False
    story = Story(
        id=book.id,
        title=book.title,
        pages=[StoryPage(text=p.text) for p in book.pages],
        status="ready",
    )
    library.save_book(story)
    logger.info("Imported curated read-along book '%s' (text only)", book.id)
    return True


def _missing_illustrations(book: ReadAlongBook) -> list[int]:
    library = BookLibrary.get()
    return [i for i in range(book.page_count) if library.page_image_path(book.id, i) is None]


async def generate_illustrations(book: ReadAlongBook) -> int:
    """Generate and cache any missing page illustrations. Returns count generated."""
    if not config.GEMINI_AVAILABLE:
        return 0
    # Imported lazily to avoid pulling the Gemini SDK at module import time.
    from reachy_mini_conversation_app.tools.story_book_create import _generate_illustration

    library = BookLibrary.get()
    book_dir = library.book_dir(book.id)
    theme = f"{book.title} — a gentle SEL picture book about {book.sel_theme}"
    generated = 0
    for i in _missing_illustrations(book):
        page = book.pages[i]
        try:
            image_b64, mime = await _generate_illustration(theme, page.illustration, i + 1, book.page_count)
        except Exception as e:  # never let illustration failures break reading
            logger.warning("Illustration gen failed for %s page %d: %s", book.id, i, e)
            continue
        if not image_b64:
            continue
        ext = "jpg" if "jpeg" in mime else "png"
        (book_dir / f"page_{i}.{ext}").write_bytes(base64.b64decode(image_b64))
        generated += 1
    if generated:
        logger.info("Generated %d illustration(s) for '%s'", generated, book.id)
    return generated


def ensure_book_assets(book: ReadAlongBook, generate: bool = True) -> dict[str, Any]:
    """Import text now and kick off background illustration generation.

    Returns a small status dict (``imported``, ``illustrating``).
    """
    imported = import_book_text(book)
    illustrating = False
    if generate and config.GEMINI_AVAILABLE and _missing_illustrations(book):
        try:
            task = asyncio.create_task(generate_illustrations(book))
            task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
            illustrating = True
        except RuntimeError:
            # No running event loop (e.g. called from sync context/tests): skip.
            illustrating = False
    return {"imported": imported, "illustrating": illustrating}
