"""Regression tests for LocalStream.clear_audio_queue (barge-in) on SDK 1.8.

Verifies the correct flush method is called per backend without a real robot.
Note: in SDK 1.8 ``MediaBackend.DEFAULT``/``DEFAULT_NO_VIDEO`` are *aliases*
(for LOCAL / GSTREAMER_NO_VIDEO), so the old code did not crash; the change
branches on the canonical members so every backend (incl. GSTREAMER_NO_VIDEO,
WEBRTC, SOUNDDEVICE_*) flushes correctly.
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


def test_gstreamer_uses_clear_player():
    stream = _stream(MediaBackend.GSTREAMER)
    stream.clear_audio_queue()
    stream._robot.media.audio.clear_player.assert_called_once()
    stream._robot.media.audio.clear_output_buffer.assert_not_called()


def test_gstreamer_no_video_uses_clear_player():
    stream = _stream(MediaBackend.GSTREAMER_NO_VIDEO)
    stream.clear_audio_queue()
    stream._robot.media.audio.clear_player.assert_called_once()


@pytest.mark.parametrize(
    "backend",
    [MediaBackend.LOCAL, MediaBackend.SOUNDDEVICE_OPENCV, MediaBackend.WEBRTC],
)
def test_non_gstreamer_uses_clear_output_buffer(backend):
    stream = _stream(backend)
    stream.clear_audio_queue()
    stream._robot.media.audio.clear_output_buffer.assert_called_once()
    stream._robot.media.audio.clear_player.assert_not_called()


def test_none_audio_does_not_crash():
    stream = _stream(MediaBackend.LOCAL, audio=None)
    # must not raise even though there is no audio backend
    stream.clear_audio_queue()


def test_default_aliases_resolve_to_canonical_members():
    # Documents the SDK 1.8 reality: DEFAULT/DEFAULT_NO_VIDEO are aliases, and
    # our barge-in branches on the canonical members they alias.
    assert MediaBackend.DEFAULT is MediaBackend.LOCAL
    assert MediaBackend.DEFAULT_NO_VIDEO is MediaBackend.GSTREAMER_NO_VIDEO
