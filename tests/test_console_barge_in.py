"""Regression tests for LocalStream.clear_audio_queue (barge-in).

These pin the fix for the bug where barge-in never actually silenced the robot:
``clear_output_buffer()`` is *deprecated and a no-op* on every current SDK audio
backend, while ``clear_player()`` is the real flush (and on WEBRTC also tells the
daemon to drop the speaker queue). The old code gated on ``media.backend ==
GSTREAMER*`` — enums the SDK resolves to LOCAL — so the check was always False and
we silently called the no-op, leaving the robot talking through barge-in.

So: every real backend MUST call ``clear_player()``; ``clear_output_buffer()`` is
only a fallback for ancient SDKs that lack ``clear_player()`` entirely.
"""

from unittest.mock import MagicMock

import pytest

from reachy_mini.media.media_manager import MediaBackend
from reachy_mini_conversation_app.console import LocalStream


def _stream(backend, *, audio=...) -> LocalStream:
    robot = MagicMock()
    robot.media.backend = backend
    robot.media.audio = MagicMock() if audio is ... else audio
    return LocalStream(MagicMock(), robot)


@pytest.mark.parametrize(
    "backend",
    [
        MediaBackend.LOCAL,
        MediaBackend.WEBRTC,
        MediaBackend.GSTREAMER,
        MediaBackend.GSTREAMER_NO_VIDEO,
        MediaBackend.SOUNDDEVICE_OPENCV,
    ],
)
def test_every_backend_uses_clear_player(backend):
    # Regardless of backend, the real flush (clear_player) must be called and the
    # deprecated no-op (clear_output_buffer) must NOT be.
    stream = _stream(backend)
    stream.clear_audio_queue()
    stream._robot.media.audio.clear_player.assert_called_once()
    stream._robot.media.audio.clear_output_buffer.assert_not_called()


def test_falls_back_to_clear_output_buffer_when_no_clear_player():
    # Ancient SDK without clear_player(): we must fall back to the (then-real)
    # clear_output_buffer() rather than do nothing.
    audio = MagicMock(spec=["clear_output_buffer"])
    stream = _stream(MediaBackend.LOCAL, audio=audio)
    stream.clear_audio_queue()
    audio.clear_output_buffer.assert_called_once()


def test_resets_stretcher_on_flush():
    stream = _stream(MediaBackend.LOCAL)
    stream._stretcher = MagicMock()
    stream.clear_audio_queue()
    stream._stretcher.reset.assert_called_once()


def test_none_audio_does_not_crash():
    stream = _stream(MediaBackend.LOCAL, audio=None)
    # must not raise even though there is no audio backend
    stream.clear_audio_queue()
