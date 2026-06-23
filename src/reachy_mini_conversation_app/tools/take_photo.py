"""Tool to capture a photo from the robot's camera and save it as PNG."""

import time
import shutil
import asyncio
import logging
import platform
import subprocess
from typing import Any, Dict, List, Optional, cast
from pathlib import Path
from datetime import datetime

import cv2
import numpy as np
from numpy.typing import NDArray

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies


logger = logging.getLogger(__name__)

PHOTOS_DIR = Path.home() / "Pictures" / "reachy"

# UVC controls to save and restore across resolution switches.
# Switching resolution on macOS resets all UVC device controls to defaults.
_UVC_CONTROLS = [
    "auto-exposure-mode",
    "auto-exposure-priority",
    "exposure-time-abs",
    "brightness",
    "gain",
    "contrast",
    "saturation",
    "sharpness",
    "gamma",
    "hue",
    "white-balance-temp",
    "auto-white-balance-temp",
    "backlight-compensation",
    "power-line-frequency",
]


# ------------------------------------------------------------------
# UVC helpers (macOS: uvc-util, Linux: v4l2-ctl)
# ------------------------------------------------------------------

def _find_uvc_tool() -> Optional[str]:
    """Return the path to the platform's UVC CLI tool, or None."""
    if platform.system() == "Darwin":
        # shutil.which may fail in sandboxed app environments where
        # /usr/local/bin is not on PATH.  Check common paths explicitly.
        path = shutil.which("uvc-util")
        if path:
            return path
        for candidate in ["/usr/local/bin/uvc-util", "/opt/homebrew/bin/uvc-util"]:
            if Path(candidate).is_file():
                return candidate
        return None
    elif platform.system() == "Linux":
        return shutil.which("v4l2-ctl")
    return None


def _uvc_get_all(tool: str, device_selector: List[str]) -> Dict[str, str]:
    """Read current values for all UVC controls we care about."""
    saved: Dict[str, str] = {}
    for ctrl in _UVC_CONTROLS:
        try:
            if "uvc-util" in tool:
                result = subprocess.run(
                    [tool] + device_selector + ["--get-value", ctrl],
                    capture_output=True, text=True, timeout=5,
                )
            else:
                # v4l2-ctl on Linux
                result = subprocess.run(
                    [tool] + device_selector + [f"--get-ctrl={ctrl}"],
                    capture_output=True, text=True, timeout=5,
                )
            if result.returncode == 0 and result.stdout.strip():
                val = result.stdout.strip().split(":")[-1].strip()
                saved[ctrl] = val
        except Exception:
            pass
    return saved


def _uvc_set_all(
    tool: str,
    device_selector: List[str],
    values: Dict[str, str],
) -> None:
    """Restore saved UVC control values."""
    for ctrl, val in values.items():
        try:
            if "uvc-util" in tool:
                subprocess.run(
                    [tool] + device_selector + [f"--set={ctrl}={val}"],
                    capture_output=True, text=True, timeout=5,
                )
            else:
                subprocess.run(
                    [tool] + device_selector + [f"--set-ctrl={ctrl}={val}"],
                    capture_output=True, text=True, timeout=5,
                )
        except Exception:
            pass


def _get_device_selector(tool: str, camera: Any) -> List[str]:
    """Build the device-selector flags for uvc-util or v4l2-ctl."""
    if "uvc-util" in tool:
        specs = getattr(camera, "camera_specs", None)
        if specs is not None:
            vid = getattr(specs, "vid", 0)
            pid = getattr(specs, "pid", 0)
            if vid and pid:
                return [f"--select-by-vendor-and-product-id={vid:#06x}:{pid:#06x}"]
        return ["-I", "0"]
    # v4l2-ctl: default device
    return []


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
        """Freeze robot at neutral, capture at highest resolution, then resume."""
        logger.info("Tool call: take_photo")

        if deps.camera_worker is None:
            return {"error": "Camera worker not available"}

        # Freeze the robot for a still capture
        was_tracking = deps.camera_worker.is_head_tracking_enabled
        try:
            await self._freeze(deps, was_tracking)

            # Try high-res capture; fall back to the buffered stream frame.
            frame = await asyncio.to_thread(self._capture_high_res, deps)
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

    async def _freeze(self, deps: ToolDependencies, was_tracking: bool) -> None:
        """Atomically freeze robot at neutral. Blocks until settled."""
        logger.info("Freezing robot for photo capture")

        if deps.head_wobbler is not None:
            deps.head_wobbler.reset()

        if was_tracking:
            assert deps.camera_worker is not None
            deps.camera_worker.set_head_tracking_enabled(False)

        settled = await asyncio.to_thread(
            deps.movement_manager.freeze, 0.5, 3.0
        )
        if not settled:
            logger.warning("Robot did not fully settle before photo capture")

    def _unfreeze(self, deps: ToolDependencies, was_tracking: bool) -> None:
        """Release freeze; normal motion resumes."""
        logger.info("Unfreezing robot after photo capture")
        deps.movement_manager.unfreeze()
        if was_tracking:
            assert deps.camera_worker is not None
            deps.camera_worker.set_head_tracking_enabled(True)

    # ------------------------------------------------------------------

    def _capture_high_res(
        self, deps: ToolDependencies,
    ) -> Optional[NDArray[np.uint8]]:
        """Capture at max resolution with UVC control save/restore.

        OpenCV on macOS cannot read/write UVC controls. Switching resolution
        resets them to dark defaults. We use uvc-util (macOS) or v4l2-ctl
        (Linux) to save controls before the switch and restore them after,
        so the sensor produces a natively well-exposed high-res frame.

        Falls back to software brightness correction if no UVC tool is
        available.
        """
        camera_worker = deps.camera_worker
        assert camera_worker is not None
        try:
            camera = deps.reachy_mini.media.camera
            if camera is None:
                return None

            cap = getattr(camera, "cap", None)
            if cap is None:
                return None

            current_w, current_h = camera.resolution

            best_res = max(
                camera.camera_specs.available_resolutions,
                key=lambda r: r.value[0] * r.value[1],
            )

            if best_res.value[0] * best_res.value[1] <= current_w * current_h:
                return None

            # Locate UVC CLI tool.
            uvc_tool = _find_uvc_tool()
            device_selector: List[str] = []
            saved_controls: Dict[str, str] = {}

            if uvc_tool:
                device_selector = _get_device_selector(uvc_tool, camera)
                saved_controls = _uvc_get_all(uvc_tool, device_selector)
                logger.info("Saved UVC controls via %s: %s", uvc_tool, saved_controls)
            else:
                logger.info("No UVC tool found; will use software brightness correction")
                # Grab reference frame for software fallback.
                ref_frame = camera_worker.get_latest_frame()

            # --- stop camera_worker so we have exclusive access ---
            camera_worker.stop()

            logger.info(
                "Switching camera %dx%d -> %dx%d for photo capture",
                current_w, current_h,
                best_res.value[0], best_res.value[1],
            )
            camera.set_resolution(best_res)

            # After the resolution switch the camera resets all UVC controls
            # to factory defaults (dark).  Per Pollen Robotics docs the fix is
            # to enable auto-exposure with priority=1 so the sensor converges
            # to correct brightness.  We then drain warmup frames for AEC.
            if uvc_tool:
                _uvc_set_all(uvc_tool, device_selector, {
                    "auto-exposure-mode": "8",       # auto
                    "auto-exposure-priority": "1",   # prioritise exposure
                })
                logger.info("Set auto-exposure ON with priority=1 after resolution switch")

            # Drain frames so the sensor's AEC converges.
            AEC_FRAMES = 30
            t0 = time.monotonic()
            for _ in range(AEC_FRAMES):
                cap.read()
            logger.info(
                "AEC warmup: %d frames in %.2fs",
                AEC_FRAMES, time.monotonic() - t0,
            )

            ret, frame = cap.read()
            if not ret or frame is None:
                logger.warning("Failed to read high-res frame")
                return None

            # If no UVC tool was available, fall back to software correction.
            if not uvc_tool:
                frame = self._match_brightness(frame, ref_frame)

            logger.info(
                "High-res frame captured: %dx%d", frame.shape[1], frame.shape[0],
            )
            return cast(NDArray[np.uint8], frame)

        except Exception as e:
            logger.warning("High-res capture failed, using buffered frame: %s", e)
            return None

        finally:
            # Restore original resolution, UVC controls, and restart camera_worker.
            try:
                camera = deps.reachy_mini.media.camera
                if camera is not None:
                    original_res = camera.camera_specs.default_resolution
                    camera.set_resolution(original_res)

                    # Restore UVC controls again after switching back.
                    if uvc_tool and saved_controls:
                        _uvc_set_all(uvc_tool, device_selector, saved_controls)

                    logger.info(
                        "Camera resolution restored to %dx%d",
                        original_res.value[0], original_res.value[1],
                    )
            except Exception as e:
                logger.warning("Failed to restore camera resolution: %s", e)

            camera_worker.start()

    @staticmethod
    def _match_brightness(
        dark: NDArray[np.uint8],
        ref: Optional[NDArray[np.uint8]],
    ) -> NDArray[np.uint8]:
        """Scale *dark* per-channel so its mean brightness matches *ref*.

        Used as a fallback when no UVC CLI tool is available.
        """
        if ref is None:
            return dark

        ref_mean = ref.mean(axis=(0, 1)).astype(np.float64)
        dark_mean = dark.mean(axis=(0, 1)).astype(np.float64)

        MIN_MEAN = 1.0
        if (dark_mean < MIN_MEAN).any() or (ref_mean < MIN_MEAN).any():
            logger.warning(
                "Frame too dim for brightness matching "
                "(ref_mean=%s, dark_mean=%s); skipping correction",
                ref_mean, dark_mean,
            )
            return dark

        gain = ref_mean / dark_mean
        logger.info(
            "Brightness correction — ref_mean=%s, dark_mean=%s, gain=%s",
            ref_mean.round(1), dark_mean.round(1), gain.round(2),
        )

        corrected = dark.astype(np.float32) * gain.astype(np.float32)
        np.clip(corrected, 0, 255, out=corrected)
        return cast(NDArray[np.uint8], corrected.astype(np.uint8))
