"""HUD configuration and command-line wiring (never opens a window)."""

from __future__ import annotations

import importlib.util
import json

import pytest

import main as arceus_main
from arceus.config import ArceusConfig
from arceus.exceptions import HudError


def test_fullscreen_defaults_to_windowed():
    assert ArceusConfig(model_backend="echo").hud_fullscreen == 0


def test_fullscreen_can_be_enabled_by_env_and_json(monkeypatch, tmp_path):
    monkeypatch.setenv("ARCEUS_HUD_FULLSCREEN", "1")
    assert ArceusConfig(model_backend="echo").hud_fullscreen == 1
    monkeypatch.delenv("ARCEUS_HUD_FULLSCREEN")
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps({"hud_fullscreen": 1, "model_backend": "echo"}), encoding="utf-8")
    assert ArceusConfig.from_json(path).hud_fullscreen == 1


def test_hud_flags_parse(monkeypatch):
    monkeypatch.setattr("sys.argv", ["main.py", "--hud", "--fullscreen"])
    args = arceus_main.parse_args()
    assert args.hud and args.fullscreen and not args.windowed
    monkeypatch.setattr("sys.argv", ["main.py", "--hud", "--fullscreen", "--windowed"])
    with pytest.raises(SystemExit):
        arceus_main.parse_args()


def test_hud_and_voice_cannot_be_combined(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["main.py", "--backend", "echo", "--hud", "--voice"])
    with pytest.raises(SystemExit) as exc:
        arceus_main.main()
    assert exc.value.code == 1 and "--hud and --voice" in capsys.readouterr().err


@pytest.mark.parametrize("argv, config_fullscreen, expected", [
    (["--hud"], 0, False),
    (["--hud", "--fullscreen"], 0, True),
    (["--hud"], 1, True),
    (["--hud", "--windowed"], 1, False),
])
def test_launch_mode_selection(monkeypatch, argv, config_fullscreen, expected):
    seen = {}
    monkeypatch.setattr("sys.argv", ["main.py", "--backend", "echo", *argv])
    monkeypatch.setenv("ARCEUS_HUD_FULLSCREEN", str(config_fullscreen))
    monkeypatch.setattr("arceus.hud.app.run_hud", lambda **kw: seen.update(kw) or 0)
    with pytest.raises(SystemExit) as exc:
        arceus_main.main()
    assert exc.value.code == 0 and seen["fullscreen"] is expected


def test_hud_startup_problem_is_reported_cleanly(monkeypatch, capsys):
    def boom(**kw):
        raise HudError("PySide6 missing")

    monkeypatch.setattr("sys.argv", ["main.py", "--backend", "echo", "--hud"])
    monkeypatch.setattr("arceus.hud.app.run_hud", boom)
    with pytest.raises(SystemExit) as exc:
        arceus_main.main()
    assert exc.value.code == 1 and "[HUD error] PySide6 missing" in capsys.readouterr().err


@pytest.mark.skipif(importlib.util.find_spec("PySide6") is not None, reason="PySide6 is installed; would open a window")
def test_missing_pyside6_gives_an_actionable_message():
    from arceus.assistant import ArceusAssistant
    from arceus.hud.app import run_hud

    cfg = ArceusConfig(model_backend="echo")
    with pytest.raises(HudError, match=r"PySide6>=6\.12\.0"):
        run_hud(ArceusAssistant(config=cfg), cfg)
