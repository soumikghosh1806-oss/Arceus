"""HudSession: threading, state flow, error handling and event contract."""

from __future__ import annotations

import threading
import time

import pytest

from arceus.exceptions import ModelConnectionError, SpeechRecognitionError
from arceus.hud.protocol import MAX_INPUT_CHARS, HudState
from tests.hud_helpers import Harness, make_wav, wait_for


@pytest.fixture
def h():
    harness = Harness()
    yield harness
    harness.close()


class TestTextTurn:
    def test_events_arrive_in_order_with_real_reply(self, h):
        assert h.session.submit_text("hello") == {"accepted": True, "reason": ""}
        assert h.idle()
        kinds = [(e["type"], e.get("role") or e.get("state")) for e in h.events]
        assert kinds == [
            ("message", "user"),
            ("state", "PROCESSING"),
            ("message", "assistant"),
            ("state", "STANDBY"),
        ]
        assert h.of("message")[1]["text"] == "reply to: hello"
        seqs = [e["seq"] for e in h.events]
        assert seqs == sorted(set(seqs))  # strictly increasing

    def test_submit_returns_immediately_and_ui_stays_responsive_during_generation(self):
        gate = threading.Event()
        h = Harness(gate=gate)
        try:
            t0 = time.monotonic()
            assert h.session.submit_text("slow one")["accepted"]
            assert time.monotonic() - t0 < 0.5          # did not wait for the model
            assert h.model.entered.wait(2)
            assert h.session.state is HudState.PROCESSING and h.session.busy
            snap_t0 = time.monotonic()
            assert h.session.snapshot()["busy"] is True  # still answers while blocked
            assert time.monotonic() - snap_t0 < 0.2
            gate.set()
            assert h.idle()
            assert h.session.state is HudState.STANDBY
        finally:
            gate.set()
            h.close()

    def test_second_message_is_rejected_while_busy(self):
        gate = threading.Event()
        h = Harness(gate=gate)
        try:
            h.session.submit_text("first")
            assert h.model.entered.wait(2)
            result = h.session.submit_text("second")
            assert result == {"accepted": False, "reason": "busy"}
            gate.set()
            assert h.idle()
            assert h.model.calls == 1
            assert [m["text"] for m in h.session.snapshot()["messages"] if m["role"] == "user"] == ["first"]
        finally:
            gate.set()
            h.close()

    @pytest.mark.parametrize("bad", ["", "   \n\t ", None, 42, ["x"]])
    def test_empty_or_invalid_input_never_reaches_the_model(self, h, bad):
        assert h.session.submit_text(bad)["accepted"] is False
        assert h.model.calls == 0 and not h.session.busy

    def test_overlong_input_is_rejected_with_a_visible_warning(self, h):
        result = h.session.submit_text("x" * (MAX_INPUT_CHARS + 1))
        assert result == {"accepted": False, "reason": "too_long"}
        assert h.of("activity")[-1]["level"] == "warn"
        assert h.model.calls == 0


class TestErrors:
    def test_backend_error_shows_error_state_then_recovers(self):
        h = Harness(outcomes=[ModelConnectionError("Cannot reach Ollama at http://localhost:11434.")])
        try:
            h.session.submit_text("hi")
            assert h.idle()
            assert h.session.state is HudState.ERROR
            err_state = h.of("state")[-1]
            assert "Cannot reach Ollama" in err_state["detail"] and err_state["busy"] is False
            assert h.of("activity")[-1]["level"] == "error"
            assert h.session.submit_text("again")["accepted"]
            assert h.idle()
            assert h.session.state is HudState.STANDBY
        finally:
            h.close()

    def test_unexpected_exception_is_contained(self):
        h = Harness(outcomes=[RuntimeError("boom")])
        try:
            h.session.submit_text("hi")
            assert h.idle()
            assert h.session.state is HudState.ERROR
            assert "boom" in h.of("state")[-1]["detail"]
            assert h.session.submit_text("still works")["accepted"]
        finally:
            h.close()

    def test_a_failing_subscriber_cannot_break_the_session(self, h):
        h.session.subscribe(lambda event: 1 / 0)
        h.session.submit_text("hi")
        assert h.idle()
        assert h.session.state is HudState.STANDBY


class TestResetAndSnapshot:
    def test_reset_clears_history_and_transcript(self, h):
        h.session.submit_text("hello")
        assert h.idle()
        assert h.session.reset()["accepted"]
        assert h.assistant.turn_count == 0
        assert h.session.snapshot()["messages"] == []
        assert h.of("reset")

    def test_reset_is_refused_while_busy(self):
        gate = threading.Event()
        h = Harness(gate=gate)
        try:
            h.session.submit_text("hi")
            assert h.model.entered.wait(2)
            assert h.session.reset() == {"accepted": False, "reason": "busy"}
            gate.set()
            assert h.idle()
            assert h.assistant.turn_count == 1
        finally:
            gate.set()
            h.close()

    def test_fresh_session_contains_no_invented_data(self, h):
        snap = h.session.snapshot()
        assert snap["messages"] == [] and snap["activity"] == []
        assert snap["state"] == "STANDBY" and snap["busy"] is False
        assert snap["metrics"]["cpu_percent"] is None      # nothing sampled yet -> N/A
        assert snap["backend"]["connection"] == "N/A"      # echo backend has no connection

    def test_snapshot_carries_history_and_the_latest_seq(self, h):
        h.session.submit_text("hello")
        assert h.idle()
        h.events.clear()
        h.session.request_snapshot()
        snap = h.of("snapshot")[0]
        assert [m["role"] for m in snap["messages"]] == ["user", "assistant"]
        assert snap["seq"] == h.events[-1]["seq"]


class TestVoice:
    SCRIPT = [
        ("listening_started", {"duration": 5.0}),
        ("captured", {"wav_bytes": make_wav(8000)}),
        ("transcribing", {}),
        ("transcribed", {"text": "what time is it"}),
        ("thinking", {}),
        ("reply", {"text": "It is noon."}),
        ("speaking_started", {}),
        ("speaking_finished", {}),
    ]

    def test_states_follow_real_pipeline_events(self):
        h = Harness(voice_script=self.SCRIPT)
        try:
            assert h.session.start_voice()["accepted"]
            assert h.idle()
            seen = dict(h.voice_states)
            assert seen["listening_started"] == "LISTENING"
            assert seen["transcribing"] == "PROCESSING"
            assert seen["thinking"] == "PROCESSING"
            assert seen["speaking_started"] == "SPEAKING"
            assert h.session.state is HudState.STANDBY       # SPEAKING ended with the turn
            msgs = h.session.snapshot()["messages"]
            assert [(m["role"], m["source"]) for m in msgs] == [("user", "voice"), ("assistant", "voice")]
        finally:
            h.close()

    def test_listening_is_never_shown_before_capture_really_starts(self):
        h = Harness(voice_script=self.SCRIPT)
        try:
            h.session.start_voice()
            h.idle()
            first_states = [e["state"] for e in h.of("state")][:2]
            assert first_states == ["PROCESSING", "PROCESSING"]   # preparing / loading, not LISTENING
        finally:
            h.close()

    def test_capture_level_is_measured_from_the_audio(self):
        loud = [("captured", {"wav_bytes": make_wav(16384)})]
        quiet = [("captured", {"wav_bytes": make_wav(0)})]
        for script, expect_silent in ((loud, False), (quiet, True)):
            h = Harness(voice_script=script)
            try:
                h.session.start_voice()
                assert h.idle()
                level = h.session.snapshot()["devices"]["last_capture"]
                assert (level["peak_dbfs"] <= -60) is expect_silent
                if not expect_silent:
                    assert -7 < level["peak_dbfs"] < -5       # 16384/32768 = -6.0 dBFS
                warned = any("silent" in a["text"] for a in h.of("activity"))
                assert warned is expect_silent
            finally:
                h.close()

    def test_voice_error_is_shown_as_error_state(self):
        script = [("listening_started", {"duration": 5.0}),
                  ("error", {"stage": "audio", "message": "No active microphone detected."})]
        h = Harness(voice_script=script)
        try:
            h.session.start_voice()
            assert h.idle()
            assert h.session.state is HudState.ERROR
            assert "Microphone: No active microphone" in h.of("state")[-1]["detail"]
        finally:
            h.close()

    def test_no_speech_is_a_warning_not_an_error(self):
        h = Harness(voice_script=[("notice", {"message": "No speech detected. Please try again."})])
        try:
            h.session.start_voice()
            assert h.idle()
            assert h.session.state is HudState.STANDBY
            assert h.of("activity")[-1]["level"] == "warn"
        finally:
            h.close()

    def test_voice_pipeline_failure_leaves_text_chat_working(self):
        def broken_factory(assistant, config, on_event):
            raise SpeechRecognitionError("Vosk model directory not found.")

        h = Harness(voice_factory=broken_factory)
        try:
            h.session.start_voice()
            assert h.idle()
            assert h.session.state is HudState.ERROR
            assert "Voice unavailable" in h.of("state")[-1]["detail"]
            assert h.session.submit_text("hello")["accepted"]
            assert h.idle()
            assert h.session.state is HudState.STANDBY
        finally:
            h.close()

    def test_two_voice_sessions_can_never_overlap(self):
        gate = threading.Event()
        h = Harness(voice_script=[], voice_block=gate)
        try:
            assert h.session.start_voice()["accepted"]
            assert wait_for(lambda: h.voice is not None and h.voice.turns == 1)
            assert h.session.start_voice() == {"accepted": False, "reason": "busy"}
            assert h.session.submit_text("typed meanwhile") == {"accepted": False, "reason": "busy"}
            gate.set()
            assert h.idle()
            assert h.voice.turns == 1
        finally:
            gate.set()
            h.close()

    def test_voice_pipeline_is_built_once_and_engines_are_reported(self):
        h = Harness(voice_script=[])
        try:
            h.session.start_voice(); assert h.idle()
            h.session.start_voice(); assert h.idle()
            assert h.voice_factory_calls == 1 and h.voice.turns == 2
            info = h.session.snapshot()["voice"]
            assert info["loaded"] and info["stt_engine"] == "VOSK (OFFLINE)"
            assert info["tts_engine"] == "PYTTSX3 / WINDOWS SAPI5"
        finally:
            h.close()

    def test_shutdown_releases_the_voice_pipeline(self):
        h = Harness(voice_script=[])
        h.session.start_voice(); assert h.idle()
        h.close()
        assert wait_for(lambda: h.voice.cleaned_up)


class TestMonitoring:
    def test_backend_connection_changes_are_reported_and_logged(self):
        results = iter([
            {"connection": "DISCONNECTED", "model_installed": None,
             "residency": {"state": "N/A", "gpu_percent": None}, "error": "Cannot reach Ollama at http://localhost:11434."},
            {"connection": "CONNECTED", "model_installed": True,
             "residency": {"state": "GPU", "gpu_percent": 100.0}, "error": ""},
        ])
        last = {}

        def probe(host, model):
            last.update(next(results, last))
            return dict(last)

        h = Harness(model_backend="ollama", monitor=True, probe_interval=0.05,
                    metrics_interval=0.05, ollama_probe=probe)
        try:
            assert wait_for(lambda: h.session.snapshot()["backend"]["connection"] == "CONNECTED")
            texts = [a["text"] for a in h.of("activity")]
            assert any("Cannot reach Ollama" in t for t in texts)
            assert any("LOCAL AI connected" in t for t in texts)
            assert h.session.snapshot()["backend"]["residency"]["state"] == "GPU"
        finally:
            h.close()

    def test_metrics_and_microphone_are_published(self):
        h = Harness(monitor=True, probe_interval=0.05, metrics_interval=0.05)
        try:
            assert wait_for(lambda: h.of("metrics") and h.of("devices"))
            m = h.of("metrics")[-1]
            assert m["cpu_percent"] == 12.5 and m["ram_total_gb"] == 24.0 and m["uptime_s"] >= 0
            assert h.session.snapshot()["devices"]["mic"] == "AVAILABLE"
        finally:
            h.close()

    def test_backend_labels_follow_the_configured_backend(self):
        for backend, label in (("echo", "ECHO TEST"), ("local", "LOCAL AI"), ("openai", "HOSTED AI")):
            h = Harness(model_backend=backend)
            try:
                info = h.session.snapshot()["backend"]
                assert info["label"] == label
            finally:
                h.close()

    def test_hosted_backend_uses_the_models_own_health_check(self):
        h = Harness(model_backend="openai", monitor=True, healthy=False)
        try:
            assert wait_for(lambda: h.session.snapshot()["backend"]["connection"] == "DISCONNECTED")
        finally:
            h.close()

    def test_shutdown_stops_all_threads(self):
        h = Harness(monitor=True, probe_interval=0.05, metrics_interval=0.05)
        h.close()
        names = {t.name for t in threading.enumerate()}
        assert not {n for n in names if n.startswith("arceus-hud")}
        h.close()  # idempotent
