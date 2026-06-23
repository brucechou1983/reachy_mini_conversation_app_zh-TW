"""Tests for the shared google-genai client factory (Vertex vs AI Studio)."""

import pytest

import reachy_mini_conversation_app.genai_client as gc
from reachy_mini_conversation_app.config import config


class _FakeClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


@pytest.fixture()
def fake_genai(monkeypatch):
    from google import genai

    monkeypatch.setattr(genai, "Client", _FakeClient)
    return genai


def test_vertex_client(monkeypatch, fake_genai):
    monkeypatch.setattr(config, "GOOGLE_GENAI_USE_VERTEXAI", True)
    monkeypatch.setattr(config, "GOOGLE_CLOUD_PROJECT", "proj-x")
    monkeypatch.setattr(config, "GOOGLE_CLOUD_LOCATION", "us-central1")

    c = gc.make_genai_client()
    assert c.kwargs["vertexai"] is True
    assert c.kwargs["project"] == "proj-x"
    assert c.kwargs["location"] == "us-central1"
    assert "api_key" not in c.kwargs
    assert "http_options" not in c.kwargs  # none requested


def test_aistudio_client(monkeypatch, fake_genai):
    monkeypatch.setattr(config, "GOOGLE_GENAI_USE_VERTEXAI", False)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "ak-123")

    c = gc.make_genai_client()
    assert c.kwargs["api_key"] == "ak-123"
    assert "vertexai" not in c.kwargs


def test_timeout_and_retry_attach_http_options(monkeypatch, fake_genai):
    monkeypatch.setattr(config, "GOOGLE_GENAI_USE_VERTEXAI", False)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "ak")

    c = gc.make_genai_client(timeout_ms=30_000, retry=True)
    assert c.kwargs["http_options"] is not None
