import base64
import asyncio
import logging
from typing import Any, Dict

import cv2

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies


logger = logging.getLogger(__name__)


class Camera(Tool):
    """Take a picture with the camera and ask a question about it."""

    name = "camera"
    description = "Take a picture with the camera and ask a question about it."
    parameters_schema = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The question to ask about the picture",
            },
        },
        "required": ["question"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        """Take a picture with the camera and ask a question about it."""
        image_query = (kwargs.get("question") or "").strip()
        if not image_query:
            logger.warning("camera: empty question")
            return {"error": "question must be a non-empty string"}

        logger.info("Tool call: camera question=%s", image_query[:120])

        if deps.camera_worker is None:
            logger.error("Camera worker not available")
            return {"error": "Camera worker not available"}

        # Hold the head still (stop tracking + wobble, settle) so we actually
        # look at what the child is holding up, then grab a clean frame.
        frame = await self._grab_steady_frame(deps)
        if frame is None:
            logger.error("No frame available from camera worker")
            return {"error": "No frame available"}

        # Use vision manager for processing if available
        if deps.vision_manager is not None:
            vision_result = await asyncio.to_thread(
                deps.vision_manager.processor.process_image, frame, image_query,
            )
            if isinstance(vision_result, dict) and "error" in vision_result:
                return vision_result
            return (
                {"image_description": vision_result}
                if isinstance(vision_result, str)
                else {"error": "vision returned non-string"}
            )

        # Encode image directly to JPEG bytes without writing to file
        success, buffer = cv2.imencode('.jpg', frame)
        if not success:
            raise RuntimeError("Failed to encode frame as JPEG")

        b64_encoded = base64.b64encode(buffer.tobytes()).decode("utf-8")
        return {"b64_im": b64_encoded}

    async def _grab_steady_frame(self, deps: ToolDependencies) -> Any:
        """Freeze the head (stop tracking + wobble, settle), grab a frame, resume.

        The robot fidgets (face tracking, speech head-sway, idle motion), so a
        raw buffer grab often misses what the child is holding. Mirror
        take_photo's freeze so the head is pointed and still for the shot.
        """
        cw = deps.camera_worker
        assert cw is not None  # caller guarantees this
        was_tracking = bool(getattr(cw, "is_head_tracking_enabled", False))
        try:
            if deps.head_wobbler is not None:
                deps.head_wobbler.reset()
            if was_tracking:
                cw.set_head_tracking_enabled(False)
            if deps.movement_manager is not None:
                # Settle at neutral; blocks briefly so the frame isn't motion-blurred.
                await asyncio.to_thread(deps.movement_manager.freeze, 0.4, 2.0)
            return cw.get_latest_frame()
        except Exception as e:  # never let freezing break a normal look
            logger.warning("camera: steady-frame freeze failed (%s); using buffer", e)
            return cw.get_latest_frame()
        finally:
            if deps.movement_manager is not None:
                try:
                    deps.movement_manager.unfreeze()
                except Exception:
                    pass
            if was_tracking:
                try:
                    cw.set_head_tracking_enabled(True)
                except Exception:
                    pass
