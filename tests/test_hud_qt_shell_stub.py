"""
Checks the Qt shell's wiring with *fake* PySide6 modules, so it runs on any
machine (and never opens a window).  A real Qt run still needs a manual check.
"""

from __future__ import annotations

import sys
import types

import pytest


class _Signal:
    def __init__(self, *types_):
        self._slots = []

    def connect(self, fn):
        self._slots.append(fn)

    def emit(self, *args):
        for fn in self._slots:
            fn(*args)


class _Page:
    def __init__(self, parent=None):
        pass

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        return True


class _Url:
    def __init__(self, text):
        self._text = text

    def isLocalFile(self):
        return self._text.startswith("file://")

    def scheme(self):
        return self._text.split(":", 1)[0]

    def toString(self):
        return self._text


def _module(name, **attrs):
    mod = types.ModuleType(name)
    mod.__dict__.update(attrs)
    return mod


@pytest.fixture
def qt_shell(monkeypatch):
    class _Obj:
        def __init__(self, *a, **k):
            pass

    fakes = {
        "PySide6": _module("PySide6", __path__=[]),
        "PySide6.QtCore": _module("PySide6.QtCore", QObject=_Obj, Qt=_Obj, QTimer=_Obj, QUrl=_Obj,
                                  Signal=_Signal, Slot=lambda *a, **k: (lambda fn: fn)),
        "PySide6.QtGui": _module("PySide6.QtGui", QGuiApplication=_Obj, QKeySequence=_Obj, QShortcut=_Obj),
        "PySide6.QtWebChannel": _module("PySide6.QtWebChannel", QWebChannel=_Obj),
        "PySide6.QtWebEngineCore": _module("PySide6.QtWebEngineCore", QWebEnginePage=_Page),
        "PySide6.QtWebEngineWidgets": _module("PySide6.QtWebEngineWidgets", QWebEngineView=_Obj),
        "PySide6.QtWidgets": _module("PySide6.QtWidgets", QApplication=_Obj, QMainWindow=_Obj),
    }
    for name, mod in fakes.items():
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.delitem(sys.modules, "arceus.hud.qt_shell", raising=False)
    import arceus.hud.qt_shell as shell

    yield shell
    sys.modules.pop("arceus.hud.qt_shell", None)   # never leak the fake-backed module into other tests


class FakeSession:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *a: self.calls.append((name, *a))


class FakeWindow:
    def __init__(self):
        self.calls = []

    def toggle_fullscreen(self):
        self.calls.append("toggle")

    def exit_fullscreen(self):
        self.calls.append("exit")

    def close(self):
        self.calls.append("close")


def test_bridge_slots_delegate_to_the_session_and_window(qt_shell):
    session, window = FakeSession(), FakeWindow()
    bridge = qt_shell.HudBridge(session, window)
    bridge.requestSnapshot()
    bridge.submitText("hello")
    bridge.startVoice()
    bridge.resetConversation()
    bridge.toggleFullscreen()
    bridge.exitFullscreen()
    bridge.quitApp()
    assert session.calls == [("request_snapshot",), ("submit_text", "hello"), ("start_voice",), ("reset",)]
    assert window.calls == ["toggle", "exit", "close"]


def test_bridge_signal_carries_json_text_to_the_page(qt_shell):
    bridge = qt_shell.HudBridge(FakeSession(), FakeWindow())
    received = []
    bridge.eventJson.connect(received.append)
    bridge.eventJson.emit('{"type": "state"}')
    assert received == ['{"type": "state"}']


def test_page_only_navigates_to_local_content_and_never_opens_windows(qt_shell):
    page = qt_shell.HudPage()
    assert page.acceptNavigationRequest(_Url("file:///C:/arceus/index.html"), 0, True) is True
    assert page.acceptNavigationRequest(_Url("qrc:///qtwebchannel/qwebchannel.js"), 0, True) is True
    assert page.acceptNavigationRequest(_Url("https://example.com/"), 0, True) is False
    assert page.acceptNavigationRequest(_Url("http://127.0.0.1:8000/"), 0, True) is False
    assert page.createWindow(0) is None
