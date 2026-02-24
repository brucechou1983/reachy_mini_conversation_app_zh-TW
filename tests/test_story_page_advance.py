"""Integration tests for LLM-driven page advance logic.

Simulates the full dispatch cycle: tool returns result with instruction →
mock LLM parses instruction → decides next tool call → repeat.
This validates the contract between tool results and LLM behavior.
"""

import re
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
# Mock LLM decision logic
# ---------------------------------------------------------------------------

def mock_llm_decide(result, behavior="normal", pages_visited=None):
    """Parse a tool result's instruction to decide the next action.

    Simulates what a real LLM would do: read the instruction text and call
    the appropriate tool.  Returns ``(tool_name, kwargs)`` or ``None``.
    """
    instruction = result.get("instruction", "")

    # Interruption behaviour: on the target page, the LLM "answers a
    # question" instead of advancing — it returns None for one turn,
    # and the caller is expected to call again.
    if behavior and behavior.startswith("interrupt_on_page_"):
        target = int(behavior.split("_")[-1])
        if (
            result.get("page") == target
            and pages_visited is not None
            and pages_visited.count(target) == 1  # first visit only
        ):
            return "interrupted", {}

    # Normal flow — follow the instruction text
    m = re.search(r"story_book_go_to_page\(page=(\d+)\)", instruction)
    if m:
        return "go_to_page", {"page": int(m.group(1))}

    if "story_book_close" in instruction:
        return "close", {}

    return None


async def simulate_story_session(num_pages, behavior="normal", use_load=False):
    """Simulate a complete story reading session.

    Parameters
    ----------
    num_pages : int
        Number of pages in the generated story.
    behavior : str
        MockLLM behaviour mode (``"normal"`` or ``"interrupt_on_page_N"``).
    use_load : bool
        If True, use ``StoryStore.load_story`` instead of create + set_ready.

    Returns
    -------
    tuple
        (pages_visited, story_status, results) — the list of page indices
        visited, final story status, and all intermediate tool results.
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
    current_action = ("go_to_page", {"page": 1})

    max_iterations = num_pages * 3 + 5  # safety guard
    iterations = 0

    while current_action is not None:
        iterations += 1
        if iterations > max_iterations:
            raise RuntimeError("simulation exceeded max iterations — likely infinite loop")

        tool_name, kwargs = current_action

        if tool_name == "go_to_page":
            result = await go_to_page(deps, **kwargs)
            pages_visited.append(result["page"])
            results.append(result)
            decision = mock_llm_decide(result, behavior, pages_visited)
            if decision is None:
                current_action = None
            elif decision[0] == "interrupted":
                # LLM answered a question; on the *next* response.create it
                # re-reads the same instruction and follows it this time.
                decision2 = mock_llm_decide(result, behavior="normal")
                current_action = decision2
            else:
                current_action = decision
        elif tool_name == "close":
            result = await close_tool(deps)
            results.append(result)
            current_action = None

    # Capture status before store.close_story sets it to None
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
    async def test_instruction_drives_correct_tool(self):
        _, _, results = await simulate_story_session(3)
        # Pages 0 & 1 instruct go_to_page
        assert "story_book_go_to_page" in results[0]["instruction"]
        assert "story_book_go_to_page" in results[1]["instruction"]
        # Page 2 (last) instructs close
        assert "story_book_close" in results[2]["instruction"]
        assert "story_book_go_to_page" not in results[2]["instruction"]

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
    async def test_single_page_instruction_says_close(self):
        _, _, results = await simulate_story_session(1)
        assert "story_book_close" in results[0]["instruction"]
        assert results[0]["is_last_page"] is True
        assert results[0]["next_page"] is None


class TestInterruptionMidStory:
    """LLM gets interrupted on page 2 (answers a question), then resumes."""

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
# Tool result contract checks (expanded from original unit tests)
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
