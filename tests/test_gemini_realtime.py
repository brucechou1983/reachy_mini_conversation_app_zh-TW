"""Hardware-free tests for the Gemini Live handler (no live session)."""

from unittest.mock import MagicMock

import numpy as np
import pytest

import reachy_mini_conversation_app.gemini_realtime as gm
from reachy_mini_conversation_app.gemini_realtime import GeminiRealtimeHandler
from reachy_mini_conversation_app.conversation_handler import ConversationHandler


def _sine(n: int, sr: int, freq: int = 440) -> np.ndarray:
    return (0.2 * np.sin(2 * np.pi * freq * np.arange(n) / sr)).astype(np.float32)


@pytest.mark.asyncio
async def test_is_conversation_handler():
    h = GeminiRealtimeHandler(MagicMock())
    assert isinstance(h, ConversationHandler)
    # input/output sample rates match Gemini Live requirements
    assert h.input_sample_rate == 16000
    assert h.output_sample_rate == 24000


@pytest.mark.asyncio
async def test_tool_spec_conversion(monkeypatch):
    monkeypatch.setattr(
        gm,
        "get_tool_specs",
        lambda: [
            {"type": "function", "name": "dance", "description": "d", "parameters": {"type": "object", "properties": {}}},
            {"type": "function", "name": "move_head", "description": "m", "parameters": {"type": "object", "properties": {}}},
            {"type": "other", "name": "ignored"},
        ],
    )
    h = GeminiRealtimeHandler(MagicMock())
    tools = h._convert_tool_specs_to_gemini_format()
    assert len(tools) == 1
    decls = tools[0]["function_declarations"]
    assert [d["name"] for d in decls] == ["dance", "move_head"]  # non-function entry dropped
    assert decls[0]["description"] == "d"


@pytest.mark.asyncio
async def test_copy_returns_fresh_instance():
    h = GeminiRealtimeHandler(MagicMock(), gradio_mode=True, instance_path="/tmp/x")
    h2 = h.copy()
    assert isinstance(h2, GeminiRealtimeHandler)
    assert h2 is not h
    assert h2.gradio_mode is True
    assert h2.instance_path == "/tmp/x"


# --- Audio format conversion (regression for Live 1007 "invalid audio format") ---


def test_to_gemini_pcm_stereo_48k_becomes_mono_16k_int16():
    """Stereo float @ 48 kHz must be downmixed, resampled to 16 kHz, cast to int16."""
    h = GeminiRealtimeHandler(MagicMock())
    n = 4800  # 0.1 s @ 48 kHz
    sig = _sine(n, 48000)
    stereo = np.stack([sig, sig], axis=1)  # (n, 2), channels-last

    out = h._to_gemini_pcm((48000, stereo))

    assert isinstance(out, bytes)
    assert len(out) % 2 == 0  # whole int16 samples
    arr = np.frombuffer(out, dtype=np.int16)
    assert arr.ndim == 1  # mono
    assert abs(len(arr) - 1600) <= 2  # 48k -> 16k => ~1600 samples
    assert arr.any()  # not silence


def test_to_gemini_pcm_mono_16k_keeps_length():
    """Already-correct mono 16 kHz audio is only cast to int16 (no resample)."""
    h = GeminiRealtimeHandler(MagicMock())
    sig = _sine(1600, 16000, freq=220)

    arr = np.frombuffer(h._to_gemini_pcm((16000, sig)), dtype=np.int16)

    assert len(arr) == 1600
    assert arr.dtype == np.int16


def test_to_gemini_pcm_int16_stereo_column_downmix():
    """int16 stereo input is reduced to a single channel."""
    h = GeminiRealtimeHandler(MagicMock())
    left = (_sine(1600, 16000) * 32000).astype(np.int16)
    right = np.zeros(1600, dtype=np.int16)
    stereo = np.stack([left, right], axis=1)  # (1600, 2)

    arr = np.frombuffer(h._to_gemini_pcm((16000, stereo)), dtype=np.int16)

    assert len(arr) == 1600  # mono, no resample
    np.testing.assert_array_equal(arr, left)  # took channel 0, not the silent one


@pytest.mark.asyncio
async def test_receive_sends_int16_mono_16k_pcm():
    """receive() must hand Gemini raw s16le mono 16 kHz bytes, not the raw frame."""
    h = GeminiRealtimeHandler(MagicMock())
    sent: dict = {}

    class FakeSession:
        async def send_realtime_input(self, audio=None):
            sent["audio"] = audio

    h.session = FakeSession()
    stereo = np.stack([_sine(4800, 48000)] * 2, axis=1)  # stereo float 48 kHz

    await h.receive((48000, stereo))

    assert sent["audio"]["mime_type"] == "audio/pcm;rate=16000"
    assert isinstance(sent["audio"]["data"], bytes)  # raw bytes, not base64 str
    arr = np.frombuffer(sent["audio"]["data"], dtype=np.int16)
    assert abs(len(arr) - 1600) <= 2


@pytest.mark.asyncio
async def test_receive_without_session_is_noop():
    """No session -> drop the frame silently (no crash, no send)."""
    h = GeminiRealtimeHandler(MagicMock())
    h.session = None
    await h.receive((48000, np.zeros((10, 2), dtype=np.float32)))


@pytest.mark.asyncio
async def test_inject_user_text_sends_to_session():
    """inject_user_text forwards text to the Gemini live session."""
    h = GeminiRealtimeHandler(MagicMock())
    sent: dict = {}

    class FakeSession:
        async def send(self, input=None, end_of_turn=None):
            sent["input"] = input
            sent["end_of_turn"] = end_of_turn

    h.session = FakeSession()
    await h.inject_user_text("讀這個字", respond=True)
    assert sent["input"] == "讀這個字"
    assert sent["end_of_turn"] is True


@pytest.mark.asyncio
async def test_inject_user_text_without_session_is_noop():
    """No session -> inject is a safe no-op."""
    h = GeminiRealtimeHandler(MagicMock())
    h.session = None
    await h.inject_user_text("x")  # must not raise


@pytest.mark.asyncio
async def test_inject_camera_image_uses_video_not_deprecated_media():
    """Camera images must go via video=, not the deprecated media= (1007)."""
    import io as _io
    import base64 as _b64

    import PIL.Image

    h = GeminiRealtimeHandler(MagicMock())
    sent: dict = {}

    class FakeSession:
        async def send_realtime_input(self, **kwargs):
            sent.update(kwargs)

    h.session = FakeSession()
    buf = _io.BytesIO()
    PIL.Image.new("RGB", (2, 2), (10, 20, 30)).save(buf, format="PNG")
    b64 = _b64.b64encode(buf.getvalue()).decode()

    await h._inject_camera_image(b64)

    assert "video" in sent
    assert "media" not in sent
    assert isinstance(sent["video"], PIL.Image.Image)


def test_live_config_enables_barge_in():
    """The Live config must turn on interruption (START_OF_ACTIVITY_INTERRUPTS)."""
    from google.genai import types

    h = GeminiRealtimeHandler(MagicMock())
    cfg = h._build_live_config("you are a robot", [])
    ric = cfg["realtime_input_config"]
    assert ric["activity_handling"] == types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS
    aad = ric["automatic_activity_detection"]
    assert aad["disabled"] is False
    assert aad["start_of_speech_sensitivity"] == types.StartSensitivity.START_SENSITIVITY_HIGH


@pytest.mark.asyncio
async def test_drain_output_queue_empties_pending_audio():
    h = GeminiRealtimeHandler(MagicMock())
    for _ in range(5):
        h.output_queue.put_nowait((24000, "frame"))
    assert not h.output_queue.empty()
    h._drain_output_queue()
    assert h.output_queue.empty()


@pytest.mark.asyncio
async def test_interrupted_flushes_playback():
    """On a Gemini 'interrupted' signal, queued audio is dropped and the player flushed."""
    h = GeminiRealtimeHandler(MagicMock())
    h.output_queue.put_nowait((24000, "stale-audio"))
    cleared = {"n": 0}
    h._clear_queue = lambda: cleared.__setitem__("n", cleared["n"] + 1)

    class _SC:
        interrupted = True
        input_transcription = None
        output_transcription = None
        model_turn = None
        turn_complete = None

    await h._handle_server_content(_SC())

    assert h.output_queue.empty()       # queued speech dropped
    assert cleared["n"] == 1            # player flushed


def _server_content(**kw):
    """Build a fake server_content with all the attrs _handle_server_content reads."""
    defaults = {
        "input_transcription": None,
        "output_transcription": None,
        "model_turn": None,
        "turn_complete": None,
        "interrupted": None,
    }
    defaults.update(kw)
    return type("_SC", (), defaults)()


@pytest.mark.asyncio
async def test_client_barge_in_when_child_heard_while_speaking():
    """User transcript arriving while the robot talks must stop playback at once."""
    h = GeminiRealtimeHandler(MagicMock())
    h._model_speaking = True
    h.output_queue.put_nowait((24000, "stale-audio"))
    cleared = {"n": 0}
    h._clear_queue = lambda: cleared.__setitem__("n", cleared["n"] + 1)

    sc = _server_content(input_transcription=type("_T", (), {"text": "停"})())
    await h._handle_server_content(sc)

    assert h.output_queue.empty()       # queued speech dropped
    assert cleared["n"] == 1            # player flushed
    assert h._model_speaking is False


@pytest.mark.asyncio
async def test_no_barge_in_when_robot_is_not_speaking():
    """A user transcript while idle should not trigger a flush."""
    h = GeminiRealtimeHandler(MagicMock())
    h._model_speaking = False
    cleared = {"n": 0}
    h._clear_queue = lambda: cleared.__setitem__("n", cleared["n"] + 1)

    sc = _server_content(input_transcription=type("_T", (), {"text": "hello"})())
    await h._handle_server_content(sc)

    assert cleared["n"] == 0


@pytest.mark.asyncio
async def test_model_turn_marks_speaking():
    import numpy as np

    h = GeminiRealtimeHandler(MagicMock())
    inline = type("_I", (), {"mime_type": "audio/pcm", "data": np.zeros(160, dtype=np.int16).tobytes()})()
    part = type("_P", (), {"inline_data": inline})()
    sc = _server_content(model_turn=type("_MT", (), {"parts": [part]})())

    await h._handle_server_content(sc)

    assert h._model_speaking is True


def test_live_config_uses_configured_voice():
    """Voice comes from config.GEMINI_VOICE (default Leda)."""
    from reachy_mini_conversation_app.config import config

    h = GeminiRealtimeHandler(MagicMock())
    cfg = h._build_live_config("sys", [])
    voice = cfg["speech_config"]["voice_config"]["prebuilt_voice_config"]["voice_name"]
    assert voice == config.GEMINI_VOICE
    assert config.GEMINI_VOICE == "Leda"
