"""The play_emotion tool must constrain the emotion arg to a strict ``enum``.

Regression: the arg was a free string with valid names only in the description,
so the model hallucinated names (e.g. 'shaking1') and every such call failed.
"""

import reachy_mini_conversation_app.tools.play_emotion as pe


def test_emotion_schema_has_enum_when_available(monkeypatch):
    monkeypatch.setattr(pe, "get_available_emotion_names", lambda: ["happy1", "sad1"])
    schema = pe._emotion_param_schema()
    assert schema["type"] == "string"
    assert schema["enum"] == ["happy1", "sad1"]


def test_emotion_schema_omits_enum_when_unavailable(monkeypatch):
    # No library / empty list: degrade to a plain string (no empty enum, which
    # would forbid every value).
    monkeypatch.setattr(pe, "get_available_emotion_names", lambda: [])
    schema = pe._emotion_param_schema()
    assert "enum" not in schema
    assert schema["type"] == "string"


def test_available_names_empty_when_library_missing(monkeypatch):
    monkeypatch.setattr(pe, "EMOTION_AVAILABLE", False)
    assert pe.get_available_emotion_names() == []
