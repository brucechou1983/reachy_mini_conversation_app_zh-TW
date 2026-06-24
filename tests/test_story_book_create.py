"""Tests for the storybook quality pipeline: bible parsing, prompts, orchestration."""

import json

import pytest

import reachy_mini_conversation_app.tools.story_book_create as sbc
from reachy_mini_conversation_app.tools.story_book_create import (
    _STYLE,
    parse_bible,
    build_page_prompt,
    build_bible_prompt,
    build_character_sheet_prompt,
)


# --- prompt builders -------------------------------------------------------
def test_bible_prompt_injects_writing_craft():
    p = build_bible_prompt("勇敢的小兔子", num_pages=8)
    assert "勇敢的小兔子" in p
    assert "8 頁" in p
    # the craft techniques that lift the copy above generic
    for keyword in ["refrain", "狀聲詞", "show don't tell", "翻頁", "故事弧"]:
        assert keyword in p
    # structured cast with locked look, and the text/scene split
    assert "characters" in p and "description" in p
    assert "text" in p and "scene" in p


def test_character_sheet_prompt_lists_every_character_and_style():
    chars = [
        {"name": "小步", "description": "a round white rabbit with a red scarf"},
        {"name": "嚕嚕", "description": "a chubby orange cat"},
    ]
    p = build_character_sheet_prompt(chars)
    assert _STYLE in p
    assert "reference sheet" in p
    for c in chars:
        assert c["name"] in p
        assert c["description"] in p
    assert "no text" in p.lower()


def test_page_prompt_demands_reference_consistency():
    chars = [{"name": "小步", "description": "a round white rabbit with a red scarf"}]
    p = build_page_prompt("小步 hops over a puddle, laughing", chars)
    assert _STYLE in p
    assert "小步 hops over a puddle" in p
    assert "consistent" in p.lower()       # must restate the consistency demand
    assert "小步" in p                      # cast restated for grounding
    assert "no text" in p.lower()


def test_page_prompt_without_characters_still_valid():
    p = build_page_prompt("a quiet forest at dawn", [])
    assert "a quiet forest at dawn" in p
    assert _STYLE in p
    assert "no text" in p.lower()


# --- bible parsing ---------------------------------------------------------
def _bible_json(num_pages=2):
    return json.dumps({
        "title": "小步的紅圍巾",
        "characters": [{"name": "小步", "description": "a round white rabbit"}],
        "pages": [
            {"text": f"第{i}頁", "scene": f"scene {i}"} for i in range(1, num_pages + 1)
        ],
    }, ensure_ascii=False)


def test_parse_bible_happy_path():
    b = parse_bible(_bible_json(3), num_pages=3)
    assert b is not None
    assert b["title"] == "小步的紅圍巾"
    assert b["characters"] == [{"name": "小步", "description": "a round white rabbit"}]
    assert [p["text"] for p in b["pages"]] == ["第1頁", "第2頁", "第3頁"]
    assert b["pages"][0]["scene"] == "scene 1"


def test_parse_bible_strips_code_fences_and_prose():
    raw = "Here is your story!\n```json\n" + _bible_json(2) + "\n```\nEnjoy!"
    b = parse_bible(raw, num_pages=2)
    assert b is not None
    assert len(b["pages"]) == 2


def test_parse_bible_legacy_string_pages_fall_back_scene_to_text():
    raw = json.dumps({"title": "X", "pages": ["甲頁", "乙頁"]}, ensure_ascii=False)
    b = parse_bible(raw, num_pages=2)
    assert b is not None
    assert b["characters"] == []
    assert b["pages"][0] == {"text": "甲頁", "scene": "甲頁"}  # scene defaults to text


def test_parse_bible_missing_scene_falls_back_to_text():
    raw = json.dumps({"pages": [{"text": "只有文字"}]}, ensure_ascii=False)
    b = parse_bible(raw, num_pages=1)
    assert b is not None
    assert b["pages"][0]["scene"] == "只有文字"


def test_parse_bible_drops_empty_text_pages():
    raw = json.dumps({"pages": [{"text": "", "scene": "x"}, {"text": "ok", "scene": "y"}]})
    b = parse_bible(raw, num_pages=2)
    assert b is not None
    assert [p["text"] for p in b["pages"]] == ["ok"]


def test_parse_bible_returns_none_on_garbage():
    assert parse_bible("not json at all", num_pages=2) is None
    assert parse_bible("", num_pages=2) is None
    assert parse_bible(json.dumps({"pages": []}), num_pages=2) is None


# --- orchestration ---------------------------------------------------------
@pytest.mark.asyncio
async def test_generate_story_uses_reference_for_every_page(monkeypatch):
    """The cast sheet is generated once and fed into every page for consistency."""
    bible = {
        "title": "小步的冒險",
        "characters": [{"name": "小步", "description": "a round white rabbit"}],
        "pages": [
            {"text": "第一頁", "scene": "小步 wakes up"},
            {"text": "第二頁", "scene": "小步 runs"},
        ],
    }

    async def fake_bible(theme, num_pages):
        return bible

    sheet = (b"REFSHEET", "image/png")

    async def fake_sheet(characters):
        assert characters == bible["characters"]
        return sheet

    page_refs = []

    async def fake_illustration(scene, characters, ref):
        page_refs.append(ref)
        return ("b64data", "image/png")

    monkeypatch.setattr(sbc, "_generate_story_bible", fake_bible)
    monkeypatch.setattr(sbc, "_generate_character_sheet", fake_sheet)
    monkeypatch.setattr(sbc, "_generate_illustration", fake_illustration)
    monkeypatch.setattr(sbc.config, "GEMINI_AVAILABLE", True)
    monkeypatch.setattr(sbc.webbrowser, "open", lambda *a, **k: None)

    store = sbc.StoryStore.get()
    story = store.create_story(title="raw theme")

    # avoid disk/library writes in the test
    import reachy_mini_conversation_app.book_library as bl
    monkeypatch.setattr(bl.BookLibrary, "save_book", lambda self, s: None)

    await sbc._generate_story(story.id, "raw theme", 2, handler=None)

    # every page got the SAME reference sheet
    assert page_refs == [sheet, sheet]
    # pages stored with narration text + image
    assert [p.text for p in store.story.pages] == ["第一頁", "第二頁"]
    assert all(p.image_b64 == "b64data" for p in store.story.pages)
    # nicer title from the bible replaced the raw theme
    assert store.story.title == "小步的冒險"
    store.close_story()


@pytest.mark.asyncio
async def test_generate_story_closes_on_bible_failure(monkeypatch):
    async def fake_bible(theme, num_pages):
        return None

    monkeypatch.setattr(sbc, "_generate_story_bible", fake_bible)
    monkeypatch.setattr(sbc.config, "GEMINI_AVAILABLE", True)

    store = sbc.StoryStore.get()
    story = store.create_story(title="t")
    await sbc._generate_story(story.id, "t", 2, handler=None)
    assert store.story is None  # closed out


@pytest.mark.asyncio
async def test_generate_story_proceeds_without_reference_sheet(monkeypatch):
    """If the cast sheet fails, pages still generate (ref=None)."""
    bible = {
        "title": "T",
        "characters": [{"name": "小步", "description": "rabbit"}],
        "pages": [{"text": "頁", "scene": "s"}],
    }

    async def fake_bible(theme, num_pages):
        return bible

    async def fake_sheet(characters):
        return None  # sheet generation failed

    seen = []

    async def fake_illustration(scene, characters, ref):
        seen.append(ref)
        return ("", "image/png")

    monkeypatch.setattr(sbc, "_generate_story_bible", fake_bible)
    monkeypatch.setattr(sbc, "_generate_character_sheet", fake_sheet)
    monkeypatch.setattr(sbc, "_generate_illustration", fake_illustration)
    monkeypatch.setattr(sbc.config, "GEMINI_AVAILABLE", True)
    monkeypatch.setattr(sbc.webbrowser, "open", lambda *a, **k: None)
    import reachy_mini_conversation_app.book_library as bl
    monkeypatch.setattr(bl.BookLibrary, "save_book", lambda self, s: None)

    store = sbc.StoryStore.get()
    story = store.create_story(title="t")
    await sbc._generate_story(story.id, "t", 1, handler=None)
    assert seen == [None]
    store.close_story()


@pytest.mark.asyncio
async def test_generate_book_image_returns_empty_on_failure(monkeypatch):
    async def fake_bytes(prompt, ref=None):
        return None

    monkeypatch.setattr(sbc, "_generate_image_bytes", fake_bytes)
    b64, mime = await sbc.generate_book_image("prompt")
    assert b64 == ""
    assert mime == "image/png"


@pytest.mark.asyncio
async def test_generate_book_image_encodes_bytes(monkeypatch):
    async def fake_bytes(prompt, ref=None):
        return (b"hello", "image/jpeg")

    monkeypatch.setattr(sbc, "_generate_image_bytes", fake_bytes)
    b64, mime = await sbc.generate_book_image("prompt")
    import base64
    assert base64.b64decode(b64) == b"hello"
    assert mime == "image/jpeg"


def test_generate_story_handler_unused_when_no_backend():
    """Smoke: module exposes the expected public surface."""
    assert hasattr(sbc, "generate_book_image")
    assert hasattr(sbc, "build_bible_prompt")
    assert isinstance(_STYLE, str) and "工藤紀子" in _STYLE
