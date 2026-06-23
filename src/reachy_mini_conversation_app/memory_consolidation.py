"""Memory consolidation via Gemini LLM.

On session start, if the number of fact memories exceeds a threshold,
this module asks Gemini to merge and deduplicate them.  Events are
left untouched.
"""

from __future__ import annotations
import json
import uuid
import logging
from typing import TYPE_CHECKING

from reachy_mini_conversation_app.memory import MemoryEntry, _now_iso


if TYPE_CHECKING:
    from reachy_mini_conversation_app.memory import MarkdownMemoryStore

logger = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-2.5-flash"

_CONSOLIDATION_PROMPT = """\
你是記憶整理助手。以下是一個機器人記住的「事實」列表（每行一項）。
請將重複、過時或矛盾的項目合併，保留最新、最完整的版本。
刪除完全重複的項目。如果兩項矛盾，保留較新的那項。

規則：
1. 輸出必須是 JSON 陣列，每個元素是一個字串（合併後的事實）。
2. 不要添加原本沒有的資訊。
3. 保持用語一致（台灣繁體中文）。
4. 只回傳 JSON，不要有其他文字。

以下是事實列表：
{facts}
"""


async def _call_gemini(api_key: str, prompt: str) -> str:
    """Call Gemini API and return the response text.

    All ``google.genai`` imports are contained here so the rest of the
    module can be imported (and tested) without the SDK installed.
    """
    from google import genai
    from google.genai import types

    retry_options = types.HttpRetryOptions(
        attempts=4,
        initial_delay=2.0,
        max_delay=16.0,
        exp_base=2.0,
        http_status_codes=[429, 500, 502, 503, 504],
    )
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=30_000,
            retry_options=retry_options,
        ),
    )
    try:
        response = await client.aio.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2,
            ),
        )
        return response.text or ""
    finally:
        await client.aio.aclose()


async def consolidate_memories(
    store: MarkdownMemoryStore,
    api_key: str,
    threshold: int = 15,
) -> bool:
    """Consolidate fact memories if count exceeds *threshold*.

    Events are preserved as-is.  Returns ``True`` if consolidation was
    performed.
    """
    entries = store.get_entries()
    facts = [e for e in entries if e.type == "fact"]
    events = [e for e in entries if e.type == "event"]

    if len(facts) < threshold:
        logger.debug(
            "Memory consolidation skipped: %d facts < threshold %d",
            len(facts),
            threshold,
        )
        return False

    logger.info("Starting memory consolidation (%d facts, threshold=%d)", len(facts), threshold)

    # Build prompt
    fact_lines = "\n".join(f"- {f.content}" for f in facts)
    prompt = _CONSOLIDATION_PROMPT.format(facts=fact_lines)

    try:
        text = await _call_gemini(api_key, prompt)

        merged_facts: list[str] = json.loads(text)
        if not isinstance(merged_facts, list):
            logger.warning("Consolidation returned non-list; skipping.")
            return False

        # Build new entries
        now = _now_iso()
        new_entries: list[MemoryEntry] = []
        for content in merged_facts:
            content = str(content).strip()
            if not content:
                continue
            new_entries.append(
                MemoryEntry(
                    id=uuid.uuid4().hex[:8],
                    type="fact",
                    content=content,
                    created=now,
                    updated=now,
                    tags=["consolidated"],
                )
            )

        # Preserve events unchanged
        new_entries.extend(events)

        store.replace_entries(new_entries)
        logger.info(
            "Memory consolidation complete: %d facts → %d merged facts, %d events preserved",
            len(facts),
            len([e for e in new_entries if e.type == "fact"]),
            len(events),
        )
        return True

    except Exception:
        logger.exception("Memory consolidation failed")
        raise
