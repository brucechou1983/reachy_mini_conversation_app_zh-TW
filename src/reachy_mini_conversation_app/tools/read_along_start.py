"""Tool: read_along_start — begin an Ello-style SEL picture-book read-along.

Unlike the storybook tools (where the robot narrates), here the *child* reads
and the robot listens and scaffolds.  This tool lists the curated SEL books or,
given a book id, opens the read-along reader, warms up the target words, and
returns the page-1 words plus the full Ello coaching protocol.
"""

from __future__ import annotations
import asyncio
import logging
import webbrowser
from typing import Any, Dict

from reachy_mini_conversation_app.read_along_books import (
    READING_MODES,
    MODE_DECODABLE,
    catalog,
    get_book,
)
from reachy_mini_conversation_app.read_along_store import ReadAlongStore
from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies
from reachy_mini_conversation_app.read_along_progress import ReadAlongProgress
from reachy_mini_conversation_app.read_along_illustrate import ensure_book_assets


logger = logging.getLogger(__name__)

SHELF_URL = "http://localhost:7860/reader/read-along"


def catalog_with_progress() -> list[dict[str, Any]]:
    """Return the curated catalogue annotated with completion + best stars."""
    progress = ReadAlongProgress.get()
    out: list[dict[str, Any]] = []
    for b in catalog():
        rec = progress.get_book(str(b["id"])) or {}
        out.append({**b, "completed": bool(rec.get("completed")), "stars": int(rec.get("stars", 0))})
    return out


def build_protocol(title: str, sel_theme: str, warmup: list[str], sel_prompt: str) -> str:
    """Build the Ello-style coaching protocol returned at session start."""
    warm = ", ".join(warmup) if warmup else "（這本沒有暖身單字）"
    return (
        f"[繪本帶讀模式 — 用 Ello 的方式帶 4-6 歲小朋友讀英文]\n"
        f"你要帶小朋友讀繪本《{title}》（情緒主題：{sel_theme}）。閱讀器已打開，會顯示每頁的圖和英文字。\n\n"
        "核心原則（務必遵守）：\n"
        "1. 小朋友自己讀，你用聽的。絕對不要幫他把整頁唸完。\n"
        f"2. 先暖身：把目標單字念給他聽一次（每個慢慢念清楚）：{warm}。\n"
        "3. 邀請他讀這一頁：用中文說「換你讀～慢慢來」，可以說 \"Let's read together!\"。\n"
        "4. **仔細聽他讀的每一個字**，然後呼叫 read_along_grade(correct=[讀對的字], "
        "incorrect=[讀錯/發音不對/漏掉的字])。只要有一個字沒讀對或漏掉，就放進 incorrect，"
        "**不要寬鬆地全部當作讀對**。\n"
        "5. grade 會回傳還沒讀對的字。對這些字：先輕推「試試看第一個音」，還是不會就幫他『拆音』"
        "（一個音一個音念，例如 h-a-ppy），再念整個字示範，請他再讀一次，然後再 grade 一次。\n"
        "6. **重要：他再讀一次時要重新仔細聽，不要因為他試了第二次就放水。** 如果他還是讀成原本的"
        "錯音（例如把 scared 讀成 said），就繼續把那個字放進 incorrect、繼續帶他練；"
        "**只有當他真的讀對那個字（聲音對得上）才放進 correct**。寧可多練一次，也不要把錯的當對的。\n"
        "7. **只有當整頁每個字都讀對（grade 回傳 complete=true、全部變綠色）才可以翻頁。**"
        "系統會擋住沒讀完的翻頁——沒全綠就 read_along_next_page 會被拒絕。\n"
        "8. 永遠不要說「你錯了」。要說「我們再讀一次這個字」。\n"
        "9. 整頁全綠後 → read_along_next_page() 翻下一頁。\n"
        f"10. 每頁讀完，用中文問一個開放式情緒/理解問題：「{sel_prompt}」，聽他回答、簡短回應、連結到他的真實感受。\n"
        "11. 多鼓勵，可搭配 play_emotion 或 dance 慶祝。\n"
        "12. 讀完最後一頁（也要全綠）→ read_along_finish(stars=N) 給星星並念鼓勵的話。\n"
        "（小提醒：小朋友也可以用手點閱讀器上的字求助，你就幫他拆音。）\n"
        "回應簡短，一次最多 1-2 句；英文單字念清楚、慢一點。"
    )


class ReadAlongStart(Tool):
    """List curated SEL books, or open one and start the read-along."""

    name = "read_along_start"
    requires_screen = True  # needs the on-screen reader
    description = (
        "開始『跟著汪汪讀英文繪本』(Ello 式帶讀，小朋友自己讀、你陪讀引導)。"
        "不帶 book_id 時，列出可選的英文情緒繪本讓小朋友挑。"
        "帶 book_id 時，打開繪本閱讀器並開始帶讀第一頁。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "book_id": {
                "type": "string",
                "description": "要讀的繪本 ID（從不帶參數的列表取得，例如 'sel-big-feelings'）",
            },
            "mode": {
                "type": "string",
                "enum": list(READING_MODES),
                "description": "decodable=小朋友自己讀；turn_taking=你一句他一句。預設 decodable",
            },
        },
        "required": [],
    }

    @staticmethod
    def _bind_handler(deps: ToolDependencies) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        ReadAlongStore.get().bind_handler(deps.realtime_handler, loop)

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        """List books (open the shelf), or load one and start a read-along."""
        book_id = (kwargs.get("book_id") or "").strip()
        if not book_id:
            # Bind the handler now so a shelf tap can start coaching, and open
            # the visual bookshelf so the child can see and pick a book.
            self._bind_handler(deps)
            try:
                webbrowser.open(SHELF_URL)
            except Exception as e:
                logger.warning("Could not auto-open read-along shelf: %s", e)
            return {
                "status": "listing",
                "books": catalog_with_progress(),
                "shelf_url": SHELF_URL,
                "message": (
                    "我把繪本書架打開了！螢幕上有幾本英文情緒小繪本，問問小朋友想讀哪一本"
                    "（讀過的會有綠色勾勾）。他可以直接在螢幕上點選，或跟你說書名。"
                ),
            }

        book = get_book(book_id)
        if book is None:
            return {
                "error": f"找不到繪本 book_id={book_id}",
                "books": catalog_with_progress(),
            }

        mode = kwargs.get("mode") or MODE_DECODABLE
        if mode not in READING_MODES:
            mode = MODE_DECODABLE

        # Import text now; illustrate in the background (best-effort).
        assets = ensure_book_assets(book)

        store = ReadAlongStore.get()
        session = store.start(book, mode)
        self._bind_handler(deps)

        reader_url = f"http://localhost:7860/reader/read-along/{book.id}"
        try:
            webbrowser.open(reader_url)
        except Exception as e:
            logger.warning("Could not auto-open read-along reader: %s", e)

        page = session.current
        return {
            "status": "reading",
            "book_id": book.id,
            "title": book.title,
            "sel_theme": book.sel_theme,
            "mode": mode,
            "total_pages": session.total_pages,
            "page": 1,
            "page_text": page.text,
            "words": list(session.current_words),
            "tricky": list(page.tricky),
            "warmup": list(book.warmup),
            "sel_prompt": page.sel_prompt,
            "is_last_page": session.is_last_page,
            "reader_url": reader_url,
            "illustrating": assets.get("illustrating", False),
            "protocol": build_protocol(book.title, book.sel_theme, book.warmup, page.sel_prompt),
            "message": (
                f"打開繪本《{book.title}》了！先帶小朋友暖身這些單字：{', '.join(book.warmup)}，"
                "再邀請他讀第一頁。記得：他讀，你聽、你陪。"
            ),
        }
