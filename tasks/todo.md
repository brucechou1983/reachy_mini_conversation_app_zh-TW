# Task: Durable camera low-light fix (auto-exposure-priority=1 at startup)

## Why
Lite camera is dark in dim light. Root cause (verified live on the robot's cam,
vid 0x38FB:pid 0x1002): UVC `auto-exposure-priority=0` pins exposure at the 1/60s
(16.6ms) ceiling, so auto-exposure can't lengthen the shutter and just maxes gain.
Official HF docs ("Image is dark on the Lite version") fix = set
`auto-exposure-priority=1` via uvc-util (macOS) / v4l2-ctl (Linux). There is NO
SDK/daemon exposure API and no selectable low-fps mode, so this OS-level UVC
control is the supported lever. uvc-util writes are honored even while the daemon
streams — but reset on restart/replug, hence apply at every startup.

## Plan
- [ ] New module `camera_uvc.py`: extract `find_uvc_tool`, `device_selector`,
      `get_controls`, `set_controls`, `_UVC_CONTROLS` from take_photo; add
      `apply_low_light_defaults(camera_specs, *, enable)` (per-tool control names,
      best-effort, never raises).
- [ ] Refactor `take_photo.py` to import from `camera_uvc` (drop private copies),
      behavior unchanged.
- [ ] `config.py`: `CAMERA_LOW_LIGHT` (env `REACHY_MINI_CAMERA_LOW_LIGHT`, default on).
- [ ] `utils.handle_vision_stuff`: after CameraWorker created, call
      `apply_low_light_defaults(current_robot.media.camera.camera_specs, enable=...)`.
- [ ] Tests `tests/test_camera_uvc.py`; keep `test_take_photo.py` green.
- [ ] ruff + mypy + pytest green; version bump; ship PR.

## Review
- New `camera_uvc.py`: find_uvc_tool / device_selector / get_controls / set_controls
  + apply_low_light_defaults (per-tool names; macOS uvc-util mode=8/priority=1,
  Linux v4l2 exposure_auto=3/exposure_auto_priority=1). Best-effort, never raises.
- take_photo.py now imports those (deleted its 4 private dup copies + _UVC_CONTROLS),
  behavior unchanged; renamed local `device_selector` var -> `selector` (name clash).
- config.CAMERA_LOW_LIGHT (env REACHY_MINI_CAMERA_LOW_LIGHT, default on).
- utils.handle_vision_stuff applies the fix after CameraWorker is created, guarded.
- .env.example documents the knob.
- Tests: tests/test_camera_uvc.py (18). Full suite 412 passed, ruff + mypy green.
- Verified live on the robot cam (0x38fb:0x1002): priority was 0, exposure railed at
  16.6ms (1/60s); uvc-util writes honoured while daemon streams; left at auto+priority=1.
