"""Tool to capture a photo from the robot's camera and save it as PNG."""

import logging
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, Optional

import cv2
import numpy as np
from numpy.typing import NDArray

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies


logger = logging.getLogger(__name__)

PHOTOS_DIR = Path.home() / "Pictures" / "reachy"


class TakePhoto(Tool):
    """Take a photo with the camera and save it to ~/Pictures/reachy/."""

    name = "take_photo"
    description = "Take a photo with the camera and save it to the photo gallery."
    parameters_schema = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        """Freeze robot, capture at highest resolution, then resume."""
        logger.info("Tool call: take_photo")

        if deps.camera_worker is None:
            return {"error": "Camera worker not available"}

        # Freeze the robot for a still capture
        was_tracking = deps.camera_worker.is_head_tracking_enabled
        try:
            self._freeze(deps, was_tracking)
            await asyncio.sleep(1.0)  # let the robot settle

            # Try high-res capture first, fall back to buffered frame
            frame = await self._capture_high_res(deps)
            if frame is None:
                frame = deps.camera_worker.get_latest_frame()
        finally:
            self._unfreeze(deps, was_tracking)

        if frame is None:
            return {"error": "No frame available from camera"}

        PHOTOS_DIR.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")
        filename = f"{timestamp}.png"
        filepath = PHOTOS_DIR / filename

        success = cv2.imwrite(str(filepath), frame)
        if not success:
            return {"error": "Failed to save photo"}

        h, w = frame.shape[:2]
        logger.info("Photo saved: %s (%dx%d)", filepath, w, h)
        return {
            "status": "success",
            "filename": filename,
            "path": str(filepath),
            "resolution": f"{w}x{h}",
        }

    def _freeze(self, deps: ToolDependencies, was_tracking: bool) -> None:
        """Stop all movement sources so the robot holds still."""
        logger.info("Freezing robot for photo capture")
        # Stop dances, emotions, breathing
        deps.movement_manager.clear_move_queue()
        # Disable face tracking
        if was_tracking:
            deps.camera_worker.set_head_tracking_enabled(False)
        # Zero speech sway
        deps.movement_manager.set_speech_offsets((0.0, 0.0, 0.0, 0.0, 0.0, 0.0))

    def _unfreeze(self, deps: ToolDependencies, was_tracking: bool) -> None:
        """Restore movement sources after capture."""
        logger.info("Unfreezing robot after photo capture")
        if was_tracking:
            deps.camera_worker.set_head_tracking_enabled(True)
        # Breathing will restart automatically via MovementManager idle logic

    async def _capture_high_res(
        self, deps: ToolDependencies
    ) -> Optional[NDArray[np.uint8]]:
        """Temporarily switch to the highest resolution, capture, and restore."""
        original_res = None
        try:
            from reachy_mini.media.camera_constants import CameraResolution

            camera = deps.reachy_mini.media.camera
            if camera is None:
                return None

            # Find current resolution so we can restore it later
            current_w, current_h = camera.resolution
            for res in camera.camera_specs.available_resolutions:
                if (res.value[0], res.value[1]) == (current_w, current_h):
                    original_res = res
                    break

            # Pick the highest available resolution
            best_res = max(
                camera.camera_specs.available_resolutions,
                key=lambda r: r.value[0] * r.value[1],
            )

            # Skip if already at highest resolution
            if best_res.value[0] * best_res.value[1] <= current_w * current_h:
                return None

            logger.info(
                "Switching camera %dx%d -> %dx%d for photo capture",
                current_w,
                current_h,
                best_res.value[0],
                best_res.value[1],
            )
            camera.set_resolution(best_res)

            # Wait for camera pipeline to settle, then capture
            await asyncio.sleep(1.0)
            frame = deps.reachy_mini.media.get_frame()

            return frame

        except Exception as e:
            logger.warning("High-res capture failed, using buffered frame: %s", e)
            return None

        finally:
            if original_res is not None:
                try:
                    deps.reachy_mini.media.camera.set_resolution(original_res)
                    logger.info(
                        "Camera resolution restored to %dx%d",
                        original_res.value[0],
                        original_res.value[1],
                    )
                except Exception as e:
                    logger.warning("Failed to restore camera resolution: %s", e)
