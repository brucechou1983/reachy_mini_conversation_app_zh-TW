"""FastAPI routes for the story reader."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse

from .story_store import StoryStore


logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


def mount_story_routes(app: FastAPI) -> None:
    """Register story reader routes on the settings FastAPI app."""

    @app.get("/reader")
    def _reader_page() -> FileResponse:
        return FileResponse(str(STATIC_DIR / "reader.html"))

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
