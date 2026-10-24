"""Shared fakes for the HUD tests (no Qt, no network, no audio hardware)."""

from __future__ import annotations

import io
import threading
import time
import wave
from typing import Any, Callable, Dict, List, Optional

from arceus.assistant import ArceusAssistant
from arceus.config import ArceusConfig
from arceus.hud.session import HudSession
from arceus.model_interface import ModelInterface


def wait_for(predicate: Callable[[], bool], timeout: float = 3.0) -> bool:
    """Poll *predicate* until true or *timeout*; returns the final result."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def make_wav(amplitude: int = 0, frames: int = 1600) -> bytes:
    """A 16 kHz mono 16-bit WAV with a constant sample value."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(int(amplitude).to_bytes(2, "little", signed=True) * frames)
    return buf.getvalue()


class ScriptedModel(ModelInterface):
    """Model backend whose replies/errors are scripted and can be held open."""

    def __init__(self, config: ArceusConfig, outcomes: Optional[List[Any]] = None, gate: Optional[threading.Event] = None):
        super().__init__(config)
        self.outcomes = list(outcomes or [])
        self.gate = gate
        self.calls = 0
        self.entered = threading.Event()
        self.healthy = True

    def generate(self, messages):
        self.calls += 1
        self.entered.set()
        if self.gate is not None:
            assert self.gate.wait(5), "test forgot to release the model gate"
        outcome = self.outcomes.pop(0) if self.outcomes else f"reply to: {messages[-1]['content']}"
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def health_check(self) -> bool:
        return self.healthy


class FakeMetrics:
    def sample(self) -> Dict[str, Any]:
        return {"cpu_percent": 12.5, "ram_used_gb": 8.0, "ram_total_gb": 24.0, "ram_percent": 33.3}


class FakeVoice:
    """Stands in for VoiceConversationController: replays a script of hook events."""

    class _Obj:  # engine placeholders, named like the real classes
        pass

    def __init__(self, on_event, script=None, block: Optional[threading.Event] = None):
        self.on_event = on_event
        self.script = script
        self.block = block
        self.turns = 0
        self.cleaned_up = False
        recognizer = type("VoskRecognizerBackend", (), {})()
        synthesizer = type("Pyttsx3Synthesizer", (), {})()
        self.recognizer, self.synthesizer = recognizer, synthesizer
        self.seen: List[Any] = []   # filled by the test through `observe`
        self.observe: Callable[[str], None] = lambda name: None

    def run_turn(self) -> bool:
        self.turns += 1
        if self.block is not None:
            assert self.block.wait(5), "test forgot to release the voice gate"
        for name, data in (self.script or []):
            self.on_event(name, data)
            self.observe(name)
        return True

    def cleanup(self) -> None:
        self.cleaned_up = True


class Harness:
    """A started HudSession plus an event log."""

    def __init__(self, model_backend: str = "echo", outcomes=None, gate=None, voice_script=None,
                 voice_block=None, voice_factory=None, monitor: bool = False, healthy: bool = True, **session_kwargs):
        self.config = ArceusConfig(model_backend=model_backend)
        self.model = ScriptedModel(self.config, outcomes, gate)
        self.model.healthy = healthy
        self.assistant = ArceusAssistant(config=self.config, model=self.model)
        self.events: List[Dict[str, Any]] = []
        self.voice: Optional[FakeVoice] = None
        self.voice_factory_calls = 0

        def factory(assistant, config, on_event):
            self.voice_factory_calls += 1
            self.voice = FakeVoice(on_event, voice_script, voice_block)
            self.voice.observe = lambda name: self.voice_states.append((name, self.session.state.value))
            return self.voice

        self.voice_states: List[Any] = []
        self.session = HudSession(
            self.assistant, self.config,
            voice_factory=voice_factory or factory,
            ollama_probe=session_kwargs.pop("ollama_probe", lambda host, model: {
                "connection": "CONNECTED", "model_installed": True,
                "residency": {"state": "GPU", "gpu_percent": 100.0}, "error": ""}),
            mic_probe=session_kwargs.pop("mic_probe", lambda: {"mic": "AVAILABLE", "mic_detail": ""}),
            metrics=FakeMetrics(),
            **session_kwargs,
        )
        self.session.subscribe(self.events.append)
        self.session.start(monitor=monitor)

    def idle(self, timeout: float = 3.0) -> bool:
        return wait_for(lambda: not self.session.busy, timeout)

    def of(self, type_: str) -> List[Dict[str, Any]]:
        return [e for e in self.events if e["type"] == type_]

    def close(self) -> None:
        self.session.shutdown()
