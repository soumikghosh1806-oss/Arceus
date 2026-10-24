"""Probes, metrics maths and the event pump."""

from __future__ import annotations

import json

import pytest

from arceus.hud import metrics, probes
from arceus.hud.pump import EventPump
from tests.hud_helpers import make_wav


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


def fake_get(routes):
    """http_get stand-in: *routes* maps path suffix -> FakeResponse or Exception."""
    def get(url, timeout=0):
        for suffix, result in routes.items():
            if url.endswith(suffix):
                if isinstance(result, Exception):
                    raise result
                return result
        raise AssertionError(f"unexpected URL {url}")
    return get


TAGS = FakeResponse(200, {"models": [{"name": "qwen2.5:3b"}, {"name": "llama3:latest"}]})


class TestOllamaProbe:
    def test_gpu_resident_model(self):
        ps = FakeResponse(200, {"models": [{"name": "qwen2.5:3b", "size": 4_000, "size_vram": 4_000}]})
        r = probes.probe_ollama("http://localhost:11434", "qwen2.5:3b", http_get=fake_get({"/api/tags": TAGS, "/api/ps": ps}))
        assert r["connection"] == "CONNECTED" and r["model_installed"] is True
        assert r["residency"] == {"state": "GPU", "gpu_percent": 100.0}

    def test_cpu_only_and_split_are_distinguished(self):
        for vram, state, pct in ((0, "CPU", 0.0), (1_000, "SPLIT", 25.0)):
            ps = FakeResponse(200, {"models": [{"name": "qwen2.5:3b", "size": 4_000, "size_vram": vram}]})
            r = probes.probe_ollama("http://h", "qwen2.5:3b", http_get=fake_get({"/api/tags": TAGS, "/api/ps": ps}))
            assert r["residency"] == {"state": state, "gpu_percent": pct}

    def test_model_not_loaded_is_idle_not_gpu(self):
        ps = FakeResponse(200, {"models": []})
        r = probes.probe_ollama("http://h", "qwen2.5:3b", http_get=fake_get({"/api/tags": TAGS, "/api/ps": ps}))
        assert r["residency"]["state"] == "IDLE"

    def test_unreachable_server(self):
        err = ConnectionError("refused")
        r = probes.probe_ollama("http://h:1", "qwen2.5:3b", http_get=fake_get({"/api/tags": err}))
        assert r["connection"] == "DISCONNECTED" and "Cannot reach Ollama" in r["error"]
        assert r["residency"]["state"] == "N/A"

    def test_http_error_is_not_connected(self):
        r = probes.probe_ollama("http://h", "m", http_get=fake_get({"/api/tags": FakeResponse(500)}))
        assert r["connection"] == "DISCONNECTED" and "500" in r["error"]

    def test_residency_failure_stays_na(self):
        r = probes.probe_ollama("http://h", "qwen2.5:3b",
                                http_get=fake_get({"/api/tags": TAGS, "/api/ps": ConnectionError("x")}))
        assert r["connection"] == "CONNECTED" and r["residency"]["state"] == "N/A"

    def test_missing_model_and_latest_tag_matching(self):
        ps = FakeResponse(200, {"models": []})
        routes = {"/api/tags": TAGS, "/api/ps": ps}
        assert probes.probe_ollama("http://h", "nope:1b", http_get=fake_get(routes))["model_installed"] is False
        assert probes.probe_ollama("http://h", "llama3", http_get=fake_get(routes))["model_installed"] is True

    def test_classify_residency_edge_cases(self):
        assert probes.classify_residency(None, None)["state"] == "N/A"
        assert probes.classify_residency(0, 0)["state"] == "N/A"


class TestMetrics:
    def test_cpu_percent_between_samples(self):
        assert metrics.cpu_percent_between((100, 1000), (150, 1200)) == 75.0
        assert metrics.cpu_percent_between((0, 0), (0, 0)) is None          # no time elapsed
        assert metrics.cpu_percent_between((10, 100), (5, 200)) is None     # counter went backwards

    def test_wav_levels_are_real_measurements(self):
        assert metrics.wav_levels(make_wav(0))["peak_dbfs"] == -96.0
        half = metrics.wav_levels(make_wav(16384))
        assert half["peak_dbfs"] == pytest.approx(-6.0, abs=0.1)
        assert half["rms_dbfs"] == pytest.approx(-6.0, abs=0.1)
        assert metrics.wav_levels(b"not a wav file") is None
        assert metrics.wav_levels(make_wav(100, frames=0)) is None

    def test_system_metrics_returns_real_numbers_or_none(self):
        sample = metrics.SystemMetrics().sample()
        assert set(sample) == {"cpu_percent", "ram_used_gb", "ram_total_gb", "ram_percent"}
        for key, value in sample.items():
            assert value is None or value >= 0
        if sample["ram_total_gb"] is not None:
            assert sample["ram_used_gb"] <= sample["ram_total_gb"]
            assert 0 <= sample["ram_percent"] <= 100


class TestEventPump:
    def test_drain_returns_json_in_order_and_empties(self):
        pump = EventPump()
        pump.push({"type": "message", "seq": 1, "text": "héllo"})
        pump.push({"type": "state", "seq": 2})
        out = pump.drain()
        assert [json.loads(x)["seq"] for x in out] == [1, 2]
        assert "héllo" in out[0]                     # not ASCII-escaped
        assert pump.drain() == []

    def test_only_the_newest_metrics_event_is_kept(self):
        pump = EventPump()
        for i in range(5):
            pump.push({"type": "metrics", "seq": i, "cpu_percent": i})
        pump.push({"type": "message", "seq": 9})
        events = [json.loads(x) for x in pump.drain()]
        assert [(e["type"], e["seq"]) for e in events] == [("metrics", 4), ("message", 9)]
