"""
ARCEUS HUD — full-screen mission-control interface.

Layout of this package (only ``qt_shell`` needs PySide6):

* ``protocol``  – state names, event types and limits shared with the web UI
* ``metrics``   – real CPU / RAM / audio-level measurements (stdlib only)
* ``probes``    – Ollama connection, model residency and microphone checks
* ``session``   – ``HudSession``: runs the assistant off the UI thread and
                  publishes events; knows nothing about Qt or HTML
* ``pump``      – thread-safe event queue drained by the UI thread
* ``qt_shell``  – PySide6 + QtWebEngine window and QWebChannel bridge
* ``app``       – ``run_hud()`` entry point used by ``main.py --hud``
* ``web/``      – HTML / CSS / JavaScript front-end
"""
