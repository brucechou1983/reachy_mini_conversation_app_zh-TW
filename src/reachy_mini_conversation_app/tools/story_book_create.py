"""Tool: story_book_create - Asynchronously generate a multi-page story book via Gemini.

Quality is driven by a three-step pipeline (see ``_generate_story``):

1. **Story bible** — one structured-JSON text call that designs a small fixed cast
   (each character gets a locked visual ``description``) and writes every page as a
   ``text`` (the Traditional-Chinese narration the child hears) plus a ``scene`` (an
   English visual brief for the illustrator). The writing prompt bakes in concrete
   picture-book craft (story arc, a recurring refrain, onomatopoeia, show-don't-tell,
   read-aloud rhythm, page-turn hooks) so the copy isn't generic.
2. **Character reference sheet** — one image of the whole cast together, front view,
   in a strong house style (``_STYLE``). This *defines* how each character looks.
3. **Per-page illustrations** — every page is generated with the reference sheet fed
   back in as an image input, so characters stay visually identical page to page
   instead of drifting (the previous pipeline generated each page in isolation).
"""

from __future__ import annotations
import json
import base64
import asyncio
import logging
import webbrowser
from typing import Any, Dict, List, Tuple, Optional

from google.genai import types

from reachy_mini_conversation_app.config import config
from reachy_mini_conversation_app.story_store import StoryPage, StoryStore
from reachy_mini_conversation_app.genai_client import make_genai_client
from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies


logger = logging.getLogger(__name__)

GEMINI_TEXT_MODEL = "gemini-2.5-flash"
GEMINI_IMAGE_MODEL = "gemini-2.5-flash-image"
DEFAULT_NUM_PAGES = 12

# Shared house art style for every generated illustration. Described by its visual
# characteristics (not only by name) so it holds even if the artist name is ignored
# or filtered — the look of classic Japanese 絵本 in the spirit of Noriko Kudo
# (工藤紀子, the Noraneko-gundan / Kon-to-Aki books).
_STYLE = (
    "Art style: classic Japanese picture-book (絵本) illustration in the warm, "
    "playful spirit of Noriko Kudo (工藤紀子). Bold, clean, even-weight black ink "
    "outlines; flat warm gouache-like color fills with a hint of paper texture; "
    "rounded, chunky, huggable character designs with simple dot-and-curve faces "
    "and big expressive eyes; a bright, slightly retro palette of warm yellows, "
    "soft reds, leaf greens and cream backgrounds; cozy, lively, gently humorous "
    "compositions with soft even lighting; wholesome and child-friendly."
)


def _make_client(timeout: float = 60_000) -> Any:
    """Create a Gemini client (Vertex AI or AI Studio) with retry and timeout."""
    return make_genai_client(timeout_ms=int(timeout), retry=True)


class StoryBookCreate(Tool):
    """Asynchronously create a multi-page illustrated story book."""

    name = "story_book_create"
    requires_screen = True  # needs the on-screen reader
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
        """Return True when a Gemini backend (AI Studio key or Vertex AI) is configured."""
        return config.GEMINI_AVAILABLE

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        """Kick off background story generation and return immediately."""
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
    """Background task: design a story bible, lock the cast, then illustrate each page."""
    if not config.GEMINI_AVAILABLE:
        logger.error("No Gemini backend configured (set GEMINI_API_KEY or GOOGLE_GENAI_USE_VERTEXAI)")
        return

    store = StoryStore.get()

    try:
        # Step 1: design the story bible (cast + per-page text & scene).
        bible = await _generate_story_bible(theme, num_pages)
        if not bible or not bible["pages"]:
            logger.error("Failed to generate story bible")
            if store.story and store.story.id == story_id:
                store.close_story()
            return
        characters = bible["characters"]
        pages_data = bible["pages"]
        logger.info(
            "Story bible ready: %d characters, %d pages", len(characters), len(pages_data)
        )

        # Step 2: lock the cast with one reference sheet (best-effort; pages still
        # generate without it, just with weaker consistency).
        ref = await _generate_character_sheet(characters)
        if ref is None and characters:
            logger.warning("Character reference sheet unavailable; pages may drift")

        # Step 3: illustrate every page using the reference sheet for consistency.
        pages: list[StoryPage] = []
        for i, page in enumerate(pages_data):
            logger.info("Generating illustration for page %d/%d", i + 1, len(pages_data))
            image_b64, image_mime = await _generate_illustration(page["scene"], characters, ref)
            pages.append(StoryPage(text=page["text"], image_b64=image_b64, image_mime=image_mime))

        # Prefer the bible's title (nicer than the raw theme) for the saved book.
        current = store.story
        if current and current.id == story_id and bible.get("title"):
            current.title = bible["title"]

        # Step 4: Mark as ready
        store.set_story_ready(story_id, pages)
        logger.info("Story '%s' is ready with %d pages", bible.get("title") or theme, len(pages))

        # Persist to disk library (use captured reference to avoid race with close_story)
        current_story = store.story
        if current_story and current_story.id == story_id:
            try:
                from reachy_mini_conversation_app.book_library import KIND_STORY, BookLibrary
                BookLibrary.get().save_book(current_story, kind=KIND_STORY)
            except Exception as e:
                logger.warning("Failed to save book to library: %s", e)

        # If the child switched to another activity while this generated in the
        # background, don't pop a story reader or start narrating over them.
        from reachy_mini_conversation_app.activity_state import STORY, ActivityState
        if ActivityState.get().current not in (STORY, None):
            logger.info("Story ready but activity switched away (%s); not opening/reading",
                        ActivityState.get().current)
            return

        # Auto-open reader in browser
        webbrowser.open(f"http://localhost:7860/reader/books/{story_id}")

        # Step 5: book is ready — start reading it. Client-driven (the app fetches
        # each page and asks the model to narrate it); works for BOTH backends via
        # StoryReaderMixin.begin_story_autoread.
        connected = getattr(handler, "connection", None) or getattr(handler, "session", None)
        if handler and connected and hasattr(handler, "begin_story_autoread"):
            try:
                logger.info("Story ready — starting auto-read (%s)", type(handler).__name__)
                await handler.begin_story_autoread(1)
            except Exception as e:
                logger.warning("Failed to start story auto-read: %s", e)
        else:
            logger.warning(
                "Story ready but auto-read NOT started (handler=%s connected=%s has_method=%s)",
                handler is not None, bool(connected), hasattr(handler, "begin_story_autoread"),
            )

    except Exception as e:
        logger.exception("Story generation failed: %s", e)
        if store.story and store.story.id == story_id:
            store.close_story()


# ----------------------------------------------------------------------------
# Prompt builders (pure functions — unit-tested without hitting the API)
# ----------------------------------------------------------------------------
def build_bible_prompt(theme: str, num_pages: int = DEFAULT_NUM_PAGES) -> str:
    """Build the structured-JSON prompt that designs the story bible.

    The writing brief injects concrete picture-book craft so the copy isn't bland,
    and asks for a fixed cast with locked visual descriptions so the illustrator can
    keep characters consistent. Narration ``text`` is Traditional Chinese (for the
    child); ``description`` and ``scene`` are English (for the image model).
    """
    return (
        "你是一位得獎的台灣兒童繪本作家，擅長為 4 到 7 歲小朋友創作朗讀繪本。\n"
        f"請為以下主題創作一本 {num_pages} 頁的繪本，並回傳結構化 JSON。\n\n"
        f"主題：{theme}\n\n"
        "【角色設定 characters】\n"
        "- 先確定 1 到 3 個主要角色，給每個角色「固定」的外觀，整本書都要長一樣。\n"
        "- 每個角色提供：name（角色名，台灣繁體中文）、description（英文的外觀描述，"
        "只描述長相：物種、體型、顏色、五官特徵、固定的服裝或配件；不要寫劇情）。\n\n"
        "【文案手法 — 請務必運用，這是品質關鍵】\n"
        "1. 清楚的故事弧：主角「想要什麼」→ 遇到「阻礙」→ 嘗試與「轉折」→ 溫暖、"
        "情緒滿足的「結局」（帶一點點成長，但不要說教）。\n"
        "2. 重複句／回應句（refrain）：設計一句好記、會重複出現的句子，讓小朋友能預測、"
        "跟著一起說。\n"
        "3. 狀聲詞與擬聲擬態：適度加入聲音詞（像「碰！」「咻——」「啪躂啪躂」），"
        "朗讀起來更生動。\n"
        "4. 具體感官、show don't tell：用看得到、聽得到、摸得到的細節表現情緒，"
        "不要直接寫「他很開心」。\n"
        "5. 朗讀節奏：句子短、有韻律，偶爾押韻，唸出來順口。\n"
        "6. 翻頁懸念：每頁結尾留一點點期待或小問題，讓小朋友想翻下一頁。\n"
        "7. 結尾溫暖、完整、令人安心。\n\n"
        "【每頁 pages】\n"
        "- text：該頁朗讀文字，台灣繁體中文，2 到 4 句短句，用詞簡單溫暖。\n"
        "- scene：該頁要畫的畫面，用英文，明確用角色 name 指名是誰、在做什麼動作、"
        "在哪裡、什麼表情情緒；一到兩句即可，畫面裡不要有任何文字。\n\n"
        "回傳格式（只回傳 JSON，不要有其他文字）：\n"
        '{"title": "故事標題", "characters": [{"name": "角色名", "description": "english look"}], '
        '"pages": [{"text": "朗讀文字", "scene": "english scene"}]}'
    )


def _roster(characters: List[Dict[str, str]]) -> str:
    """One-line cast roster ("name (description); …") for image prompts."""
    bits = []
    for c in characters:
        name = c.get("name", "").strip()
        desc = c.get("description", "").strip()
        if name and desc:
            bits.append(f"{name} ({desc})")
        elif name or desc:
            bits.append(name or desc)
    return "; ".join(bits)


def build_character_sheet_prompt(characters: List[Dict[str, str]]) -> str:
    """Prompt for the single cast reference sheet that locks every character's look."""
    roster = "\n".join(
        f"- {c.get('name', '').strip()}: {c.get('description', '').strip()}".rstrip(": ")
        for c in characters
    )
    return "\n".join([
        "Create a single character reference sheet for a children's picture book.",
        _STYLE,
        "Show ALL of these characters together in one image, full body, front view, "
        "standing in a row on a plain off-white background, in friendly neutral poses. "
        "Make each character distinct and memorable; this sheet defines exactly how "
        "each character looks for the whole book.",
        "Characters:\n" + roster,
        "Absolutely no text, words, letters or labels anywhere in the image.",
    ])


def build_page_prompt(scene: str, characters: List[Dict[str, str]]) -> str:
    """Prompt for one page; restates the cast and demands reference consistency."""
    parts = ["Illustrate one full page of a children's picture book.", _STYLE]
    roster = _roster(characters)
    if roster:
        parts.append(
            "Keep every character EXACTLY consistent with the reference image — same "
            "faces, colors, outfits and proportions. Cast: " + roster + "."
        )
    parts.append("Scene to draw: " + scene)
    parts.append(
        "Full-bleed illustration. Absolutely no text, words, letters, numbers or "
        "captions anywhere in the image."
    )
    return "\n".join(parts)


def parse_bible(text: str, num_pages: int = DEFAULT_NUM_PAGES) -> Optional[Dict[str, Any]]:
    """Parse the bible JSON robustly into ``{title, characters, pages}``.

    Tolerates code fences / stray prose (extracts the outermost ``{...}``), accepts
    both the new page format (``{text, scene}``) and the legacy list-of-strings, and
    falls the ``scene`` back to the narration text when one isn't provided. Returns
    ``None`` if no usable pages could be parsed.
    """
    raw = (text or "").strip()
    data: Any = None
    for candidate in (raw, _extract_braces(raw)):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
            break
        except Exception:
            continue
    if not isinstance(data, dict):
        return None

    title = str(data.get("title") or "").strip()

    characters: List[Dict[str, str]] = []
    for c in data.get("characters") or []:
        if isinstance(c, dict):
            name = str(c.get("name") or "").strip()
            desc = str(c.get("description") or "").strip()
        else:
            name, desc = "", str(c).strip()
        if name or desc:
            characters.append({"name": name, "description": desc})

    pages: List[Dict[str, str]] = []
    for p in data.get("pages") or []:
        if isinstance(p, dict):
            ptext = str(p.get("text") or "").strip()
            scene = str(p.get("scene") or "").strip() or ptext
        else:
            ptext = str(p).strip()
            scene = ptext
        if ptext:
            pages.append({"text": ptext, "scene": scene})

    if not pages:
        return None
    if len(pages) != num_pages:
        logger.warning("Story bible: expected %d pages, got %d", num_pages, len(pages))
    return {"title": title, "characters": characters, "pages": pages}


def _extract_braces(raw: str) -> str:
    """Return the substring from the first ``{`` to the last ``}`` (or "")."""
    try:
        start = raw.index("{")
        end = raw.rindex("}")
    except ValueError:
        return ""
    return raw[start : end + 1] if end > start else ""


# ----------------------------------------------------------------------------
# Generation (API calls)
# ----------------------------------------------------------------------------
async def _generate_story_bible(theme: str, num_pages: int = DEFAULT_NUM_PAGES) -> Optional[Dict[str, Any]]:
    """Generate the structured story bible (cast + per-page text & scene)."""
    prompt = build_bible_prompt(theme, num_pages)
    client = _make_client(timeout=60_000)
    try:
        response = await client.aio.models.generate_content(
            model=GEMINI_TEXT_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.9,
            ),
        )
        return parse_bible(response.text or "", num_pages)
    except Exception as e:
        logger.exception("Gemini story-bible generation failed: %s", e)
        return None
    finally:
        await client.aio.aclose()


_IMAGE_GEN_MAX_RETRIES = 3
_IMAGE_GEN_RETRY_DELAY = 2.0

_IMAGE_SAFETY = [
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
        threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
    ),
]


async def _generate_image_bytes(
    prompt: str, ref: Optional[Tuple[bytes, str]] = None
) -> Optional[Tuple[bytes, str]]:
    """Generate one image, optionally conditioned on a reference image.

    Returns ``(image_bytes, mime_type)`` or ``None`` on failure. When ``ref`` is
    given it is sent as an image input so the model reuses those characters/style.
    """
    contents: List[Any] = []
    if ref is not None:
        ref_bytes, ref_mime = ref
        contents.append(types.Part.from_bytes(data=ref_bytes, mime_type=ref_mime))
    contents.append(prompt)

    for attempt in range(1, _IMAGE_GEN_MAX_RETRIES + 1):
        client = _make_client(timeout=120_000)
        try:
            response = await client.aio.models.generate_content(
                model=GEMINI_IMAGE_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                    safety_settings=_IMAGE_SAFETY,
                ),
            )
            if response.candidates:
                candidate = response.candidates[0]
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if part.inline_data is not None and part.inline_data.data is not None:
                            mime = part.inline_data.mime_type or "image/png"
                            return part.inline_data.data, mime

            if attempt < _IMAGE_GEN_MAX_RETRIES:
                logger.warning(
                    "No image data in Gemini response (attempt %d/%d), retrying...",
                    attempt, _IMAGE_GEN_MAX_RETRIES,
                )
                await asyncio.sleep(_IMAGE_GEN_RETRY_DELAY * attempt)
            else:
                logger.warning("No image data in Gemini response after %d attempts", _IMAGE_GEN_MAX_RETRIES)
                return None
        except Exception as e:
            if attempt < _IMAGE_GEN_MAX_RETRIES:
                logger.warning(
                    "Gemini image generation failed (attempt %d/%d): %s, retrying...",
                    attempt, _IMAGE_GEN_MAX_RETRIES, e,
                )
                await asyncio.sleep(_IMAGE_GEN_RETRY_DELAY * attempt)
            else:
                logger.error("Gemini image generation failed after %d attempts: %s", _IMAGE_GEN_MAX_RETRIES, e)
                return None
        finally:
            await client.aio.aclose()

    return None


async def generate_book_image(
    prompt: str, ref: Optional[Tuple[bytes, str]] = None
) -> Tuple[str, str]:
    """Generate one illustration and return ``(base64, mime)`` (``("", "image/png")`` on failure).

    Shared low-level entry point used by the storybook pages and by the read-along
    importer; callers build their own prompt and optionally pass a reference image.
    """
    result = await _generate_image_bytes(prompt, ref)
    if result is None:
        return "", "image/png"
    image_bytes, mime = result
    return base64.b64encode(image_bytes).decode("ascii"), mime


async def _generate_character_sheet(
    characters: List[Dict[str, str]],
) -> Optional[Tuple[bytes, str]]:
    """Generate the cast reference sheet; returns raw ``(bytes, mime)`` or ``None``."""
    if not characters:
        return None
    result = await _generate_image_bytes(build_character_sheet_prompt(characters))
    if result is not None:
        logger.info("Character reference sheet generated (%d characters)", len(characters))
    return result


async def _generate_illustration(
    scene: str, characters: List[Dict[str, str]], ref: Optional[Tuple[bytes, str]]
) -> Tuple[str, str]:
    """Generate one page illustration (base64, mime) using the reference sheet."""
    return await generate_book_image(build_page_prompt(scene, characters), ref)
