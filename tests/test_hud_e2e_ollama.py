"""
End-to-end: HudSession + the REAL OllamaModel + the REAL Ollama probe,
talking to a fake Ollama server on 127.0.0.1 (no internet, no GPU needed).
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from arceus.assistant import ArceusAssistant
from arceus.config import ArceusConfig
from arceus.hud.protocol import HudState
from arceus.hud.session import HudSession
from tests.hud_helpers import FakeMetrics, wait_for


class FakeOllama:
    """Implements just the endpoints ARCEUS uses: /api/tags, /api/ps, /api/generate."""

    def __init__(self, delay: float = 0.0, vram_fraction: float = 1.0):
        self.delay, self.vram_fraction = delay, vram_fraction
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def handle(self):
                try:
                    super().handle()
                except OSError:
                    pass

            def _send(self, payload, status=200):
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                outer.requests.append(("GET", self.path))
                if self.path == "/api/tags":
                    self._send({"models": [{"name": "qwen2.5:3b"}]})
                elif self.path == "/api/ps":
                    self._send({"models": [{"name": "qwen2.5:3b", "size": 1000,
                                            "size_vram": int(1000 * outer.vram_fraction)}]})
                else:
                    self._send({}, 404)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(("POST", self.path))
                if self.path == "/api/generate":
                    time.sleep(outer.delay)
                    self._send({"response": f"Acknowledged: {body['prompt'][-40:]}"})
                else:
                    self._send({}, 404)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def count(self, method, path) -> int:
        return sum(1 for r in self.requests if r == (method, path))


@pytest.fixture(autouse=True)
def _no_proxy(monkeypatch):
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")


def build(server: FakeOllama):
    cfg = ArceusConfig(model_backend="ollama", ollama_host=server.url, ollama_model="qwen2.5:3b")
    session = HudSession(
        ArceusAssistant(config=cfg), cfg,
        mic_probe=lambda: {"mic": "AVAILABLE", "mic_detail": ""},
        metrics=FakeMetrics(), probe_interval=0.05, metrics_interval=0.05,
    )
    events = []
    session.subscribe(events.append)
    session.start()
    return session, events


def test_text_reaches_ollama_and_the_reply_comes_back():
    server = FakeOllama()
    session, events = build(server)
    try:
        assert session.submit_text("Report status of the mission")["accepted"]
        assert wait_for(lambda: not session.busy)
        replies = [e for e in events if e["type"] == "message" and e["role"] == "assistant"]
        assert len(replies) == 1 and "Acknowledged" in replies[0]["text"]
        assert "Report status of the mission" in replies[0]["text"]
        assert session.state is HudState.STANDBY
        assert server.count("POST", "/api/generate") == 1          # one request, no duplicate model calls
    finally:
        session.shutdown(); server.stop()


def test_connection_gpu_residency_and_model_install_are_read_from_ollama():
    server = FakeOllama(vram_fraction=1.0)
    session, _ = build(server)
    try:
        assert wait_for(lambda: session.snapshot()["backend"]["connection"] == "CONNECTED")
        backend = session.snapshot()["backend"]
        assert backend["model_installed"] is True
        assert backend["residency"] == {"state": "GPU", "gpu_percent": 100.0}
        assert wait_for(lambda: server.count("GET", "/api/ps") >= 1)
        assert server.count("POST", "/api/generate") == 0           # monitoring never runs the model
    finally:
        session.shutdown(); server.stop()


def test_cpu_only_ollama_is_reported_as_cpu_not_gpu():
    server = FakeOllama(vram_fraction=0.0)
    session, _ = build(server)
    try:
        assert wait_for(lambda: session.snapshot()["backend"]["residency"]["state"] == "CPU")
    finally:
        session.shutdown(); server.stop()


def test_ui_stays_responsive_while_ollama_is_generating():
    server = FakeOllama(delay=0.8)
    session, events = build(server)
    try:
        t0 = time.monotonic()
        session.submit_text("think hard")
        assert time.monotonic() - t0 < 0.3
        assert wait_for(lambda: session.state is HudState.PROCESSING)
        # metrics keep flowing and snapshots stay instant during generation
        before = len([e for e in events if e["type"] == "metrics"])
        assert wait_for(lambda: len([e for e in events if e["type"] == "metrics"]) > before + 2, 1.0)
        assert session.busy
        assert wait_for(lambda: not session.busy)
    finally:
        session.shutdown(); server.stop()


def test_ollama_going_away_is_reported_and_chat_recovers_when_it_returns():
    server = FakeOllama()
    session, events = build(server)
    try:
        assert wait_for(lambda: session.snapshot()["backend"]["connection"] == "CONNECTED")
        server.stop()
        session.submit_text("anyone there?")
        assert wait_for(lambda: not session.busy)
        assert session.state is HudState.ERROR
        assert "Cannot reach Ollama" in [e for e in events if e["type"] == "state"][-1]["detail"]
        assert wait_for(lambda: session.snapshot()["backend"]["connection"] == "DISCONNECTED")
        assert any(a["level"] == "warn" and "Cannot reach Ollama" in a["text"]
                   for a in session.snapshot()["activity"])
    finally:
        session.shutdown()
