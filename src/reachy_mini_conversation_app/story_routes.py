"""FastAPI routes for the story bookshelf and reader."""

from __future__ import annotations
import io
import json
import asyncio
import logging
import zipfile
from typing import Any, AsyncIterator
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.responses import Response, FileResponse, JSONResponse, StreamingResponse

from .story_store import StoryStore
from .book_library import BookLibrary, _validate_book_id
from .read_along_store import STATE_SOUND_OUT, ReadAlongStore


logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


class TapPayload(BaseModel):
    """Body for a read-along word tap: the tapped word's index on the page."""

    index: int


class SelectPayload(BaseModel):
    """Body for a bookshelf selection: the chosen book's id."""

    book_id: str


def mount_story_routes(app: FastAPI) -> None:
    """Register story bookshelf and reader routes."""
    # ------------------------------------------------------------------ #
    # Bookshelf (landing page at /reader)
    # ------------------------------------------------------------------ #

    @app.get("/reader")
    def _bookshelf_page() -> FileResponse:
        return FileResponse(str(STATIC_DIR / "reader.html"))

    @app.get("/reader/api/books")
    def _list_books() -> JSONResponse:
        library = BookLibrary.get()
        books = library.list_books()
        result = []
        for meta in books:
            count = library.page_count(meta.id)
            img_path = library.page_image_path(meta.id, 0)
            result.append({
                "id": meta.id,
                "title": meta.title,
                "created_date": meta.created_date,
                "last_read_date": meta.last_read_date,
                "page_count": count,
                "cover_url": f"/reader/api/books/{meta.id}/pages/0/image" if img_path else None,
            })
        return JSONResponse(result)

    def _check_book_id(book_id: str) -> None:
        try:
            _validate_book_id(book_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid book id")

    @app.delete("/reader/api/books/{book_id}")
    def _delete_book(book_id: str) -> JSONResponse:
        _check_book_id(book_id)
        library = BookLibrary.get()
        if not library.delete_book(book_id):
            raise HTTPException(status_code=404, detail="book not found")
        return JSONResponse({"ok": True})

    @app.get("/reader/api/books/{book_id}/download")
    def _download_book(book_id: str) -> StreamingResponse:
        _check_book_id(book_id)
        library = BookLibrary.get()
        meta = library.get_book(book_id)
        if meta is None:
            raise HTTPException(status_code=404, detail="book not found")
        book_dir = library.book_dir(book_id)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(book_dir.iterdir()):
                if f.is_file():
                    zf.write(f, f.name)
        buf.seek(0)

        safe_title = "".join(c for c in meta.title if c.isalnum() or c in " _-")[:40]
        filename = f"{safe_title or book_id}.zip"
        # Use RFC 5987 encoding for non-ASCII filenames
        ascii_fallback = f"{book_id}.zip"
        from urllib.parse import quote
        encoded_filename = quote(filename)
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{ascii_fallback}"; '
                    f"filename*=UTF-8''{encoded_filename}"
                ),
            },
        )

    # ------------------------------------------------------------------ #
    # Per-book page API (used by the book reader)
    # ------------------------------------------------------------------ #

    @app.get("/reader/api/books/{book_id}")
    def _get_book_meta(book_id: str) -> JSONResponse:
        _check_book_id(book_id)
        library = BookLibrary.get()
        meta = library.get_book(book_id)
        if meta is None:
            raise HTTPException(status_code=404, detail="book not found")
        return JSONResponse({
            "id": meta.id,
            "title": meta.title,
            "created_date": meta.created_date,
            "last_read_date": meta.last_read_date,
            "page_count": library.page_count(book_id),
        })

    @app.get("/reader/api/books/{book_id}/pages/{page}")
    def _get_page(book_id: str, page: int) -> JSONResponse:
        _check_book_id(book_id)
        library = BookLibrary.get()
        if library.get_book(book_id) is None:
            raise HTTPException(status_code=404, detail="book not found")
        total = library.page_count(book_id)
        if page < 0 or page >= total:
            raise HTTPException(status_code=404, detail="page not found")
        text = library.page_text(book_id, page)
        img_path = library.page_image_path(book_id, page)
        return JSONResponse({
            "page": page,
            "total": total,
            "text": text,
            "image_url": f"/reader/api/books/{book_id}/pages/{page}/image" if img_path else None,
        })

    @app.get("/reader/api/books/{book_id}/pages/{page}/image")
    def _get_page_image(book_id: str, page: int) -> Response:
        _check_book_id(book_id)
        library = BookLibrary.get()
        img_path = library.page_image_path(book_id, page)
        if img_path is None:
            raise HTTPException(status_code=404, detail="image not found")
        mime = "image/jpeg" if img_path.suffix in (".jpg", ".jpeg") else "image/png"
        return Response(content=img_path.read_bytes(), media_type=mime)

    @app.post("/reader/api/books/{book_id}/last_read")
    def _update_last_read(book_id: str) -> JSONResponse:
        _check_book_id(book_id)
        library = BookLibrary.get()
        library.update_last_read(book_id)
        return JSONResponse({"ok": True})

    # ------------------------------------------------------------------ #
    # Book reader HTML (standalone with prev/next + SSE for live reading)
    # ------------------------------------------------------------------ #

    @app.get("/reader/books/{book_id}")
    def _book_reader_page(book_id: str) -> FileResponse:
        _check_book_id(book_id)
        return FileResponse(str(STATIC_DIR / "book_reader.html"))

    # ------------------------------------------------------------------ #
    # Live SSE stream + story snapshot (used by book reader for live mode)
    # ------------------------------------------------------------------ #

    @app.get("/reader/events")
    async def _reader_events() -> StreamingResponse:
        store = StoryStore.get()
        q = store.subscribe()

        async def event_stream() -> AsyncIterator[str]:
            try:
                # Send current state on connect
                story = store.story
                if story and story.status == "reading" and story.pages:
                    sp = story.pages[story.current_page]
                    yield f"data: {json.dumps({'event': 'page_change', 'page': story.current_page, 'total': len(story.pages), 'text': sp.text, 'image_b64': sp.image_b64})}\n\n"
                elif story and story.status == "ready":
                    yield f"data: {json.dumps({'event': 'story_ready', 'story_id': story.id, 'title': story.title, 'page_count': len(story.pages)})}\n\n"
                elif story and story.status == "generating":
                    yield f"data: {json.dumps({'event': 'generating', 'title': story.title})}\n\n"

                while True:
                    try:
                        data = await asyncio.wait_for(q.get(), timeout=30)
                        yield f"data: {json.dumps(data)}\n\n"
                    except asyncio.TimeoutError:
                        # Keep-alive heartbeat
                        yield f"data: {json.dumps({'event': 'heartbeat'})}\n\n"
            except asyncio.CancelledError:
                pass
            finally:
                store.unsubscribe(q)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.get("/reader/story", response_model=None)
    def _reader_story() -> dict[str, Any] | JSONResponse:
        store = StoryStore.get()
        story = store.story
        if not story:
            return JSONResponse({"error": "no_story"}, status_code=404)
        pages = [{"text": p.text, "image_b64": p.image_b64, "image_mime": p.image_mime} for p in story.pages]
        return {
            "id": story.id,
            "title": story.title,
            "status": story.status,
            "current_page": story.current_page,
            "pages": pages,
        }

    # ------------------------------------------------------------------ #
    # Read-along (Ello-style SEL picture books): child reads, robot coaches
    # ------------------------------------------------------------------ #
    # NOTE: declare the specific paths before the /{book_id} catch-all so
    # "events"/"state"/"tap" are not swallowed as book ids.

    @app.get("/reader/read-along/events")
    async def _read_along_events() -> StreamingResponse:
        return StreamingResponse(
            read_along_event_stream(ReadAlongStore.get()),
            media_type="text/event-stream",
        )

    @app.get("/reader/read-along/state")
    def _read_along_state() -> JSONResponse:
        store = ReadAlongStore.get()
        snap = store.snapshot()
        if snap is None:
            return JSONResponse({"error": "no_session"}, status_code=404)
        library = BookLibrary.get()
        book_id = str(snap["book_id"])
        page = int(snap["page"])
        has_img = library.page_image_path(book_id, page) is not None
        snap["image_url"] = (
            f"/reader/api/books/{book_id}/pages/{page}/image" if has_img else None
        )
        return JSONResponse(snap)

    @app.post("/reader/read-along/tap")
    async def _read_along_tap(payload: TapPayload) -> JSONResponse:
        store = ReadAlongStore.get()
        session = store.session
        if session is None:
            return JSONResponse({"error": "no_session"}, status_code=404)
        words = session.current_words
        if payload.index < 0 or payload.index >= len(words):
            return JSONResponse({"error": "bad_index"}, status_code=400)
        word = words[payload.index]
        # Immediate UI feedback regardless of whether the robot is reachable.
        store.cue(payload.index, STATE_SOUND_OUT)
        _inject_tap(store, word)
        return JSONResponse({"ok": True, "index": payload.index, "word": word})

    # Visual bookshelf: kids see the curated SEL books and pick one.
    @app.get("/reader/read-along")
    def _read_along_shelf() -> FileResponse:
        return FileResponse(str(STATIC_DIR / "read_along_shelf.html"))

    @app.get("/reader/api/read-along/books")
    def _read_along_book_list() -> JSONResponse:
        from .read_along_books import catalog
        from .read_along_progress import ReadAlongProgress

        library = BookLibrary.get()
        progress = ReadAlongProgress.get()
        result = []
        for b in catalog():
            book_id = str(b["id"])
            has_cover = library.page_image_path(book_id, 0) is not None
            rec = progress.get_book(book_id) or {}
            result.append({
                **b,
                "cover_url": f"/reader/api/books/{book_id}/pages/0/image" if has_cover else None,
                "completed": bool(rec.get("completed")),
                "stars": int(rec.get("stars", 0)),
            })
        return JSONResponse(result)

    @app.post("/reader/api/read-along/select")
    async def _read_along_select(payload: SelectPayload) -> JSONResponse:
        from .read_along_books import get_book

        book = get_book(payload.book_id)
        if book is None:
            return JSONResponse({"error": "unknown_book"}, status_code=404)
        # Best-effort: nudge the robot to begin coaching this book.
        _inject_select(ReadAlongStore.get(), book.id, book.title)
        return JSONResponse({
            "ok": True,
            "book_id": book.id,
            "reader_url": f"/reader/read-along/{book.id}",
        })

    @app.get("/reader/read-along/{book_id}")
    def _read_along_page(book_id: str) -> FileResponse:
        _check_book_id(book_id)
        return FileResponse(str(STATIC_DIR / "read_along.html"))


async def read_along_event_stream(store: ReadAlongStore) -> AsyncIterator[str]:
    """Yield SSE payloads for the read-along reader: snapshot, then live events."""
    q = store.subscribe()
    try:
        snap = store.snapshot()
        if snap is not None:
            yield f"data: {json.dumps(snap)}\n\n"
        while True:
            try:
                data = await asyncio.wait_for(q.get(), timeout=30)
                yield f"data: {json.dumps(data)}\n\n"
            except asyncio.TimeoutError:
                yield f"data: {json.dumps({'event': 'heartbeat'})}\n\n"
    except asyncio.CancelledError:
        pass
    finally:
        store.unsubscribe(q)


def _inject_to_handler(store: ReadAlongStore, text: str) -> None:
    """Best-effort: deliver a user-role message to the bound robot handler.

    Schedules the coroutine on the handler's event loop (which may differ from
    the request loop), so a browser action (tap / book selection) can reach the
    live realtime session.
    """
    handler = store.handler
    if handler is None or not hasattr(handler, "inject_user_text"):
        return
    coro = handler.inject_user_text(text)
    loop = store.loop
    try:
        running: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    try:
        if loop is not None and loop is not running:
            asyncio.run_coroutine_threadsafe(coro, loop)
        else:
            asyncio.ensure_future(coro)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("read-along handler injection failed: %s", e)
        coro.close()


def _inject_tap(store: ReadAlongStore, word: str) -> None:
    """Best-effort: ask the bound robot handler to sound out a tapped word."""
    _inject_to_handler(
        store,
        f"[小朋友在繪本上點了單字「{word}」，請溫柔地幫他把這個字一個音一個音拆音念出來，"
        "再把整個字清楚念一次示範。]",
    )


def _inject_select(store: ReadAlongStore, book_id: str, title: str) -> None:
    """Best-effort: tell the robot the child picked a book on the shelf."""
    _inject_to_handler(
        store,
        f"[孩子在書架上選了繪本《{title}》(book_id={book_id})。"
        f'請馬上呼叫 read_along_start(book_id="{book_id}") 開始帶讀。]',
    )
