"""Pitch-preserving speech slowdown for young children (WSOLA time-stretch).

Realtime backends don't expose a speaking-rate knob (verified: Gemini Live's
``SpeechConfig`` only has ``voice_config``/``language_code``/
``multi_speaker_voice_config``) and prompt instructions drift, so to slow the
robot's speech by an exact factor *without* the chipmunk pitch shift that plain
resampling causes, we time-stretch the output audio.

We use **WSOLA** (Waveform Similarity Overlap-Add): like OLA, but each frame's
position is nudged within a small search window to best line up with the natural
continuation of the previous frame, which removes most of the warble/phasiness
plain OLA produces.  Same sample rate, more samples, pitch preserved.

Configured via ``SPEECH_SLOWDOWN`` (1.0 = off, passthrough).  Stateful so it runs
on the streamed chunks of a live response; output is clipped to [-1, 1].
"""

from __future__ import annotations
import logging

import numpy as np
from numpy.typing import NDArray


logger = logging.getLogger(__name__)

_MIN, _MAX = 1.0, 2.5


def get_speech_slowdown() -> float:
    """Read and clamp the configured slowdown factor (1.0 = no change)."""
    from reachy_mini_conversation_app.config import config

    try:
        factor = float(getattr(config, "SPEECH_SLOWDOWN", 1.0))
    except (TypeError, ValueError):
        return 1.0
    if factor < _MIN:
        return _MIN
    return min(factor, _MAX)


class TimeStretcher:
    """Streaming WSOLA time-stretch (slows audio, keeps pitch).

    ``factor`` > 1.0 lengthens/slows audio.  Hann windows at 50% synthesis
    overlap; the analysis hop is shrunk by ``factor`` so frames are reused.  Each
    frame is shifted within ``±search`` samples to maximize waveform similarity
    with the previous frame's natural continuation (the WSOLA step).
    """

    def __init__(self, factor: float, frame: int = 1024, search: int = 128) -> None:
        """Create a stretcher for ``factor`` using ``frame``-sample Hann windows."""
        self.factor = max(1.0, float(factor))
        self.frame = int(frame)
        self.syn_hop = self.frame // 2
        self.ana_hop = max(1, int(round(self.syn_hop / self.factor)))
        self.search = int(search)
        self._win = np.hanning(self.frame).astype(np.float32)
        self._buf: NDArray[np.float32] = np.zeros(0, dtype=np.float32)
        self._read = 0
        self._template: NDArray[np.float32] | None = None
        self._acc: NDArray[np.float32] = np.zeros(0, dtype=np.float32)

    def reset(self) -> None:
        """Drop buffered input, template and synthesis tail (e.g. on barge-in)."""
        self._buf = np.zeros(0, dtype=np.float32)
        self._read = 0
        self._template = None
        self._acc = np.zeros(0, dtype=np.float32)

    def _best_offset(self, center: int) -> int:
        """Return the frame start near ``center`` most similar to the template."""
        max_start = self._buf.shape[0] - self.frame
        lo = max(0, center - self.search)
        hi = min(max_start, center + self.search)
        if self._template is None or hi <= lo:
            return min(max(center, 0), max(0, max_start))
        t = self._template
        t_norm = float(np.linalg.norm(t)) + 1e-6
        best_k, best_score = lo, -1e30
        for k in range(lo, hi + 1):
            seg = self._buf[k:k + self.frame]
            score = float(np.dot(seg, t)) / (float(np.linalg.norm(seg)) + 1e-6) / t_norm
            if score > best_score:
                best_score, best_k = score, k
        return best_k

    def process(self, x: NDArray[np.float32]) -> NDArray[np.float32]:
        """Stretch a chunk; returns the finalized output samples so far.

        Accepts mono audio shaped (N,) or (N, 1) — the Gemini backend emits the
        latter, which used to crash concatenation. Output keeps the input shape.
        """
        arr = np.asarray(x, dtype=np.float32)
        if self.factor <= 1.0:
            return arr
        was_2d = arr.ndim == 2
        arr = arr.ravel()
        if arr.size:
            self._buf = np.concatenate([self._buf, arr])

        out_pieces = []
        # Need room for the search window, the frame, and the template lookahead.
        while self._read + self.search + self.frame + self.syn_hop <= self._buf.shape[0]:
            pos = self._best_offset(self._read)
            seg = self._buf[pos:pos + self.frame] * self._win
            if self._acc.shape[0] < self.frame:
                pad = np.zeros(self.frame - self._acc.shape[0], dtype=np.float32)
                self._acc = np.concatenate([self._acc, pad])
            self._acc[:self.frame] += seg
            out_pieces.append(self._acc[:self.syn_hop].copy())
            self._acc = self._acc[self.syn_hop:]
            # The natural continuation of the chosen frame guides the next match.
            self._template = self._buf[pos + self.syn_hop:pos + self.syn_hop + self.frame].copy()
            self._read += self.ana_hop
            # Keep the buffer small: we never search before read-search next time.
            drop = max(0, self._read - self.search)
            if drop:
                self._buf = self._buf[drop:]
                self._read -= drop

        if not out_pieces:
            return np.zeros((0, 1), dtype=np.float32) if was_2d else np.zeros(0, dtype=np.float32)
        out = np.clip(np.concatenate(out_pieces), -1.0, 1.0)
        return out.reshape(-1, 1) if was_2d else out
