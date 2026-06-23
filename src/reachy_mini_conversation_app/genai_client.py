"""Shared google-genai client factory.

Returns a client wired for either Vertex AI (ADC + project/location) or
AI Studio (API key), selected by ``config.GOOGLE_GENAI_USE_VERTEXAI``. Used by
the Gemini Live handler, the storyteller, and memory consolidation so the auth
choice lives in exactly one place.
"""

from typing import Any, Optional

from reachy_mini_conversation_app.config import config


def make_genai_client(timeout_ms: Optional[int] = None, retry: bool = False) -> Any:
    """Create a ``google.genai`` client for the configured backend.

    Args:
        timeout_ms: optional HTTP timeout in milliseconds.
        retry: enable HTTP retries on transient (429/5xx) errors.

    """
    from google import genai
    from google.genai import types

    http_kwargs: dict[str, Any] = {}
    if timeout_ms is not None:
        http_kwargs["timeout"] = int(timeout_ms)
    if retry:
        http_kwargs["retry_options"] = types.HttpRetryOptions(
            attempts=4,
            initial_delay=2.0,
            max_delay=16.0,
            exp_base=2.0,
            http_status_codes=[429, 500, 502, 503, 504],
        )
    http_options = types.HttpOptions(**http_kwargs) if http_kwargs else None

    if config.GOOGLE_GENAI_USE_VERTEXAI:
        kwargs: dict[str, Any] = {
            "vertexai": True,
            "project": config.GOOGLE_CLOUD_PROJECT,
            "location": config.GOOGLE_CLOUD_LOCATION,
        }
    else:
        kwargs = {"api_key": config.GEMINI_API_KEY}

    if http_options is not None:
        kwargs["http_options"] = http_options
    return genai.Client(**kwargs)
