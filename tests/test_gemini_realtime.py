"""Hardware-free tests for the Gemini Live handler (no live session)."""

import asyncio
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


def test_live_config_uses_default_sensitivity_no_self_interrupt():
    """We must NOT force a sensitivity override — Gemini's default (like OpenAI's
    server VAD) avoids interrupting the robot on its own echo. Only the silence
    window is tuned for kids."""
    h = GeminiRealtimeHandler(MagicMock())
    aad = h._build_live_config("you are a robot", [])["realtime_input_config"][
        "automatic_activity_detection"
    ]
    assert "start_of_speech_sensitivity" not in aad
    assert "end_of_speech_sensitivity" not in aad


def test_live_config_is_patient_about_end_of_turn():
    """A child's mid-phrase pause must not split the turn (regression: "等一下"
    answered as "等" then "一下"). We rely on an explicit silence window."""
    h = GeminiRealtimeHandler(MagicMock())
    aad = h._build_live_config("you are a robot", [])["realtime_input_config"][
        "automatic_activity_detection"
    ]
    assert aad["silence_duration_ms"] >= 700   # room for slow speech / pauses
    assert aad["prefix_padding_ms"] >= 0


def test_live_config_vad_timing_is_env_tunable(monkeypatch):
    from reachy_mini_conversation_app.config import config as cfg

    monkeypatch.setattr(cfg, "GEMINI_VAD_SILENCE_MS", "1500")
    monkeypatch.setattr(cfg, "GEMINI_VAD_PREFIX_MS", "250")
    h = GeminiRealtimeHandler(MagicMock())
    aad = h._build_live_config("x", [])["realtime_input_config"]["automatic_activity_detection"]
    assert aad["silence_duration_ms"] == 1500
    assert aad["prefix_padding_ms"] == 250


def test_live_config_vad_timing_falls_back_on_bad_value(monkeypatch):
    from reachy_mini_conversation_app.config import config as cfg

    monkeypatch.setattr(cfg, "GEMINI_VAD_SILENCE_MS", "not-a-number")
    h = GeminiRealtimeHandler(MagicMock())
    aad = h._build_live_config("x", [])["realtime_input_config"]["automatic_activity_detection"]
    assert aad["silence_duration_ms"] == 900


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


def _audio_model_turn():
    """A model_turn server_content carrying one PCM audio chunk."""
    import numpy as np

    inline = type("_I", (), {"mime_type": "audio/pcm", "data": np.zeros(160, dtype=np.int16).tobytes()})()
    part = type("_P", (), {"inline_data": inline})()
    return _server_content(model_turn=type("_MT", (), {"parts": [part]})())


@pytest.mark.asyncio
async def test_suppress_window_drops_aborted_turn_audio():
    """While muted (just after a client barge-in), incoming chunks are dropped.

    Regression: BARGE_IN_LOCAL flushed the player but Gemini kept streaming the
    aborted turn, whose chunks resumed playback a beat later. They must be muted.
    """
    h = GeminiRealtimeHandler(MagicMock())
    h._mute_until = asyncio.get_event_loop().time() + 5.0  # inside the mute window

    await h._handle_server_content(_audio_model_turn())

    assert h.output_queue.empty()       # chunk dropped, not queued for playback
    assert h._model_speaking is False   # and we did NOT re-arm "speaking"


@pytest.mark.asyncio
async def test_audio_plays_again_once_mute_window_lapses():
    h = GeminiRealtimeHandler(MagicMock())
    h._mute_until = 0.0  # not muted

    await h._handle_server_content(_audio_model_turn())

    assert not h.output_queue.empty()
    assert h._model_speaking is True


@pytest.mark.asyncio
async def test_heard_child_barge_in_flushes_without_arming_mute():
    """Heard-child barge-in flushes, but must NOT arm the mute window — the server
    manages that turn, and muting here could swallow the start of the reply."""
    h = GeminiRealtimeHandler(MagicMock())
    h._model_speaking = True
    flushed = {"n": 0}
    h._clear_queue = lambda: flushed.__setitem__("n", flushed["n"] + 1)

    sc = _server_content(input_transcription=type("_T", (), {"text": "停"})())
    await h._handle_server_content(sc)

    assert flushed["n"] == 1          # playback flushed
    assert h._mute_until == 0.0       # but no mute window (local path only)


@pytest.mark.asyncio
async def test_server_interrupted_clears_mute_window():
    """A server 'interrupted' means the turn already stopped — let the next play."""
    h = GeminiRealtimeHandler(MagicMock())
    h._clear_queue = lambda: None
    h._mute_until = asyncio.get_event_loop().time() + 5.0  # a prior client mute

    await h._handle_server_content(_server_content(interrupted=True))

    assert h._mute_until == 0.0


@pytest.mark.asyncio
async def test_turn_complete_clears_mute_window():
    h = GeminiRealtimeHandler(MagicMock())
    h._mute_until = asyncio.get_event_loop().time() + 5.0

    await h._handle_server_content(_server_content(turn_complete=True))

    assert h._mute_until == 0.0


@pytest.mark.asyncio
async def test_local_barge_in_arms_mute_but_server_interrupt_does_not():
    h = GeminiRealtimeHandler(MagicMock())
    h._clear_queue = lambda: None

    h._barge_in(suppress=True)
    assert h._mute_until > asyncio.get_event_loop().time()

    h._barge_in()  # server-style: no suppression
    assert h._mute_until == 0.0


def test_live_config_uses_configured_voice():
    """Voice comes from config.GEMINI_VOICE (default Leda)."""
    from reachy_mini_conversation_app.config import config

    h = GeminiRealtimeHandler(MagicMock())
    cfg = h._build_live_config("sys", [])
    voice = cfg["speech_config"]["voice_config"]["prebuilt_voice_config"]["voice_name"]
    assert voice == config.GEMINI_VOICE
    assert config.GEMINI_VOICE == "Leda"


@pytest.mark.asyncio
async def test_local_barge_in_triggers_on_sustained_loud_speech():
    h = GeminiRealtimeHandler(MagicMock())
    h._local_barge_in = True
    h._barge_level = 0.05
    h._model_speaking = True
    h._model_speech_start = asyncio.get_event_loop().time() - 1.0  # past grace
    cleared = {"n": 0}
    h._clear_queue = lambda: cleared.__setitem__("n", cleared["n"] + 1)

    loud = h._frame_level(np.full(320, 3000, dtype=np.int16))  # ≈ 0.09 > 0.05
    for _ in range(h._BARGE_SUSTAIN):
        h._maybe_local_barge_in(loud)

    assert cleared["n"] >= 1
    assert h._model_speaking is False


@pytest.mark.asyncio
async def test_local_barge_in_ignores_quiet_mic():
    h = GeminiRealtimeHandler(MagicMock())
    h._local_barge_in = True
    h._barge_level = 0.05
    h._model_speaking = True
    h._model_speech_start = asyncio.get_event_loop().time() - 1.0
    cleared = {"n": 0}
    h._clear_queue = lambda: cleared.__setitem__("n", cleared["n"] + 1)

    quiet = h._frame_level(np.full(320, 100, dtype=np.int16))  # ≈ 0.003
    for _ in range(10):
        h._maybe_local_barge_in(quiet)
    assert cleared["n"] == 0


@pytest.mark.asyncio
async def test_local_barge_in_respects_grace_period():
    h = GeminiRealtimeHandler(MagicMock())
    h._local_barge_in = True
    h._barge_level = 0.05
    h._model_speaking = True
    h._model_speech_start = asyncio.get_event_loop().time()  # just started -> in grace
    cleared = {"n": 0}
    h._clear_queue = lambda: cleared.__setitem__("n", cleared["n"] + 1)

    loud = h._frame_level(np.full(320, 3000, dtype=np.int16))
    for _ in range(5):
        h._maybe_local_barge_in(loud)
    assert cleared["n"] == 0
