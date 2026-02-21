"""Tool: story_book_create - Asynchronously generate a multi-page story book via Gemini."""

from __future__ import annotations
import json
import base64
import asyncio
import logging
import webbrowser
from typing import Any, Dict

from google import genai
from google.genai import types

from reachy_mini_conversation_app.config import config
from reachy_mini_conversation_app.story_store import StoryPage, StoryStore
from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies


logger = logging.getLogger(__name__)

GEMINI_TEXT_MODEL = "gemini-2.5-flash"
GEMINI_IMAGE_MODEL = "gemini-2.5-flash-image"
DEFAULT_NUM_PAGES = 12

# Retry configuration for Gemini API calls
_RETRY_OPTIONS = types.HttpRetryOptions(
    attempts=4,
    initial_delay=2.0,
    max_delay=16.0,
    exp_base=2.0,
    http_status_codes=[429, 500, 502, 503, 504],
)


def _make_client(api_key: str, timeout: float = 60_000) -> genai.Client:
    """Create a Gemini client with retry and timeout configuration."""
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=int(timeout),
            retry_options=_RETRY_OPTIONS,
        ),
    )


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
            "num_pages": {
                "type": "integer",
                "description": "故事的頁數，預設為 12 頁",
                "default": DEFAULT_NUM_PAGES,
                "minimum": 4,
                "maximum": 99,
            },
        },
        "required": ["theme"],
    }

    def is_available(self) -> bool:
        key = getattr(config, "GEMINI_API_KEY", None)
        return bool(key and str(key).strip())

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        theme = kwargs.get("theme", "一個有趣的故事")
        num_pages = kwargs.get("num_pages", DEFAULT_NUM_PAGES)
        num_pages = max(4, min(99, int(num_pages)))
        logger.info("story_book_create called with theme: %s, num_pages: %d", theme, num_pages)

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
        task = asyncio.create_task(_generate_story(story.id, theme, num_pages, handler))
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

        return {
            "status": "generating",
            "story_id": story.id,
            "message": f"好的！我開始幫你創作「{theme}」的故事書囉！產生需要一點時間，你可以先跟我聊天。",
        }


async def _generate_story(story_id: str, theme: str, num_pages: int, handler: Any) -> None:
    """Background task: generate story text + images via Gemini API."""
    api_key = getattr(config, "GEMINI_API_KEY", None)
    if not api_key:
        logger.error("No GEMINI_API_KEY configured")
        return

    store = StoryStore.get()

    try:
        # Step 1: Generate story text
        story_pages_text = await _generate_story_text(api_key, theme, num_pages)
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

        # Persist to disk library (use captured reference to avoid race with close_story)
        current_story = store.story
        if current_story and current_story.id == story_id:
            try:
                from reachy_mini_conversation_app.book_library import BookLibrary
                BookLibrary.get().save_book(current_story)
            except Exception as e:
                logger.warning("Failed to save book to library: %s", e)

        # Auto-open reader in browser
        webbrowser.open(f"http://localhost:7860/reader/books/{story_id}")

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


async def _generate_story_text(api_key: str, theme: str, num_pages: int = DEFAULT_NUM_PAGES) -> list[str] | None:
    """Generate story text via Gemini API, returning a list of page texts."""
    prompt = (
        f"你是一位專門為4到7歲小朋友寫故事的作家。請用台灣繁體中文，為以下主題寫一本 {num_pages} 頁的故事書。\n\n"
        f"主題：{theme}\n\n"
        "要求：\n"
        "1. 每頁的文字要簡短（2-4句話），適合小朋友聽。\n"
        "2. 用詞簡單、溫暖、有趣。\n"
        "3. 故事要有開頭、發展、高潮和結尾。\n"
        '4. 請用以下 JSON 格式回應：{"pages": ["第一頁的文字", "第二頁的文字", ...]}\n\n'
        "只回傳 JSON，不要有其他文字。"
    )

    client = _make_client(api_key, timeout=60_000)
    try:
        response = await client.aio.models.generate_content(
            model=GEMINI_TEXT_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.9,
            ),
        )

        text = response.text
        parsed = json.loads(text)
        pages = parsed.get("pages", [])
        if len(pages) != num_pages:
            logger.warning("Expected %d pages, got %d", num_pages, len(pages))
        return pages if pages else None

    except Exception as e:
        logger.exception("Gemini text generation failed: %s", e)
        return None
    finally:
        await client.aio.aclose()


_IMAGE_GEN_MAX_RETRIES = 3
_IMAGE_GEN_RETRY_DELAY = 2.0


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

    for attempt in range(1, _IMAGE_GEN_MAX_RETRIES + 1):
        client = _make_client(api_key, timeout=120_000)
        try:
            response = await client.aio.models.generate_content(
                model=GEMINI_IMAGE_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                    safety_settings=[
                        types.SafetySetting(
                            category="HARM_CATEGORY_DANGEROUS_CONTENT",
                            threshold="BLOCK_ONLY_HIGH",
                        ),
                        types.SafetySetting(
                            category="HARM_CATEGORY_HARASSMENT",
                            threshold="BLOCK_ONLY_HIGH",
                        ),
                        types.SafetySetting(
                            category="HARM_CATEGORY_HATE_SPEECH",
                            threshold="BLOCK_ONLY_HIGH",
                        ),
                        types.SafetySetting(
                            category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
                            threshold="BLOCK_ONLY_HIGH",
                        ),
                    ],
                ),
            )

            # Extract image from response parts
            if response.candidates:
                candidate = response.candidates[0]
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if part.inline_data is not None:
                            mime = part.inline_data.mime_type or "image/png"
                            image_bytes = part.inline_data.data
                            image_b64 = base64.b64encode(image_bytes).decode("ascii")
                            return image_b64, mime

            if attempt < _IMAGE_GEN_MAX_RETRIES:
                logger.warning(
                    "No image data in Gemini response for page %d/%d (attempt %d/%d), retrying...",
                    page_num, total_pages, attempt, _IMAGE_GEN_MAX_RETRIES,
                )
                await asyncio.sleep(_IMAGE_GEN_RETRY_DELAY * attempt)
            else:
                logger.warning(
                    "No image data in Gemini response for page %d/%d after %d attempts",
                    page_num, total_pages, _IMAGE_GEN_MAX_RETRIES,
                )
                return "", "image/png"

        except Exception as e:
            if attempt < _IMAGE_GEN_MAX_RETRIES:
                logger.warning(
                    "Gemini image generation failed for page %d/%d (attempt %d/%d): %s, retrying...",
                    page_num, total_pages, attempt, _IMAGE_GEN_MAX_RETRIES, e,
                )
                await asyncio.sleep(_IMAGE_GEN_RETRY_DELAY * attempt)
            else:
                logger.error(
                    "Gemini image generation failed for page %d/%d after %d attempts: %s",
                    page_num, total_pages, _IMAGE_GEN_MAX_RETRIES, e,
                )
                return "", "image/png"
        finally:
            await client.aio.aclose()

    return "", "image/png"
