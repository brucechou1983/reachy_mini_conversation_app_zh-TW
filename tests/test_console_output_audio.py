"""Hardware-free tests for play_loop output-audio prep.

Regression for a ZeroDivisionError: the Gemini Live backend can emit a 0- or
1-sample audio chunk; resampling it to the speaker rate makes the target length
0 and scipy.signal.resample divides by zero, crashing the whole app.
"""

import numpy as np

from reachy_mini_conversation_app.console import _prepare_output_audio


def _sine(n: int, sr: int, freq: int = 440) -> np.ndarray:
    return (0.2 * np.sin(2 * np.pi * freq * np.arange(n) / sr)).astype(np.float32)


def test_empty_frame_returns_none():
    assert _prepare_output_audio(np.zeros(0, dtype=np.float32), 24000, 16000) is None


def test_subsample_frame_returns_none_not_zerodivision():
    # 1 sample @ 24k -> 16k => int(1 * 16000/24000) == 0. Must return None, not raise.
    out = _prepare_output_audio(np.array([0.5], dtype=np.float32), 24000, 16000)
    assert out is None


def test_resamples_when_rates_differ():
    sig = _sine(2400, 24000)  # 0.1 s @ 24 kHz (typical Gemini output rate)
    out = _prepare_output_audio(sig, 24000, 16000)
    assert out is not None
    assert out.dtype == np.float32
    assert abs(len(out) - 1600) <= 2  # 24k -> 16k


def test_passthrough_when_rates_equal():
    sig = _sine(1600, 16000, freq=220)
    out = _prepare_output_audio(sig, 16000, 16000)
    assert out is not None
    assert len(out) == 1600


def test_stereo_is_downmixed_to_mono():
    left = _sine(1600, 16000)
    right = np.zeros(1600, dtype=np.float32)
    stereo = np.stack([left, right], axis=1)  # (1600, 2)
    out = _prepare_output_audio(stereo, 16000, 16000)
    assert out is not None
    assert out.ndim == 1
    assert len(out) == 1600
