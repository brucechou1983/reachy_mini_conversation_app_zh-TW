"""Tests for durable .env loading + precedence (config._load_env_files)."""

import os
from pathlib import Path

import pytest

import reachy_mini_conversation_app.config as cfg


_TEST_VARS = ("RM_TEST_A", "RM_TEST_B", "RM_TEST_C")


@pytest.fixture(autouse=True)
def _clean_env():
    # load_dotenv writes os.environ directly (bypassing monkeypatch), so scrub our
    # test vars before and after each test.
    for v in _TEST_VARS:
        os.environ.pop(v, None)
    yield
    for v in _TEST_VARS:
        os.environ.pop(v, None)


def _write_env(dir_path: Path, **vars: str) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / ".env").write_text(
        "".join(f"{k}={v}\n" for k, v in vars.items()), encoding="utf-8"
    )


def test_reachy_mini_home_is_under_home():
    assert cfg.reachy_mini_home() == Path.home() / ".reachy_mini"


def test_durable_env_is_loaded(monkeypatch, tmp_path):
    home = tmp_path / "home"
    _write_env(home, RM_TEST_A="durable")
    monkeypatch.setattr(cfg, "reachy_mini_home", lambda: home)
    cwd_empty = tmp_path / "cwd_empty"      # no project .env to interfere
    cwd_empty.mkdir()
    monkeypatch.chdir(cwd_empty)

    cfg._load_env_files()
    assert os.environ["RM_TEST_A"] == "durable"


def test_os_env_wins_over_durable_fallback(monkeypatch, tmp_path):
    """The durable file is a fallback — an explicit OS env var (launchctl) wins."""
    home = tmp_path / "home"
    _write_env(home, RM_TEST_B="from_durable")
    monkeypatch.setattr(cfg, "reachy_mini_home", lambda: home)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    os.environ["RM_TEST_B"] = "from_os_env"

    cfg._load_env_files()
    assert os.environ["RM_TEST_B"] == "from_os_env"   # explicit env not clobbered


def test_cwd_env_overrides_durable(monkeypatch, tmp_path):
    """A project-local .env (dev override) wins over the durable file."""
    home = tmp_path / "home"
    _write_env(home, RM_TEST_C="from_durable")
    monkeypatch.setattr(cfg, "reachy_mini_home", lambda: home)
    cwd = tmp_path / "cwd"
    _write_env(cwd, RM_TEST_C="from_cwd")
    monkeypatch.chdir(cwd)

    cfg._load_env_files()
    assert os.environ["RM_TEST_C"] == "from_cwd"


def test_no_env_files_is_safe(monkeypatch, tmp_path):
    home = tmp_path / "home"      # exists but no .env
    home.mkdir()
    monkeypatch.setattr(cfg, "reachy_mini_home", lambda: home)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    cfg._load_env_files()  # must not raise
    assert "RM_TEST_A" not in os.environ
