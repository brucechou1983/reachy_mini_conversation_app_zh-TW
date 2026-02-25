"""Integration tests for system-driven story page advance logic.

The new model: the tool returns structured data (next_page, is_last_page)
and the system auto-advances pages after audio playback finishes.
Instructions no longer contain explicit tool-call commands.
"""

import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure src is on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Mock heavy dependencies that aren't installed in dev environments
for mod_name in (
    "reachy_mini",
    "reachy_mini.media",
    "reachy_mini.media.media_manager",
    "cv2",
    "gradio",
    "openai",
    "fastrtc",
):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

from reachy_mini_conversation_app.story_store import StoryStore, Story, StoryPage
from reachy_mini_conversation_app.tools.story_book_go_to_page import StoryBookGoToPage
from reachy_mini_conversation_app.tools.story_book_close import StoryBookClose


# ---------------------------------------------------------------------------
# Simulation helpers
# ---------------------------------------------------------------------------

async def simulate_story_session(num_pages, behavior="normal", use_load=False):
    """Simulate a complete story reading session using system-driven auto-advance.

    Parameters
    ----------
    num_pages : int
        Number of pages in the generated story.
    behavior : str
        ``"normal"`` for uninterrupted read-through, or
        ``"interrupt_on_page_N"`` to simulate the user interrupting on page N
        (auto-advance cancelled, then LLM resumes on the same page).
    use_load : bool
        If True, use ``StoryStore.load_story`` instead of create + set_ready.

    Returns
    -------
    tuple
        (pages_visited, story_status, results)
    """
    store = StoryStore.get()
    pages = [StoryPage(text=f"第{i}頁的內容") for i in range(num_pages)]

    if use_load:
        story = Story(
            id=str(uuid.uuid4()),
            title="載入的故事",
            pages=pages,
            status="ready",
        )
        store.load_story(story)
    else:
        story = store.create_story("測試故事")
        store.set_story_ready(story.id, pages)

    go_to_page = StoryBookGoToPage()
    close_tool = StoryBookClose()
    deps = MagicMock()

    pages_visited = []
    results = []
    interrupted_pages = set()

    # Parse interruption target
    interrupt_target = None
    if behavior and behavior.startswith("interrupt_on_page_"):
        interrupt_target = int(behavior.split("_")[-1])

    # Start reading from page 1
    next_page = 1
    max_iterations = num_pages * 3 + 5
    iterations = 0

    while next_page is not None:
        iterations += 1
        if iterations > max_iterations:
            raise RuntimeError("simulation exceeded max iterations — likely infinite loop")

        result = await go_to_page(deps, page=next_page)
        pages_visited.append(result["page"])
        results.append(result)

        # Simulate interruption: user speaks → auto-advance cancelled
        if interrupt_target == result["page"] and result["page"] not in interrupted_pages:
            interrupted_pages.add(result["page"])
            # After interruption, LLM resumes on the NEXT page
            # (user says "continue" → LLM calls go_to_page for next_page)
            if result["next_page"] is not None:
                next_page = result["next_page"]
            elif result["is_last_page"]:
                # Interrupted on last page; after user resumes, system auto-closes
                close_result = await close_tool(deps)
                results.append(close_result)
                next_page = None
            continue

        # System auto-advance: use next_page from result
        if result.get("is_last_page"):
            # System auto-closes
            close_result = await close_tool(deps)
            results.append(close_result)
            next_page = None
        else:
            next_page = result.get("next_page")

    final_status = store.story.status if store.story else "closed"
    return pages_visited, final_status, results


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_store():
    """Reset the StoryStore singleton between tests."""
    StoryStore._instance = None
    yield
    StoryStore._instance = None


@pytest.fixture
def tool():
    return StoryBookGoToPage()


@pytest.fixture
def deps():
    return MagicMock()


# ---------------------------------------------------------------------------
# Integration tests — full session simulations
# ---------------------------------------------------------------------------

class TestHappyPathFullReadThrough:
    """3-page story read from start to finish."""

    @pytest.mark.asyncio
    async def test_all_pages_visited_in_order(self):
        pages_visited, status, _ = await simulate_story_session(3)
        assert pages_visited == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_story_closed_at_end(self):
        _, status, _ = await simulate_story_session(3)
        assert status == "closed"

    @pytest.mark.asyncio
    async def test_next_page_correct_at_each_step(self):
        _, _, results = await simulate_story_session(3)
        # go_to_page results (first 3), then close result
        assert results[0]["next_page"] == 2
        assert results[1]["next_page"] == 3
        assert results[2]["next_page"] is None

    @pytest.mark.asyncio
    async def test_is_last_page_flag(self):
        _, _, results = await simulate_story_session(3)
        assert results[0]["is_last_page"] is False
        assert results[1]["is_last_page"] is False
        assert results[2]["is_last_page"] is True

    @pytest.mark.asyncio
    async def test_instruction_has_no_tool_commands(self):
        """Instructions should NOT contain tool call commands (system handles advance)."""
        _, _, results = await simulate_story_session(3)
        for r in results[:3]:  # go_to_page results
            assert "story_book_go_to_page" not in r.get("instruction", "")
            assert "story_book_close" not in r.get("instruction", "")

    @pytest.mark.asyncio
    async def test_close_result_shape(self):
        _, _, results = await simulate_story_session(3)
        close_result = results[-1]
        assert close_result["status"] == "closed"


class TestSinglePageStory:
    """Edge case: story with only one page."""

    @pytest.mark.asyncio
    async def test_single_page_visited(self):
        pages_visited, _, _ = await simulate_story_session(1)
        assert pages_visited == [1]

    @pytest.mark.asyncio
    async def test_single_page_closes(self):
        _, status, _ = await simulate_story_session(1)
        assert status == "closed"

    @pytest.mark.asyncio
    async def test_single_page_is_last(self):
        _, _, results = await simulate_story_session(1)
        assert results[0]["is_last_page"] is True
        assert results[0]["next_page"] is None


class TestInterruptionMidStory:
    """User interrupts during narration — auto-advance cancelled, then resumes."""

    @pytest.mark.asyncio
    async def test_all_pages_still_visited(self):
        pages_visited, _, _ = await simulate_story_session(
            3, behavior="interrupt_on_page_2"
        )
        assert pages_visited == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_story_closes_after_interruption(self):
        _, status, _ = await simulate_story_session(
            3, behavior="interrupt_on_page_2"
        )
        assert status == "closed"

    @pytest.mark.asyncio
    async def test_interrupt_on_first_page(self):
        pages_visited, status, _ = await simulate_story_session(
            3, behavior="interrupt_on_page_1"
        )
        assert pages_visited == [1, 2, 3]
        assert status == "closed"

    @pytest.mark.asyncio
    async def test_interrupt_on_last_page(self):
        pages_visited, status, _ = await simulate_story_session(
            3, behavior="interrupt_on_page_3"
        )
        assert pages_visited == [1, 2, 3]
        assert status == "closed"


class TestLoadSavedStory:
    """Load a pre-built story via StoryStore.load_story and read through."""

    @pytest.mark.asyncio
    async def test_loaded_story_full_read(self):
        pages_visited, status, _ = await simulate_story_session(
            3, use_load=True
        )
        assert pages_visited == [1, 2, 3]
        assert status == "closed"

    @pytest.mark.asyncio
    async def test_loaded_story_status_transitions(self):
        store = StoryStore.get()
        pages = [StoryPage(text=f"第{i}頁") for i in range(2)]
        story = Story(
            id=str(uuid.uuid4()),
            title="saved",
            pages=pages,
            status="ready",
        )
        store.load_story(story)
        assert store.story.status == "ready"

        tool = StoryBookGoToPage()
        deps = MagicMock()
        await tool(deps, page=1)
        assert store.story.status == "reading"

        close = StoryBookClose()
        await close(deps)
        # close_story sets status to "closed" then clears story
        assert store.story is None


# ---------------------------------------------------------------------------
# Tool result contract checks
# ---------------------------------------------------------------------------

class TestToolResultContract:
    """Verify the shape and values returned by story_book_go_to_page."""

    @pytest.mark.asyncio
    async def test_first_page_returns_next_page(self, tool, deps):
        store = StoryStore.get()
        story = store.create_story("t")
        store.set_story_ready(story.id, [StoryPage(text=f"p{i}") for i in range(3)])

        result = await tool(deps, page=1)
        assert result["status"] == "ok"
        assert result["page"] == 1
        assert result["next_page"] == 2
        assert result["is_last_page"] is False

    @pytest.mark.asyncio
    async def test_last_page_returns_null_next_page(self, tool, deps):
        store = StoryStore.get()
        story = store.create_story("t")
        store.set_story_ready(story.id, [StoryPage(text=f"p{i}") for i in range(3)])

        result = await tool(deps, page=3)
        assert result["status"] == "ok"
        assert result["next_page"] is None
        assert result["is_last_page"] is True

    @pytest.mark.asyncio
    async def test_page_text_included(self, tool, deps):
        store = StoryStore.get()
        story = store.create_story("t")
        store.set_story_ready(story.id, [StoryPage(text="內容ABC")])

        result = await tool(deps, page=1)
        assert result["page_text"] == "內容ABC"

    @pytest.mark.asyncio
    async def test_no_story_returns_error(self, tool, deps):
        StoryStore.get()
        result = await tool(deps, page=1)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_generating_story_returns_error(self, tool, deps):
        store = StoryStore.get()
        store.create_story("still generating")
        # status is "generating" — pages not set yet
        result = await tool(deps, page=1)
        assert "error" in result
