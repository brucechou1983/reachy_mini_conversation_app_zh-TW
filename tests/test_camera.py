"""Tests for the camera tool — it must hold the head still before capturing."""

from unittest.mock import MagicMock

import numpy as np
import pytest

from reachy_mini_conversation_app.tools.camera import Camera


def _deps(*, tracking: bool, frame):
    deps = MagicMock()
    deps.vision_manager = None  # use the direct JPEG path
    cw = MagicMock()
    cw.is_head_tracking_enabled = tracking
    cw.get_latest_frame.return_value = frame
    deps.camera_worker = cw
    deps.head_wobbler = MagicMock()
    return deps


@pytest.mark.asyncio
async def test_camera_freezes_head_then_restores():
    deps = _deps(tracking=True, frame=np.zeros((4, 6, 3), dtype=np.uint8))
    result = await Camera()(deps, question="這是什麼？")

    # settled the head and released it
    deps.movement_manager.freeze.assert_called_once()
    deps.movement_manager.unfreeze.assert_called_once()
    deps.head_wobbler.reset.assert_called_once()
    # tracking disabled for the shot, then restored
    toggles = [c.args[0] for c in deps.camera_worker.set_head_tracking_enabled.call_args_list]
    assert toggles == [False, True]
    assert "b64_im" in result


@pytest.mark.asyncio
async def test_camera_leaves_tracking_off_if_it_was_off():
    deps = _deps(tracking=False, frame=np.zeros((4, 6, 3), dtype=np.uint8))
    await Camera()(deps, question="這是什麼？")
    deps.camera_worker.set_head_tracking_enabled.assert_not_called()


@pytest.mark.asyncio
async def test_camera_empty_question_errors():
    deps = _deps(tracking=False, frame=np.zeros((4, 6, 3), dtype=np.uint8))
    result = await Camera()(deps, question="   ")
    assert "error" in result


@pytest.mark.asyncio
async def test_camera_no_worker_errors():
    deps = MagicMock()
    deps.camera_worker = None
    result = await Camera()(deps, question="x")
    assert "error" in result


@pytest.mark.asyncio
async def test_camera_no_frame_errors():
    deps = _deps(tracking=False, frame=None)
    result = await Camera()(deps, question="x")
    assert "error" in result
    # even on failure, the head must be released
    deps.movement_manager.unfreeze.assert_called_once()
