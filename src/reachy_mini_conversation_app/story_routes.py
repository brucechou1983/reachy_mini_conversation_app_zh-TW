"""FastAPI routes for the story bookshelf and reader."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import zipfile
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse, Response

from .book_library import BookLibrary
from .story_store import StoryStore

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


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

    @app.delete("/reader/api/books/{book_id}")
    def _delete_book(book_id: str) -> JSONResponse:
        library = BookLibrary.get()
        if not library.delete_book(book_id):
            raise HTTPException(status_code=404, detail="book not found")
        return JSONResponse({"ok": True})

    @app.get("/reader/api/books/{book_id}/download")
    def _download_book(book_id: str) -> StreamingResponse:
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
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # ------------------------------------------------------------------ #
    # Per-book page API (used by the book reader)
    # ------------------------------------------------------------------ #

    @app.get("/reader/api/books/{book_id}")
    def _get_book_meta(book_id: str) -> JSONResponse:
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
        library = BookLibrary.get()
        img_path = library.page_image_path(book_id, page)
        if img_path is None:
            raise HTTPException(status_code=404, detail="image not found")
        mime = "image/jpeg" if img_path.suffix in (".jpg", ".jpeg") else "image/png"
        return Response(content=img_path.read_bytes(), media_type=mime)

    @app.post("/reader/api/books/{book_id}/last_read")
    def _update_last_read(book_id: str) -> JSONResponse:
        library = BookLibrary.get()
        library.update_last_read(book_id)
        return JSONResponse({"ok": True})

    # ------------------------------------------------------------------ #
    # Book reader HTML (standalone with prev/next + SSE for live reading)
    # ------------------------------------------------------------------ #

    @app.get("/reader/books/{book_id}")
    def _book_reader_page(book_id: str) -> FileResponse:
        return FileResponse(str(STATIC_DIR / "book_reader.html"))

    # ------------------------------------------------------------------ #
    # Live SSE stream + story snapshot (used by book reader for live mode)
    # ------------------------------------------------------------------ #

    @app.get("/reader/events")
    async def _reader_events() -> StreamingResponse:
        store = StoryStore.get()
        q = store.subscribe()

        async def event_stream():  # type: ignore[return]
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
    def _reader_story() -> dict | JSONResponse:
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
