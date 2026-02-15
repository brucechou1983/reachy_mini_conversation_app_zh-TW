"""Web search tool using the Tavily REST API.

Only available when ``TAVILY_API_KEY`` is configured (via .env, environment, or
the settings UI).  Uses ``httpx`` (already a transitive dependency via
``openai``) to avoid pulling in the heavyweight ``tavily-python`` SDK.
"""

import logging
from typing import Any, Dict

import httpx

from reachy_mini_conversation_app.config import config
from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies


logger = logging.getLogger(__name__)

TAVILY_SEARCH_URL = "https://api.tavily.com/search"


class WebSearch(Tool):
    """Search the web for current information about a topic."""

    name = "web_search"
    description = (
        "Search the web for current information. Use this when the user asks about "
        "recent events, facts you are unsure about, or anything that may require "
        "up-to-date knowledge."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query to look up on the web.",
            },
        },
        "required": ["query"],
    }

    def is_available(self) -> bool:
        key = getattr(config, "TAVILY_API_KEY", None)
        return bool(key and str(key).strip())

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        query = kwargs.get("query", "")
        if not query:
            return {"error": "query is required"}

        api_key = getattr(config, "TAVILY_API_KEY", None)
        if not api_key or not str(api_key).strip():
            return {"error": "TAVILY_API_KEY is not configured"}

        logger.info("Tool call: web_search query=%r", query)

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    TAVILY_SEARCH_URL,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "query": query,
                        "search_depth": "basic",
                        "max_results": 3,
                    },
                )

                if response.status_code != 200:
                    logger.warning(
                        "Tavily API error: status=%d body=%s",
                        response.status_code,
                        response.text[:200],
                    )
                    return {"error": f"Search failed (HTTP {response.status_code})"}

                data = response.json()
                results = [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "content": r.get("content", ""),
                    }
                    for r in data.get("results", [])
                ]
                return {"results": results}

        except httpx.TimeoutException:
            logger.warning("Tavily API timeout for query=%r", query)
            return {"error": "Search request timed out"}
        except Exception as e:
            logger.exception("Tavily API error: %s", e)
            return {"error": f"Search failed: {type(e).__name__}: {e}"}
