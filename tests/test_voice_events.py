"""The voice controller's event hooks (used by the HUD) and their safety."""

from __future__ import annotations

import pytest

from arceus.assistant import ArceusAssistant
from arceus.config import ArceusConfig
from arceus.exceptions import AudioDeviceError, SpeechRecognitionError, SpeechSynthesisError
from arceus.voice.controller import VoiceConversationController
from arceus.voice.stt import MockSpeechRecognizer
from arceus.voice.tts import MockSpeechSynthesizer
from tests.hud_helpers import make_wav


class Recorder:
    def __init__(self, fail=None):
        self.fail = fail

    def record(self, duration=5.0):
        if self.fail:
            raise self.fail
        return make_wav(1000)


def build(responses=None, recorder=None, on_event="collect"):
    cfg = ArceusConfig(model_backend="echo")
    events = []
    hook = (lambda name, data: events.append((name, data))) if on_event == "collect" else on_event
    ctl = VoiceConversationController(
        assistant=ArceusAssistant(config=cfg),
        recorder=recorder or Recorder(),
        recognizer=MockSpeechRecognizer(cfg, responses or ["hello arceus"]),
        synthesizer=MockSpeechSynthesizer(cfg),
        config=cfg, input_func=lambda _p="": "", output_func=lambda *a, **k: None, on_event=hook,
    )
    return ctl, events


def names(events):
    return [n for n, _ in events]


def test_successful_turn_emits_the_full_pipeline_in_order():
    ctl, events = build()
    assert ctl.run_turn() is True
    assert names(events) == ["listening_started", "captured", "transcribing", "transcribed",
                             "thinking", "reply", "speaking_started", "speaking_finished"]
    data = dict(events)
    assert data["transcribed"]["text"] == "hello arceus"
    assert "hello arceus" in data["reply"]["text"]
    assert data["captured"]["wav_bytes"].startswith(b"RIFF")


def test_microphone_failure_stops_the_turn_with_an_error_event():
    ctl, events = build(recorder=Recorder(AudioDeviceError("No active microphone")))
    assert ctl.run_turn() is True
    assert names(events) == ["listening_started", "error"]
    assert dict(events)["error"] == {"stage": "audio", "message": "No active microphone"}


def test_unintelligible_speech_emits_error_and_empty_speech_emits_notice():
    ctl, events = build(["__ERROR__ Could not understand the audio."])
    ctl.run_turn()
    assert names(events)[-1] == "error" and dict(events)["error"]["stage"] == "speech"
    ctl, events = build(["   "])
    ctl.run_turn()
    assert names(events)[-1] == "notice"


def test_tts_failure_still_closes_the_speaking_phase():
    ctl, events = build()
    ctl.synthesizer.fail_next = "SAPI exploded"
    ctl.run_turn()
    assert names(events)[-3:] == ["speaking_started", "error", "speaking_finished"]
    assert dict(events)["error"]["stage"] == "speech_output"


def test_spoken_exit_command_is_reported_and_ends_the_session():
    ctl, events = build(["quit"])
    assert ctl.run_turn() is False
    assert "exit_requested" in names(events)


def test_a_crashing_observer_cannot_break_the_pipeline():
    def bad(name, data):
        raise RuntimeError("observer bug")

    ctl, _ = build(on_event=bad)
    assert ctl.run_turn() is True
    assert ctl.synthesizer.spoken_texts          # the reply was still spoken


def test_without_an_observer_behaviour_is_unchanged():
    ctl, _ = build(on_event=None)
    assert ctl.run_turn() is True and ctl.synthesizer.spoken_texts
