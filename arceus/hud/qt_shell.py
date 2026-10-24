"""
PySide6 + QtWebEngine shell for the HUD.

This module is deliberately thin: it opens a window, loads the local HTML
interface, and forwards a handful of commands to ``HudSession``.  All
behaviour worth testing lives in ``session.py`` (no Qt there).

Security: there is no network server.  The page is loaded from local files,
talks to Python only through QWebChannel, may not navigate away from local
content, and cannot open new windows.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMainWindow

from arceus.assistant import ArceusAssistant
from arceus.config import ArceusConfig
from arceus.hud.pump import EventPump
from arceus.hud.session import HudSession

logger = logging.getLogger(__name__)

DRAIN_INTERVAL_MS = 40   # how often queued events are pushed to the page


class HudPage(QWebEnginePage):
    """Web page that refuses to leave local content or open popups."""

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):  # noqa: N802 (Qt API)
        if url.isLocalFile() or url.scheme() in ("qrc", "about"):
            return super().acceptNavigationRequest(url, nav_type, is_main_frame)
        logger.warning("Blocked navigation to %s", url.toString())
        return False

    def createWindow(self, window_type):  # noqa: N802 (Qt API)
        return None


class HudBridge(QObject):
    """Object exposed to JavaScript as ``channel.objects.arceus``."""

    eventJson = Signal(str)   # Python -> JS: one JSON-encoded event

    def __init__(self, session: HudSession, window: "HudWindow") -> None:
        super().__init__()
        self._session = session
        self._window = window

    @Slot()
    def requestSnapshot(self) -> None:  # noqa: N802
        self._session.request_snapshot()

    @Slot(str)
    def submitText(self, text: str) -> None:  # noqa: N802
        self._session.submit_text(text)

    @Slot()
    def startVoice(self) -> None:  # noqa: N802
        self._session.start_voice()

    @Slot()
    def resetConversation(self) -> None:  # noqa: N802
        self._session.reset()

    @Slot()
    def toggleFullscreen(self) -> None:  # noqa: N802
        self._window.toggle_fullscreen()

    @Slot()
    def exitFullscreen(self) -> None:  # noqa: N802
        self._window.exit_fullscreen()

    @Slot()
    def quitApp(self) -> None:  # noqa: N802
        self._window.close()


class HudWindow(QMainWindow):
    def __init__(self, session: HudSession, pump: EventPump, index_html: Path, fullscreen: bool) -> None:
        super().__init__()
        self._session = session
        self._pump = pump
        self.setWindowTitle("ARCEUS")

        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.resize(int(area.width() * 0.85), int(area.height() * 0.85))

        self.view = QWebEngineView(self)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.page = HudPage(self.view)
        self.view.setPage(self.page)

        self.bridge = HudBridge(session, self)
        self.channel = QWebChannel(self.page)
        self.channel.registerObject("arceus", self.bridge)
        self.page.setWebChannel(self.channel)
        self.setCentralWidget(self.view)

        # Esc leaves full-screen, F11 toggles it, Ctrl+Q always quits.
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self).activated.connect(self.exit_fullscreen)
        QShortcut(QKeySequence(Qt.Key.Key_F11), self).activated.connect(self.toggle_fullscreen)
        QShortcut(QKeySequence("Ctrl+Q"), self).activated.connect(self.close)

        # Worker threads push events into the pump; this timer (GUI thread)
        # hands them to the page, so no Qt object is touched off-thread.
        self._timer = QTimer(self)
        self._timer.setInterval(DRAIN_INTERVAL_MS)
        self._timer.timeout.connect(self._drain)
        self._timer.start()

        self.view.load(QUrl.fromLocalFile(str(index_html)))
        if fullscreen:
            self.showFullScreen()
        else:
            self.show()

    def _drain(self) -> None:
        for payload in self._pump.drain():
            self.bridge.eventJson.emit(payload)

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def exit_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        self._timer.stop()
        self._session.shutdown()
        super().closeEvent(event)


def run(assistant: ArceusAssistant, config: ArceusConfig, fullscreen: bool, index_html: Path) -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("ARCEUS")

    pump = EventPump()
    session = HudSession(assistant, config, fullscreen=fullscreen)
    session.subscribe(pump.push)
    window = HudWindow(session, pump, index_html, fullscreen)
    app.aboutToQuit.connect(session.shutdown)
    session.start()
    code = app.exec()
    session.shutdown()
    del window
    return int(code)
