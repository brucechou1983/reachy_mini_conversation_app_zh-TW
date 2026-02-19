"""Tool: story_book_create - Asynchronously generate a multi-page story book via Gemini."""

from __future__ import annotations

import asyncio
import json
import logging
import webbrowser
from typing import Any, Dict

import httpx

from reachy_mini_conversation_app.config import config
from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies
from reachy_mini_conversation_app.story_store import StoryStore, StoryPage


logger = logging.getLogger(__name__)

GEMINI_TEXT_MODEL = "gemini-2.5-flash"
GEMINI_IMAGE_MODEL = "gemini-2.5-flash-image"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
NUM_PAGES = 8


class StoryBookCreate(Tool):
    """Asynchronously create a multi-page illustrated story book."""

    name = "story_book_create"
    description = (
        "開始非同步產生一本多頁插畫故事書。呼叫後立即返回，故事會在背景產生。"
        "當故事準備好時會自動通知你。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "theme": {
                "type": "string",
                "description": "故事的主題或題材，例如「勇敢的小兔子冒險記」",
            },
        },
        "required": ["theme"],
    }

    def is_available(self) -> bool:
        key = getattr(config, "GEMINI_API_KEY", None)
        return bool(key and str(key).strip())

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        theme = kwargs.get("theme", "一個有趣的故事")
        logger.info("story_book_create called with theme: %s", theme)

        store = StoryStore.get()

        # Check if already generating
        if store.story and store.story.status == "generating":
            return {
                "status": "already_generating",
                "message": "故事正在產生中，請稍等一下喔！",
            }

        story = store.create_story(title=theme)

        # Launch background generation (keep reference to avoid silent exception loss)
        handler = deps.realtime_handler
        task = asyncio.create_task(_generate_story(story.id, theme, handler))
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

        return {
            "status": "generating",
            "story_id": story.id,
            "message": f"好的！我開始幫你創作「{theme}」的故事書囉！產生需要一點時間，你可以先跟我聊天。",
        }


async def _generate_story(story_id: str, theme: str, handler: Any) -> None:
    """Background task: generate story text + images via Gemini API."""
    api_key = getattr(config, "GEMINI_API_KEY", None)
    if not api_key:
        logger.error("No GEMINI_API_KEY configured")
        return

    store = StoryStore.get()

    try:
        # Step 1: Generate story text
        story_pages_text = await _generate_story_text(api_key, theme)
        if not story_pages_text:
            logger.error("Failed to generate story text")
            if store.story and store.story.id == story_id:
                store.close_story()
            return

        # Step 2: Generate illustrations for each page
        pages: list[StoryPage] = []
        for i, page_text in enumerate(story_pages_text):
            logger.info("Generating illustration for page %d/%d", i + 1, len(story_pages_text))
            image_b64, image_mime = await _generate_illustration(
                api_key, theme, page_text, i + 1, len(story_pages_text)
            )
            pages.append(StoryPage(text=page_text, image_b64=image_b64, image_mime=image_mime))

        # Step 3: Mark as ready
        store.set_story_ready(story_id, pages)
        logger.info("Story '%s' is ready with %d pages", theme, len(pages))

        # Auto-open reader in browser
        webbrowser.open("http://localhost:7860/reader")

        # Step 4: Notify the robot via conversation injection
        if handler and getattr(handler, "connection", None):
            try:
                # Wait for any in-progress response to finish before injecting
                response_idle = getattr(handler, "response_idle", None)
                if response_idle is not None:
                    try:
                        await asyncio.wait_for(response_idle.wait(), timeout=30.0)
                    except asyncio.TimeoutError:
                        logger.warning("Timed out waiting for response to finish; proceeding anyway")

                await handler.connection.conversation.item.create(
                    item={
                        "type": "message",
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": (
                                    f"[系統通知: 故事書「{theme}」已經產生完成了！共有 {len(pages)} 頁。"
                                    "請告訴小朋友故事好了，然後呼叫 story_book_go_to_page(page=0) 開始翻到第一頁朗讀故事。]"
                                ),
                            }
                        ],
                    },
                )
                await handler.connection.response.create()
            except Exception as e:
                logger.warning("Failed to notify handler about story ready: %s", e)

    except Exception as e:
        logger.exception("Story generation failed: %s", e)
        if store.story and store.story.id == story_id:
            store.close_story()


async def _generate_story_text(api_key: str, theme: str) -> list[str] | None:
    """Generate story text via Gemini API, returning a list of page texts."""
    prompt = (
        f"你是一位專門為4到7歲小朋友寫故事的作家。請用台灣繁體中文，為以下主題寫一本 {NUM_PAGES} 頁的故事書。\n\n"
        f"主題：{theme}\n\n"
        "要求：\n"
        "1. 每頁的文字要簡短（2-4句話），適合小朋友聽。\n"
        "2. 用詞簡單、溫暖、有趣。\n"
        "3. 故事要有開頭、發展、高潮和結尾。\n"
        '4. 請用以下 JSON 格式回應：{"pages": ["第一頁的文字", "第二頁的文字", ...]}\n\n'
        "只回傳 JSON，不要有其他文字。"
    )

    url = f"{GEMINI_API_BASE}/{GEMINI_TEXT_MODEL}:generateContent?key={api_key}"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.9,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=body)
            if resp.status_code != 200:
                logger.error(
                    "Gemini text API error: status=%d url=%s body=%s",
                    resp.status_code, url.split("?")[0], resp.text[:500],
                )
            resp.raise_for_status()
            data = resp.json()

        # Extract text from Gemini response
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(text)
        pages = parsed.get("pages", [])
        if len(pages) != NUM_PAGES:
            logger.warning("Expected %d pages, got %d", NUM_PAGES, len(pages))
        return pages if pages else None

    except Exception as e:
        logger.exception("Gemini text generation failed: %s", e)
        return None


async def _generate_illustration(
    api_key: str, theme: str, page_text: str, page_num: int, total_pages: int
) -> tuple[str, str]:
    """Generate a single illustration via Gemini image model. Returns (base64, mime_type)."""
    prompt = (
        f"Generate a cute storybook illustration.\n\n"
        f"Story theme: {theme}\n"
        f"Page {page_num} of {total_pages}: {page_text}\n\n"
        "Style: soft watercolor painting with warm colors, expressive cute characters, "
        "picture book art style. No text or words in the image."
    )

    url = f"{GEMINI_API_BASE}/{GEMINI_IMAGE_MODEL}:generateContent?key={api_key}"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
        },
        "safetySettings": [
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_ONLY_HIGH"},
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_ONLY_HIGH"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_ONLY_HIGH"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_ONLY_HIGH"},
        ],
    }

    max_retries = 3
    for attempt in range(max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(url, json=body)

                # Retry on transient HTTP errors
                if resp.status_code in (429, 503) and attempt < max_retries:
                    delay = 2 ** (attempt + 1)  # 2s, 4s, 8s
                    logger.warning(
                        "Gemini image API returned %d for page %d/%d; retrying in %ds (attempt %d/%d)",
                        resp.status_code, page_num, total_pages, delay, attempt + 1, max_retries,
                    )
                    await asyncio.sleep(delay)
                    continue

                if resp.status_code != 200:
                    logger.error(
                        "Gemini image API error: status=%d page=%d/%d url=%s body=%s",
                        resp.status_code, page_num, total_pages, url.split("?")[0], resp.text[:500],
                    )
                resp.raise_for_status()
                data = resp.json()

            # Extract image from response
            candidate = data.get("candidates", [{}])[0]
            content = candidate.get("content")
            if not content:
                reason = candidate.get("finishReason", "unknown")
                if attempt < max_retries:
                    delay = 2 ** (attempt + 1)
                    logger.warning(
                        "Gemini image response has no content for page %d (finishReason=%s); retrying in %ds (attempt %d/%d)",
                        page_num, reason, delay, attempt + 1, max_retries,
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.warning(
                    "Gemini image response has no content for page %d after %d retries (finishReason=%s)",
                    page_num, max_retries, reason,
                )
                return "", "image/png"

            parts = content.get("parts", [])
            for part in parts:
                if "inlineData" in part:
                    mime = part["inlineData"].get("mimeType", "image/png")
                    return part["inlineData"]["data"], mime

            # Got content but no image (text-only response) — retry
            if attempt < max_retries:
                delay = 2 ** (attempt + 1)
                logger.warning(
                    "No image data in Gemini response for page %d (text-only); retrying in %ds (attempt %d/%d)",
                    page_num, delay, attempt + 1, max_retries,
                )
                await asyncio.sleep(delay)
                continue

            logger.warning(
                "No image data in Gemini response for page %d after %d retries; keys in parts: %s",
                page_num, max_retries, [list(p.keys()) for p in parts],
            )
            return "", "image/png"

        except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as e:
            if attempt < max_retries:
                delay = 2 ** (attempt + 1)
                logger.warning(
                    "Gemini image connection error for page %d/%d: %s; retrying in %ds (attempt %d/%d)",
                    page_num, total_pages, e, delay, attempt + 1, max_retries,
                )
                await asyncio.sleep(delay)
                continue
            logger.error("Gemini image generation failed for page %d/%d after %d retries: %s", page_num, total_pages, max_retries, e)
            return "", "image/png"

        except Exception as e:
            logger.error("Gemini image generation failed for page %d/%d: %s", page_num, total_pages, e)
            return "", "image/png"
