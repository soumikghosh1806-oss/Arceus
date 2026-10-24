"""``run_hud()`` — the entry point used by ``python main.py --hud``."""

from __future__ import annotations

from pathlib import Path

from arceus.assistant import ArceusAssistant
from arceus.config import ArceusConfig
from arceus.exceptions import HudError

WEB_ROOT = Path(__file__).resolve().parent / "web"
_INSTALL_HINT = (
    'Install it with:  pip install "PySide6>=6.12.0"  '
    "(PySide6 6.12 is the first release that supports Python 3.15)."
)


def run_hud(assistant: ArceusAssistant, config: ArceusConfig, *, fullscreen: bool = False) -> int:
    """Open the HUD window and block until it closes.  Returns the exit code."""
    if not (WEB_ROOT / "index.html").is_file():
        raise HudError(f"HUD interface files are missing at {WEB_ROOT}.")
    try:
        from arceus.hud import qt_shell
    except ImportError as exc:
        raise HudError(f"The HUD needs PySide6 with QtWebEngine. {_INSTALL_HINT} ({exc})") from exc
    return qt_shell.run(assistant, config, fullscreen, WEB_ROOT / "index.html")
