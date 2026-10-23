"""
Unit tests for the ARCEUS voice pipeline.

Mocks all hardware (mic, speakers), network, and speech models.
Runs 100% offline and requires no physical audio devices.
"""

from __future__ import annotations

import io
import wave
import pytest

from arceus.assistant import ArceusAssistant
from arceus.config import ArceusConfig
from arceus.exceptions import (
    AudioDeviceError,
    ModelError,
    SpeechRecognitionError,
    SpeechSynthesisError,
)
from arceus.voice.audio_input import AudioRecorder
from arceus.voice.controller import VoiceConversationController
from arceus.voice.stt import (
    MockSpeechRecognizer,
    SpeechRecognizerInterface,
    create_recognizer,
)
from arceus.voice.tts import (
    MockSpeechSynthesizer,
    SpeechSynthesizerInterface,
    create_synthesizer,
)


def _generate_dummy_wav() -> bytes:
    """Helper to generate a minimal valid 16kHz mono WAV buffer in-memory."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 1600)  # 0.1s of silence
    return buf.getvalue()


class DummyRecorder:
    """Mock audio recorder returning valid dummy WAV bytes."""

    def __init__(self, should_fail: bool = False, error_msg: str = "Mic error") -> None:
        self.should_fail = should_fail
        self.error_msg = error_msg
        self.record_called = 0

    def record(self, duration: float = 5.0) -> bytes:
        self.record_called += 1
        if self.should_fail:
            raise AudioDeviceError(self.error_msg)
        return _generate_dummy_wav()


@pytest.fixture
def dummy_assistant():
    """Create an ArceusAssistant in echo mode."""
    cfg = ArceusConfig(model_backend="echo")
    return ArceusAssistant(config=cfg)


# ── Scenario 1, 2, 3: Successful conversation, text passing, speech output ───
class TestVoiceSuccessfulTurn:
    def test_single_successful_turn(self, dummy_assistant):
        cfg = ArceusConfig(model_backend="echo")
        recorder = DummyRecorder()
        recognizer = MockSpeechRecognizer(cfg, responses=["Hello ARCEUS"])
        synthesizer = MockSpeechSynthesizer(cfg)

        printed_messages = []
        inputs = [""]  # user presses Enter once

        controller = VoiceConversationController(
            assistant=dummy_assistant,
            recorder=recorder,
            recognizer=recognizer,
            synthesizer=synthesizer,
            config=cfg,
            input_func=lambda _: inputs.pop(0),
            output_func=printed_messages.append,
        )

        should_continue = controller.step()
        assert should_continue is True
        assert recorder.record_called == 1
        assert recognizer.call_count == 1

        # Check that user speech reached the assistant and was echoed
        assert any("You (Voice) ➤ Hello ARCEUS" in msg for msg in printed_messages)
        assert any("[ARCEUS echo] Hello ARCEUS" in msg for msg in printed_messages)

        # Check speech synthesis received the assistant's reply
        assert len(synthesizer.spoken_texts) == 1
        assert "[ARCEUS echo] Hello ARCEUS" in synthesizer.spoken_texts[0]


# ── Scenario 4: Repeated conversations in a single session ───────────────────
class TestRepeatedConversations:
    def test_multi_turn_session(self, dummy_assistant):
        cfg = ArceusConfig(model_backend="echo")
        recorder = DummyRecorder()
        recognizer = MockSpeechRecognizer(cfg, responses=["Turn 1 text", "Turn 2 text"])
        synthesizer = MockSpeechSynthesizer(cfg)

        printed_messages = []
        inputs = ["", "", "exit"]  # 2 turns then exit

        controller = VoiceConversationController(
            assistant=dummy_assistant,
            recorder=recorder,
            recognizer=recognizer,
            synthesizer=synthesizer,
            config=cfg,
            input_func=lambda _: inputs.pop(0),
            output_func=printed_messages.append,
        )

        # Turn 1
        cont1 = controller.step()
        assert cont1 is True
        # Turn 2
        cont2 = controller.step()
        assert cont2 is True
        # Exit turn
        cont3 = controller.step()
        assert cont3 is False

        assert recorder.record_called == 2
        assert len(synthesizer.spoken_texts) == 2
        assert "Turn 1 text" in synthesizer.spoken_texts[0]
        assert "Turn 2 text" in synthesizer.spoken_texts[1]
        assert dummy_assistant.turn_count == 2

    def test_first_interaction_invokes_tts(self, dummy_assistant):
        """Verify the first voice turn delivers assistant response to TTS."""
        cfg = ArceusConfig(model_backend="echo")
        recorder = DummyRecorder()
        recognizer = MockSpeechRecognizer(cfg, responses=["First turn question"])
        synthesizer = MockSpeechSynthesizer(cfg)

        controller = VoiceConversationController(
            assistant=dummy_assistant,
            recorder=recorder,
            recognizer=recognizer,
            synthesizer=synthesizer,
            config=cfg,
            input_func=lambda _: "",
            output_func=lambda _: None,
        )

        assert controller.step() is True
        assert len(synthesizer.spoken_texts) == 1
        assert "First turn question" in synthesizer.spoken_texts[0]

    def test_second_interaction_invokes_tts(self, dummy_assistant):
        """Verify the second voice turn delivers assistant response to TTS."""
        cfg = ArceusConfig(model_backend="echo")
        recorder = DummyRecorder()
        recognizer = MockSpeechRecognizer(cfg, responses=["First turn", "Second turn"])
        synthesizer = MockSpeechSynthesizer(cfg)

        controller = VoiceConversationController(
            assistant=dummy_assistant,
            recorder=recorder,
            recognizer=recognizer,
            synthesizer=synthesizer,
            config=cfg,
            input_func=lambda _: "",
            output_func=lambda _: None,
        )

        assert controller.step() is True
        assert len(synthesizer.spoken_texts) == 1
        assert controller.step() is True
        assert len(synthesizer.spoken_texts) == 2
        assert "Second turn" in synthesizer.spoken_texts[1]

    def test_at_least_three_consecutive_responses_invoke_tts(self, dummy_assistant):
        """Verify at least 3 consecutive assistant responses invoke TTS successfully."""
        cfg = ArceusConfig(model_backend="echo")
        recorder = DummyRecorder()
        turn_inputs = ["Alpha", "Beta", "Gamma", "Delta"]
        recognizer = MockSpeechRecognizer(cfg, responses=list(turn_inputs))
        synthesizer = MockSpeechSynthesizer(cfg)

        controller = VoiceConversationController(
            assistant=dummy_assistant,
            recorder=recorder,
            recognizer=recognizer,
            synthesizer=synthesizer,
            config=cfg,
            input_func=lambda _: "",
            output_func=lambda _: None,
        )

        for i, word in enumerate(turn_inputs):
            assert controller.step() is True
            assert len(synthesizer.spoken_texts) == i + 1
            assert word in synthesizer.spoken_texts[i]


# ── Scenario 5: Empty or unintelligible transcription ────────────────────────
class TestUnintelligibleSpeech:
    def test_empty_transcription(self, dummy_assistant):
        cfg = ArceusConfig(model_backend="echo")
        recorder = DummyRecorder()
        recognizer = MockSpeechRecognizer(cfg, responses=[""])  # empty
        synthesizer = MockSpeechSynthesizer(cfg)

        printed_messages = []
        controller = VoiceConversationController(
            assistant=dummy_assistant,
            recorder=recorder,
            recognizer=recognizer,
            synthesizer=synthesizer,
            config=cfg,
            input_func=lambda _: "",
            output_func=printed_messages.append,
        )

        cont = controller.step()
        assert cont is True
        assert any("No speech detected" in msg for msg in printed_messages)
        # Assistant must NOT have been called
        assert dummy_assistant.turn_count == 0
        assert len(synthesizer.spoken_texts) == 0


# ── Scenario 6: Microphone failure ──────────────────────────────────────────
class TestMicrophoneFailure:
    def test_microphone_error_handled_gracefully(self, dummy_assistant):
        cfg = ArceusConfig(model_backend="echo")
        recorder = DummyRecorder(should_fail=True, error_msg="Device not found")
        recognizer = MockSpeechRecognizer(cfg, responses=["Some text"])
        synthesizer = MockSpeechSynthesizer(cfg)

        printed_messages = []
        controller = VoiceConversationController(
            assistant=dummy_assistant,
            recorder=recorder,
            recognizer=recognizer,
            synthesizer=synthesizer,
            config=cfg,
            input_func=lambda _: "",
            output_func=printed_messages.append,
        )

        cont = controller.step()
        # Should inform the user and not crash
        assert cont is True
        assert any("Audio Error" in msg for msg in printed_messages)
        assert dummy_assistant.turn_count == 0


# ── Scenario 7: Speech recognition failure ──────────────────────────────────
class TestSpeechRecognitionFailure:
    def test_stt_exception_handled(self, dummy_assistant):
        cfg = ArceusConfig(model_backend="echo")
        recorder = DummyRecorder()
        recognizer = MockSpeechRecognizer(cfg, responses=["__ERROR__Failed to recognize audio"])
        synthesizer = MockSpeechSynthesizer(cfg)

        printed_messages = []
        controller = VoiceConversationController(
            assistant=dummy_assistant,
            recorder=recorder,
            recognizer=recognizer,
            synthesizer=synthesizer,
            config=cfg,
            input_func=lambda _: "",
            output_func=printed_messages.append,
        )

        cont = controller.step()
        assert cont is True
        assert any("Speech Error" in msg for msg in printed_messages)
        assert dummy_assistant.turn_count == 0


# ── Scenario 8: AI-provider failure ─────────────────────────────────────────
class FailingAssistant(ArceusAssistant):
    def chat(self, user_input: str) -> str:
        raise ModelError("Remote model timeout")


class TestAIProviderFailure:
    def test_model_error_does_not_crash_loop(self):
        cfg = ArceusConfig(model_backend="echo")
        failing_assistant = FailingAssistant(config=cfg)
        recorder = DummyRecorder()
        recognizer = MockSpeechRecognizer(cfg, responses=["Hello"])
        synthesizer = MockSpeechSynthesizer(cfg)

        printed_messages = []
        controller = VoiceConversationController(
            assistant=failing_assistant,
            recorder=recorder,
            recognizer=recognizer,
            synthesizer=synthesizer,
            config=cfg,
            input_func=lambda _: "",
            output_func=printed_messages.append,
        )

        cont = controller.step()
        assert cont is True
        assert any("Assistant Error" in msg for msg in printed_messages)
        assert len(synthesizer.spoken_texts) == 0


# ── Scenario 9, 10: Text-to-speech / audio playback failure ─────────────────
class TestTTSFailure:
    def test_tts_failure_does_not_crash(self, dummy_assistant):
        cfg = ArceusConfig(model_backend="echo")
        recorder = DummyRecorder()
        recognizer = MockSpeechRecognizer(cfg, responses=["Hi there"])
        synthesizer = MockSpeechSynthesizer(cfg)
        synthesizer.fail_next = "Speaker stream write error"

        printed_messages = []
        controller = VoiceConversationController(
            assistant=dummy_assistant,
            recorder=recorder,
            recognizer=recognizer,
            synthesizer=synthesizer,
            config=cfg,
            input_func=lambda _: "",
            output_func=printed_messages.append,
        )

        cont = controller.step()
        assert cont is True
        # Text should still be displayed
        assert any("ARCEUS ➤ [ARCEUS echo] Hi there" in msg for msg in printed_messages)
        # Error must be explicitly reported (not silently swallowed)
        assert any("Speech Synthesis Error" in msg for msg in printed_messages)
        assert any("Speaker stream write error" in msg for msg in printed_messages)

    def test_tts_exception_reported_explicitly(self, dummy_assistant):
        """TTS failure logs error details and notifies the user."""
        cfg = ArceusConfig(model_backend="echo")
        recorder = DummyRecorder()
        recognizer = MockSpeechRecognizer(cfg, responses=["Hello failure"])
        synthesizer = MockSpeechSynthesizer(cfg)
        synthesizer.fail_next = "Audio output device disconnected"

        messages = []
        controller = VoiceConversationController(
            assistant=dummy_assistant,
            recorder=recorder,
            recognizer=recognizer,
            synthesizer=synthesizer,
            config=cfg,
            input_func=lambda _: "",
            output_func=messages.append,
        )

        assert controller.step() is True
        error_msgs = [m for m in messages if "Speech Synthesis Error" in m]
        assert len(error_msgs) == 1
        assert "Audio output device disconnected" in error_msgs[0]


# ── Scenario 11: Graceful exit ──────────────────────────────────────────────
class TestGracefulExit:
    @pytest.mark.parametrize("cmd", ["quit", "exit", "q", "/exit"])
    def test_text_exit_commands(self, dummy_assistant, cmd):
        cfg = ArceusConfig(model_backend="echo")
        controller = VoiceConversationController(
            assistant=dummy_assistant,
            recorder=DummyRecorder(),
            recognizer=MockSpeechRecognizer(cfg),
            synthesizer=MockSpeechSynthesizer(cfg),
            config=cfg,
            input_func=lambda _: cmd,
            output_func=lambda _: None,
        )
        assert controller.step() is False

    @pytest.mark.parametrize("spoken_word", ["quit", "exit"])
    def test_spoken_exit_commands(self, dummy_assistant, spoken_word):
        cfg = ArceusConfig(model_backend="echo")
        recognizer = MockSpeechRecognizer(cfg, responses=[spoken_word])
        controller = VoiceConversationController(
            assistant=dummy_assistant,
            recorder=DummyRecorder(),
            recognizer=recognizer,
            synthesizer=MockSpeechSynthesizer(cfg),
            config=cfg,
            input_func=lambda _: "",
            output_func=lambda _: None,
        )
        assert controller.step() is False


# ── Scenario 12: KeyboardInterrupt / EOF handling ───────────────────────────
class TestInterruptionAndCleanup:
    def test_keyboard_interrupt_handled(self, dummy_assistant):
        cfg = ArceusConfig(model_backend="echo")

        def interrupt_input(_):
            raise KeyboardInterrupt

        printed = []
        controller = VoiceConversationController(
            assistant=dummy_assistant,
            recorder=DummyRecorder(),
            recognizer=MockSpeechRecognizer(cfg),
            synthesizer=MockSpeechSynthesizer(cfg),
            config=cfg,
            input_func=interrupt_input,
            output_func=printed.append,
        )

        assert controller.step() is False
        assert any("Exiting voice mode" in msg for msg in printed)

    def test_reset_command(self, dummy_assistant):
        cfg = ArceusConfig(model_backend="echo")
        dummy_assistant.chat("test turn")
        assert dummy_assistant.turn_count == 1

        printed = []
        controller = VoiceConversationController(
            assistant=dummy_assistant,
            recorder=DummyRecorder(),
            recognizer=MockSpeechRecognizer(cfg),
            synthesizer=MockSpeechSynthesizer(cfg),
            config=cfg,
            input_func=lambda _: "/reset",
            output_func=printed.append,
        )

        assert controller.step() is True
        assert dummy_assistant.turn_count == 0
        assert any("history cleared" in msg for msg in printed)

    def test_run_loop_exits_on_command(self, dummy_assistant):
        cfg = ArceusConfig(model_backend="echo")
        printed = []
        inputs = ["exit"]
        synthesizer = MockSpeechSynthesizer(cfg)

        controller = VoiceConversationController(
            assistant=dummy_assistant,
            recorder=DummyRecorder(),
            recognizer=MockSpeechRecognizer(cfg),
            synthesizer=synthesizer,
            config=cfg,
            input_func=lambda _: inputs.pop(0),
            output_func=printed.append,
        )

        controller.run_loop()
        assert any("ARCEUS Voice Mode Active" in msg for msg in printed)
        assert any("Exiting voice mode" in msg for msg in printed)
        # Verify resources cleaned up on exit
        assert synthesizer.cleaned_up is True

    def test_run_loop_cleans_up_on_keyboard_interrupt(self, dummy_assistant):
        cfg = ArceusConfig(model_backend="echo")
        synthesizer = MockSpeechSynthesizer(cfg)

        def interrupt_prompt(_):
            raise KeyboardInterrupt

        controller = VoiceConversationController(
            assistant=dummy_assistant,
            recorder=DummyRecorder(),
            recognizer=MockSpeechRecognizer(cfg),
            synthesizer=synthesizer,
            config=cfg,
            input_func=interrupt_prompt,
            output_func=lambda _: None,
        )

        controller.run_loop()
        assert synthesizer.cleaned_up is True


# ── Factory tests ────────────────────────────────────────────────────────────
class TestFactories:
    def test_recognizer_factory_mock(self):
        cfg = ArceusConfig(voice_stt_engine="mock")
        rec = create_recognizer(cfg)
        assert isinstance(rec, MockSpeechRecognizer)

    def test_synthesizer_factory_mock(self):
        cfg = ArceusConfig()
        cfg.voice_tts_engine = "mock"
        synth = create_synthesizer(cfg)
        assert isinstance(synth, MockSpeechSynthesizer)


# ── Pyttsx3 Lifecycle & Multi-Turn State Tests ──────────────────────────────
class TestPyttsx3Lifecycle:
    class FakeProxy:
        def __init__(self):
            self.busy = False
            self._queue = ["stale_cmd"]

        def setBusy(self, busy):
            self.busy = busy

    class FakeEngine:
        def __init__(self):
            self.proxy = TestPyttsx3Lifecycle.FakeProxy()
            self._inLoop = True
            self.say_calls = []
            self.run_and_wait_count = 0
            self.stopped = False

        def say(self, text):
            self.say_calls.append(text)

        def runAndWait(self):
            self.run_and_wait_count += 1
            # Simulate upstream pyttsx3 behavior of clearing busy
            self.proxy.busy = False

        def endLoop(self):
            self._inLoop = False

        def stop(self):
            self.stopped = True

        def setProperty(self, name, val):
            pass

    def test_reset_proxy_state_clears_queue_and_marks_busy(self):
        from arceus.voice.tts import Pyttsx3Synthesizer

        cfg = ArceusConfig()
        synth = Pyttsx3Synthesizer.__new__(Pyttsx3Synthesizer)
        synth.config = cfg
        synth._engine = self.FakeEngine()

        synth._reset_proxy_state()
        assert synth._engine.proxy.busy is True
        assert len(synth._engine.proxy._queue) == 0
        assert synth._engine._inLoop is False

    def test_speak_resets_state_before_and_after(self):
        from arceus.voice.tts import Pyttsx3Synthesizer

        cfg = ArceusConfig()
        synth = Pyttsx3Synthesizer.__new__(Pyttsx3Synthesizer)
        synth.config = cfg
        fake_engine = self.FakeEngine()
        synth._engine = fake_engine

        # Turn 1
        synth.speak("Turn 1 text")
        assert fake_engine.say_calls == ["Turn 1 text"]
        assert fake_engine.run_and_wait_count == 1
        assert fake_engine.proxy.busy is True

        # Turn 2
        synth.speak("Turn 2 text")
        assert fake_engine.say_calls == ["Turn 1 text", "Turn 2 text"]
        assert fake_engine.run_and_wait_count == 2
        assert fake_engine.proxy.busy is True

        # Turn 3
        synth.speak("Turn 3 text")
        assert fake_engine.say_calls == ["Turn 1 text", "Turn 2 text", "Turn 3 text"]
        assert fake_engine.run_and_wait_count == 3
        assert fake_engine.proxy.busy is True

    def test_cleanup_stops_engine(self):
        from arceus.voice.tts import Pyttsx3Synthesizer

        cfg = ArceusConfig()
        synth = Pyttsx3Synthesizer.__new__(Pyttsx3Synthesizer)
        synth.config = cfg
        fake_engine = self.FakeEngine()
        synth._engine = fake_engine

        synth.cleanup()
        assert fake_engine.stopped is True
        assert fake_engine._inLoop is False
