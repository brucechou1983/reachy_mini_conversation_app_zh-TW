"""Tests for the take_photo tool — hardware-free.

Focus on the SDK-1.8 path: the media manager no longer exposes a direct
``camera`` object, so high-res capture is skipped and the tool falls back to
the buffered stream frame via ``camera_worker.get_latest_frame()``.
"""

from unittest.mock import MagicMock

import numpy as np
import pytest

from reachy_mini_conversation_app.tools.take_photo import TakePhoto


def _frame() -> np.ndarray:
    return np.zeros((4, 6, 3), dtype=np.uint8)


def _deps(*, with_camera_obj: bool, frame) -> MagicMock:
    deps = MagicMock()
    # media has NO usable direct camera object on SDK 1.8+ → getattr returns None
    deps.reachy_mini.media.camera = MagicMock() if with_camera_obj else None
    deps.head_wobbler = None
    deps.movement_manager.freeze.return_value = True
    cw = MagicMock()
    cw.is_head_tracking_enabled = False
    cw.get_latest_frame.return_value = frame
    deps.camera_worker = cw
    return deps


@pytest.mark.asyncio
async def test_returns_error_without_camera_worker(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "reachy_mini_conversation_app.tools.take_photo.PHOTOS_DIR", tmp_path
    )
    deps = _deps(with_camera_obj=False, frame=_frame())
    deps.camera_worker = None

    result = await TakePhoto()(deps)
    assert "error" in result


@pytest.mark.asyncio
async def test_falls_back_to_buffered_frame_on_sdk_1_8(monkeypatch, tmp_path):
    """media.camera is None (SDK 1.8) → high-res skipped → buffered frame saved."""
    monkeypatch.setattr(
        "reachy_mini_conversation_app.tools.take_photo.PHOTOS_DIR", tmp_path
    )
    deps = _deps(with_camera_obj=False, frame=_frame())

    result = await TakePhoto()(deps)

    assert result["status"] == "success"
    assert result["resolution"] == "6x4"  # WxH of the 4x6x3 frame
    # the buffered-stream path was used
    deps.camera_worker.get_latest_frame.assert_called_once()
    # a file was actually written
    saved = list(tmp_path.glob("*.png"))
    assert len(saved) == 1
    assert result["filename"] == saved[0].name


@pytest.mark.asyncio
async def test_errors_when_no_frame_available(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "reachy_mini_conversation_app.tools.take_photo.PHOTOS_DIR", tmp_path
    )
    deps = _deps(with_camera_obj=False, frame=None)

    result = await TakePhoto()(deps)
    assert "error" in result


def test_is_a_registered_tool():
    # sanity: TakePhoto declares the expected tool name
    assert TakePhoto.name == "take_photo"
    assert isinstance(TakePhoto().parameters_schema, dict)
