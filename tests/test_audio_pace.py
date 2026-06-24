"""Tests for the pitch-preserving speech slowdown (WSOLA, no hardware)."""

import numpy as np

from reachy_mini_conversation_app.audio_pace import TimeStretcher, get_speech_slowdown


def _sine(n, sr, freq=220.0):
    return (0.5 * np.sin(2 * np.pi * freq * np.arange(n) / sr)).astype(np.float32)


def _dominant_freq(x, sr):
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return float(np.fft.rfftfreq(len(x), 1.0 / sr)[int(np.argmax(spec))])


def test_factor_one_is_passthrough():
    st = TimeStretcher(1.0)
    x = _sine(2048, 24000)
    np.testing.assert_array_equal(st.process(x), x)


def test_slowdown_lengthens_audio():
    st = TimeStretcher(1.5)
    x = _sine(48000, 24000)
    out = st.process(x)
    assert abs(len(out) / len(x) - 1.5) < 0.06


def test_slowdown_2x():
    st = TimeStretcher(2.0)
    x = _sine(48000, 24000)
    out = st.process(x)
    assert abs(len(out) / len(x) - 2.0) < 0.06


def test_pitch_is_preserved():
    sr = 24000
    factor = 1.6
    st = TimeStretcher(factor)
    x = _sine(48000, sr, freq=300.0)
    dom = _dominant_freq(st.process(x), sr)
    # Pitch stays near 300 Hz, NOT shifted to 300/1.6 like plain resampling.
    assert abs(dom - 300.0) < 30.0
    assert abs(dom - 300.0) < abs(dom - 300.0 / factor)


def test_streaming_length_matches_whole():
    sr = 24000
    factor = 1.5
    x = _sine(36000, sr)
    whole = TimeStretcher(factor).process(x)
    st = TimeStretcher(factor)
    chunks = [st.process(x[i:i + 1000]) for i in range(0, len(x), 1000)]
    streamed = np.concatenate([c for c in chunks if c.size])
    # WSOLA picks slightly different offsets when chunked, but total length tracks.
    assert abs(len(streamed) - len(whole)) <= 4 * st.frame


def test_output_is_clipped_and_finite():
    st = TimeStretcher(1.7)
    out = st.process(_sine(24000, 24000))
    assert np.all(np.isfinite(out))
    assert np.max(np.abs(out)) <= 1.0


def test_reset_clears_state():
    st = TimeStretcher(1.5)
    st.process(_sine(8000, 24000))
    st.reset()
    assert st._buf.size == 0
    assert st._acc.size == 0
    assert st._template is None
    assert st._read == 0


def test_empty_input():
    st = TimeStretcher(1.5)
    assert st.process(np.zeros(0, dtype=np.float32)).size == 0


def test_wsola_matches_a_natural_continuation():
    """On a clean tone the search should keep waveform continuity (no NaN/spikes)."""
    st = TimeStretcher(1.5, frame=512, search=64)
    out = st.process(_sine(20000, 24000, freq=200.0))
    # No discontinuity blow-ups: consecutive-sample diff stays bounded.
    assert float(np.max(np.abs(np.diff(out)))) < 0.2


# --- config knob ---


def test_get_speech_slowdown_parses_and_clamps(monkeypatch):
    from reachy_mini_conversation_app.config import config

    monkeypatch.setattr(config, "SPEECH_SLOWDOWN", "1.5", raising=False)
    assert get_speech_slowdown() == 1.5
    monkeypatch.setattr(config, "SPEECH_SLOWDOWN", "9", raising=False)
    assert get_speech_slowdown() == 2.5  # clamp max
    monkeypatch.setattr(config, "SPEECH_SLOWDOWN", "0.3", raising=False)
    assert get_speech_slowdown() == 1.0  # never speed up
    monkeypatch.setattr(config, "SPEECH_SLOWDOWN", "garbage", raising=False)
    assert get_speech_slowdown() == 1.0  # invalid -> no change
