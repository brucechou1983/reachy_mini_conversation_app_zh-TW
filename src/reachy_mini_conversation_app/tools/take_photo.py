"""Tool to capture a photo from the robot's camera and save it as PNG."""

import logging
from pathlib import Path
from datetime import datetime
from typing import Any, Dict

import cv2

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
        """Capture frame and save as PNG."""
        logger.info("Tool call: take_photo")

        if deps.camera_worker is None:
            return {"error": "Camera worker not available"}

        frame = deps.camera_worker.get_latest_frame()
        if frame is None:
            return {"error": "No frame available from camera"}

        PHOTOS_DIR.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")
        filename = f"{timestamp}.png"
        filepath = PHOTOS_DIR / filename

        success = cv2.imwrite(str(filepath), frame)
        if not success:
            return {"error": "Failed to save photo"}

        logger.info("Photo saved: %s", filepath)
        return {
            "status": "success",
            "filename": filename,
            "path": str(filepath),
        }
