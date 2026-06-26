"""Tests for OS-level UVC camera controls (camera_uvc)."""

import subprocess
from unittest.mock import MagicMock

import reachy_mini_conversation_app.camera_uvc as uvc


class _Specs:
    """Minimal camera_specs stand-in with a USB vid/pid."""

    def __init__(self, vid=0x38FB, pid=0x1002):
        self.vid = vid
        self.pid = pid


# --- find_uvc_tool() ---


def test_find_uvc_tool_macos_prefers_which(monkeypatch):
    monkeypatch.setattr(uvc.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(uvc.shutil, "which", lambda name: "/somewhere/uvc-util")
    assert uvc.find_uvc_tool() == "/somewhere/uvc-util"


def test_find_uvc_tool_macos_falls_back_to_known_paths(monkeypatch):
    monkeypatch.setattr(uvc.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(uvc.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        uvc.Path, "is_file", lambda self: str(self) == "/usr/local/bin/uvc-util"
    )
    assert uvc.find_uvc_tool() == "/usr/local/bin/uvc-util"


def test_find_uvc_tool_macos_none_when_missing(monkeypatch):
    monkeypatch.setattr(uvc.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(uvc.shutil, "which", lambda name: None)
    monkeypatch.setattr(uvc.Path, "is_file", lambda self: False)
    assert uvc.find_uvc_tool() is None


def test_find_uvc_tool_linux_uses_v4l2(monkeypatch):
    monkeypatch.setattr(uvc.platform, "system", lambda: "Linux")
    monkeypatch.setattr(uvc.shutil, "which", lambda name: "/usr/bin/v4l2-ctl")
    assert uvc.find_uvc_tool() == "/usr/bin/v4l2-ctl"


def test_find_uvc_tool_windows_none(monkeypatch):
    monkeypatch.setattr(uvc.platform, "system", lambda: "Windows")
    assert uvc.find_uvc_tool() is None


# --- device_selector() ---


def test_device_selector_uvcutil_uses_vid_pid():
    sel = uvc.device_selector("/usr/local/bin/uvc-util", _Specs())
    assert sel == ["--select-by-vendor-and-product-id=0x38fb:0x1002"]


def test_device_selector_uvcutil_fallback_without_specs():
    assert uvc.device_selector("uvc-util", None) == ["-I", "0"]
    # Specs present but no vid/pid -> also fall back.
    assert uvc.device_selector("uvc-util", _Specs(vid=0, pid=0)) == ["-I", "0"]


def test_device_selector_v4l2_is_empty():
    assert uvc.device_selector("/usr/bin/v4l2-ctl", _Specs()) == []


# --- set_controls() / get_controls() ---


def test_set_controls_uvcutil_emits_set_flags(monkeypatch):
    calls = []
    monkeypatch.setattr(
        subprocess, "run", lambda args, **k: calls.append(args) or MagicMock(returncode=0)
    )
    uvc.set_controls("uvc-util", ["-I", "0"], {"auto-exposure-priority": "1"})
    assert calls == [["uvc-util", "-I", "0", "--set=auto-exposure-priority=1"]]


def test_set_controls_v4l2_emits_set_ctrl_flags(monkeypatch):
    calls = []
    monkeypatch.setattr(
        subprocess, "run", lambda args, **k: calls.append(args) or MagicMock(returncode=0)
    )
    uvc.set_controls("v4l2-ctl", [], {"exposure_auto_priority": "1"})
    assert calls == [["v4l2-ctl", "--set-ctrl=exposure_auto_priority=1"]]


def test_get_controls_parses_values(monkeypatch):
    def fake_run(args, **k):
        # Value of the requested control is the last "--get-value X" arg.
        ctrl = args[-1]
        return MagicMock(returncode=0, stdout=f"{ctrl}: 42\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    got = uvc.get_controls("uvc-util", ["-I", "0"], names=["gain", "brightness"])
    assert got == {"gain": "42", "brightness": "42"}


def test_get_controls_swallows_failures(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("boom"))
    )
    assert uvc.get_controls("uvc-util", [], names=["gain"]) == {}


# --- apply_low_light_defaults() ---


def test_apply_low_light_disabled_is_noop(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(uvc, "set_controls", lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    assert uvc.apply_low_light_defaults(_Specs(), enable=False) is False
    assert called["n"] == 0


def test_apply_low_light_no_tool_returns_false(monkeypatch):
    monkeypatch.setattr(uvc, "find_uvc_tool", lambda: None)
    assert uvc.apply_low_light_defaults(_Specs(), enable=True) is False


def test_apply_low_light_skips_when_specs_unknown(monkeypatch):
    monkeypatch.setattr(uvc, "find_uvc_tool", lambda: "uvc-util")
    called = {"n": 0}
    monkeypatch.setattr(uvc, "set_controls", lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    assert uvc.apply_low_light_defaults(None, enable=True) is False
    assert called["n"] == 0


def test_apply_low_light_macos_sets_priority(monkeypatch):
    monkeypatch.setattr(uvc, "find_uvc_tool", lambda: "/usr/local/bin/uvc-util")
    captured = {}
    monkeypatch.setattr(
        uvc, "set_controls",
        lambda tool, selector, values: captured.update(tool=tool, selector=selector, values=values),
    )
    assert uvc.apply_low_light_defaults(_Specs(), enable=True) is True
    assert captured["values"] == {"auto-exposure-mode": "8", "auto-exposure-priority": "1"}
    assert captured["selector"] == ["--select-by-vendor-and-product-id=0x38fb:0x1002"]


def test_apply_low_light_linux_uses_v4l2_names(monkeypatch):
    monkeypatch.setattr(uvc, "find_uvc_tool", lambda: "/usr/bin/v4l2-ctl")
    captured = {}
    monkeypatch.setattr(
        uvc, "set_controls",
        lambda tool, selector, values: captured.update(values=values),
    )
    assert uvc.apply_low_light_defaults(_Specs(), enable=True) is True
    # Both legacy and modern v4l2 names are sent (whichever the kernel has wins).
    assert captured["values"] == {
        "exposure_auto": "3",
        "exposure_auto_priority": "1",
        "auto_exposure": "3",
        "exposure_dynamic_framerate": "1",
    }


def test_apply_low_light_never_raises(monkeypatch):
    monkeypatch.setattr(uvc, "find_uvc_tool", lambda: "uvc-util")
    monkeypatch.setattr(
        uvc, "set_controls", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("nope"))
    )
    # Should swallow the error and report failure rather than propagate.
    assert uvc.apply_low_light_defaults(_Specs(), enable=True) is False
