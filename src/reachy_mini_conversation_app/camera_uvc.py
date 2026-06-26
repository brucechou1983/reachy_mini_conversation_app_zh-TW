"""OS-level UVC camera controls (exposure / gain / brightness …).

The Reachy Mini SDK and daemon expose **no** camera exposure API: on macOS the
daemon captures via ``avfvideosrc`` configured with only a device-index, and the
camera's real resolution/framerate is fixed at daemon startup. The only supported
lever for image brightness — per the official HF docs section *"Image is dark on
the Lite version"* — is an external OS-level UVC tool talking to the USB camera
directly: ``uvc-util`` on macOS, ``v4l2-ctl`` on Linux.

The key control is ``auto-exposure-priority`` (UVC; ``exposure_auto_priority`` in
v4l2). With it **0**, the camera holds its framerate and caps exposure at the
frame interval (e.g. 1/60s ≈ 16.6ms), so in dim light it can only crank gain and
the image stays dark/noisy. Set to **1**, the camera may lower its effective
framerate to lengthen the exposure — i.e. it trades framerate for exposure — and
brightens. These writes are honoured even while the daemon streams the camera,
but they reset on robot/daemon restart or camera re-enumeration, so we re-apply
them at every app startup (see :func:`apply_low_light_defaults`).

This module is the single home for the UVC CLI plumbing; ``tools/take_photo.py``
reuses it for its save/restore-across-resolution-switch logic.
"""

import shutil
import logging
import platform
import subprocess
from typing import Any, Dict, List, Optional
from pathlib import Path


logger = logging.getLogger(__name__)


# UVC controls take_photo saves and restores across resolution switches.
# (Switching resolution on macOS resets all UVC device controls to defaults.)
UVC_CONTROLS = [
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


def find_uvc_tool() -> Optional[str]:
    """Return the path to the platform's UVC CLI tool, or ``None``.

    macOS uses ``uvc-util``; Linux uses ``v4l2-ctl``. Windows has no
    equivalent CLI, so returns ``None`` there.
    """
    if platform.system() == "Darwin":
        # shutil.which may fail in sandboxed app environments where
        # /usr/local/bin is not on PATH. Check common paths explicitly.
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


def device_selector(tool: str, camera_specs: Any) -> List[str]:
    """Build the device-selector flags for ``uvc-util`` or ``v4l2-ctl``.

    For ``uvc-util`` we target the camera by USB vendor/product id (from
    ``camera_specs``) so we never touch the wrong webcam (e.g. a Mac's
    built-in FaceTime camera); falls back to ``-I 0`` when specs are
    unavailable. ``v4l2-ctl`` uses its default device.
    """
    if "uvc-util" in tool:
        if camera_specs is not None:
            vid = getattr(camera_specs, "vid", 0)
            pid = getattr(camera_specs, "pid", 0)
            if vid and pid:
                return [f"--select-by-vendor-and-product-id={vid:#06x}:{pid:#06x}"]
        return ["-I", "0"]
    # v4l2-ctl: default device
    return []


def get_controls(
    tool: str,
    selector: List[str],
    names: Optional[List[str]] = None,
) -> Dict[str, str]:
    """Read current values for the given UVC controls (defaults to all)."""
    if names is None:
        names = UVC_CONTROLS
    saved: Dict[str, str] = {}
    for ctrl in names:
        try:
            if "uvc-util" in tool:
                result = subprocess.run(
                    [tool] + selector + ["--get-value", ctrl],
                    capture_output=True, text=True, timeout=5,
                )
            else:
                # v4l2-ctl on Linux
                result = subprocess.run(
                    [tool] + selector + [f"--get-ctrl={ctrl}"],
                    capture_output=True, text=True, timeout=5,
                )
            if result.returncode == 0 and result.stdout.strip():
                val = result.stdout.strip().split(":")[-1].strip()
                saved[ctrl] = val
        except Exception:
            pass
    return saved


def set_controls(tool: str, selector: List[str], values: Dict[str, str]) -> None:
    """Set UVC control values (best-effort; per-control failures are ignored)."""
    for ctrl, val in values.items():
        try:
            if "uvc-util" in tool:
                subprocess.run(
                    [tool] + selector + [f"--set={ctrl}={val}"],
                    capture_output=True, text=True, timeout=5,
                )
            else:
                subprocess.run(
                    [tool] + selector + [f"--set-ctrl={ctrl}={val}"],
                    capture_output=True, text=True, timeout=5,
                )
        except Exception:
            pass


def _low_light_controls(tool: str) -> Dict[str, str]:
    """Return the auto-exposure controls that brighten dim scenes, per tool.

    The control names differ between the two CLIs:

    * ``uvc-util`` (macOS): ``auto-exposure-mode=8`` (aperture-priority = auto
      exposure on) and ``auto-exposure-priority=1`` (allow longer exposure /
      lower framerate in low light).
    * ``v4l2-ctl`` (Linux): the legacy names (``exposure_auto=3`` /
      ``exposure_auto_priority=1``) AND the modern kernel ~4.5+ renames
      (``auto_exposure=3`` / ``exposure_dynamic_framerate=1``). Both are sent;
      whichever the kernel exposes wins and the other silently fails
      (:func:`set_controls` ignores per-control errors).
    """
    if "uvc-util" in tool:
        return {"auto-exposure-mode": "8", "auto-exposure-priority": "1"}
    return {
        "exposure_auto": "3",            # legacy: aperture-priority (auto exposure)
        "exposure_auto_priority": "1",   # legacy: allow longer exposure / lower fps
        "auto_exposure": "3",            # modern (kernel ~4.5+) rename of the above
        "exposure_dynamic_framerate": "1",
    }


def apply_low_light_defaults(camera_specs: Any, *, enable: bool = True) -> bool:
    """Enable auto-exposure with long-exposure priority so the camera isn't dark.

    Sets ``auto-exposure-priority=1`` (and auto-exposure mode) on the UVC camera
    so it can lengthen exposure (drop framerate) in dim light instead of staying
    dark — the official "Image is dark on the Lite version" fix. Best-effort and
    never raises, so it is safe to call during startup:

    * Returns ``False`` (and logs) when disabled, when no UVC tool is installed,
      or when the camera specs (USB vid/pid) are unknown — in the last case we
      skip rather than risk targeting the wrong webcam.
    * Returns ``True`` once the controls have been written.

    Args:
        camera_specs: The camera's ``CameraSpecs`` (for the USB vid/pid selector).
        enable: When ``False``, do nothing (lets a user opt out via config).

    """
    if not enable:
        logger.info("Camera low-light fix disabled (REACHY_MINI_CAMERA_LOW_LIGHT).")
        return False

    tool = find_uvc_tool()
    if tool is None:
        logger.info(
            "No UVC tool (uvc-util/v4l2-ctl) found; skipping camera low-light fix. "
            "Install uvc-util (brew install uvc-util) to auto-brighten the camera "
            "in dim light."
        )
        return False

    if camera_specs is None:
        logger.info(
            "Camera specs unknown; skipping low-light fix to avoid touching the "
            "wrong camera."
        )
        return False

    try:
        selector = device_selector(tool, camera_specs)
        set_controls(tool, selector, _low_light_controls(tool))
        logger.info(
            "Applied camera low-light fix via %s: auto-exposure-priority=1 "
            "(camera may lengthen exposure / drop framerate in dim light). "
            "Disable with REACHY_MINI_CAMERA_LOW_LIGHT=false.",
            Path(tool).name,
        )
        return True
    except Exception as e:
        logger.warning("Failed to apply camera low-light fix: %s", e)
        return False
