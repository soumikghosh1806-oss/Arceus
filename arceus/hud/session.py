"""
``HudSession`` â€” everything the HUD needs from ARCEUS, with no Qt and no HTML.

Responsibilities
----------------
* Run the *existing* ``ArceusAssistant`` (text) and
  ``VoiceConversationController`` (voice) on ONE background worker thread,
  so the UI never blocks and two turns can never overlap.
* Turn real pipeline events into a small, ordered stream of JSON-friendly
  events (``state``, ``message``, ``activity`` ...) for the front-end.
* Poll real facts: Ollama connection / model residency, microphone, CPU, RAM.
* Validate every command coming from the front-end (it is not trusted).

Nothing here invents data.  Transcript lines come from the assistant, states
come from pipeline events, and anything unmeasurable is reported as ``None``
(shown as N/A).
"""

from __future__ import annotations

import logging
import queue
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from arceus import __version__
from arceus.assistant import ArceusAssistant
from arceus.config import ArceusConfig
from arceus.exceptions import ArceusError
from arceus.hud import metrics as metrics_mod
from arceus.hud import probes
from arceus.hud.protocol import (
    MAX_ACTIVITY,
    MAX_DETAIL_CHARS,
    MAX_INPUT_CHARS,
    MAX_MESSAGES,
    HudState,
)
from arceus.utils import sanitize_input

logger = logging.getLogger(__name__)

Event = Dict[str, Any]
Subscriber = Callable[[Event], None]
VoiceFactory = Callable[[ArceusAssistant, ArceusConfig, Callable[..., None]], Any]

_ENGINE_LABELS = {
    "VoskRecognizerBackend": ("VOSK", False),
    "GoogleSpeechRecognizer": ("GOOGLE WEB SPEECH", True),
    "MockSpeechRecognizer": ("MOCK", False),
    "Pyttsx3Synthesizer": ("PYTTSX3 / WINDOWS SAPI5", False),
    "MockSpeechSynthesizer": ("MOCK", False),
}
_SILENT_DBFS = -60.0


def _concise(text: str, limit: int = MAX_DETAIL_CHARS) -> str:
    """One-line, length-limited version of an error message for the status line."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "â€¦"


def _init_com_for_this_thread() -> None:
    """
    Windows speech (SAPI5 via pyttsx3) uses COM, which must be initialised on
    the thread that talks to it.  The voice pipeline only ever runs on the
    worker thread, so we initialise COM there.  No-op on other platforms.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.ole32.CoInitializeEx(None, 2)  # type: ignore[attr-defined]  # APARTMENTTHREADED
    except Exception:  # noqa: BLE001
        logger.debug("COM initialisation failed on worker thread", exc_info=True)


def _default_voice_factory(
    assistant: ArceusAssistant, config: ArceusConfig, on_event: Callable[..., None]
) -> Any:
    from arceus.voice.controller import VoiceConversationController

    return VoiceConversationController(
        assistant=assistant,
        config=config,
        input_func=lambda _prompt="": "",   # the HUD mic button replaces "press Enter"
        output_func=lambda *a, **k: None,   # status is shown through events, not print
        on_event=on_event,
    )


class _Worker(threading.Thread):
    """A single daemon thread running jobs one at a time (never blocks app exit)."""

    def __init__(self) -> None:
        super().__init__(name="arceus-hud-worker", daemon=True)
        self._jobs: "queue.Queue[Optional[Callable[[], None]]]" = queue.Queue()

    def submit(self, job: Callable[[], None]) -> None:
        self._jobs.put(job)

    def stop(self) -> None:
        self._jobs.put(None)

    def run(self) -> None:
        _init_com_for_this_thread()
        while True:
            job = self._jobs.get()
            if job is None:
                return
            try:
                job()
            except Exception:  # noqa: BLE001 - jobs handle their own errors; this is a last resort
                logger.exception("Unhandled error in HUD worker job")


class HudSession:
    """Owns the assistant for the HUD and publishes events to subscribers."""

    def __init__(
        self,
        assistant: ArceusAssistant,
        config: Optional[ArceusConfig] = None,
        *,
        fullscreen: bool = False,
        voice_factory: Optional[VoiceFactory] = None,
        ollama_probe: Optional[Callable[..., Dict[str, Any]]] = None,
        mic_probe: Optional[Callable[[], Dict[str, Any]]] = None,
        metrics: Optional[metrics_mod.SystemMetrics] = None,
        probe_interval: float = 5.0,
        metrics_interval: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._assistant = assistant
        self._config = config or assistant.config
        self._fullscreen = fullscreen
        self._voice_factory = voice_factory or _default_voice_factory
        self._ollama_probe = ollama_probe or probes.probe_ollama
        self._mic_probe = mic_probe or probes.probe_microphone
        self._metrics = metrics or metrics_mod.SystemMetrics()
        self._probe_interval = probe_interval
        self._metrics_interval = metrics_interval
        self._clock = clock
        self._wall = wall_clock
        self._started_at = clock()

        self._lock = threading.RLock()
        self._subscribers: List[Subscriber] = []
        self._seq = 0
        self._state = HudState.STANDBY
        self._detail = ""
        self._busy: Optional[str] = None       # None | "text" | "voice"
        self._messages: List[Event] = []
        self._activity: List[Event] = []
        self._voice: Optional[Any] = None       # lazily built VoiceConversationController
        self._job_error: Optional[str] = None   # set by voice hooks during one voice turn

        self._kind = self._backend_kind()
        self._backend: Dict[str, Any] = {
            "kind": self._kind,
            "label": {"ollama": "LOCAL AI", "openai": "HOSTED AI", "echo": "ECHO TEST"}.get(
                self._kind, self._kind.upper()
            ),
            "model": self._model_name(),
            "host": self._config.ollama_host if self._kind == "ollama" else None,
            "connection": "N/A" if self._kind == "echo" else "UNKNOWN",
            "model_installed": None,
            "residency": {"state": probes.NA, "gpu_percent": None},
            "error": "",
        }
        self._devices: Dict[str, Any] = {"mic": "UNKNOWN", "mic_detail": "", "last_capture": None}
        self._voice_info: Dict[str, Any] = {
            "loaded": False,
            "stt_engine": f"{self._config.voice_stt_engine or 'auto'} (not loaded)",
            "stt_online": None,
            "tts_engine": "not loaded",
        }
        self._last_metrics: Dict[str, Any] = {
            "cpu_percent": None, "ram_used_gb": None, "ram_total_gb": None,
            "ram_percent": None, "uptime_s": 0,
        }

        self._worker = _Worker()
        self._stop = threading.Event()
        self._threads: List[threading.Thread] = []
        self._started = False

    # â”€â”€ Lifecycle â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def start(self, monitor: bool = True) -> None:
        """Start the worker (and, unless ``monitor=False``, the polling threads). Idempotent."""
        with self._lock:
            if self._started:
                return
            self._started = True
        self._worker.start()
        if not monitor:
            return
        for name, target in (("metrics", self._metrics_loop), ("probes", self._probe_loop)):
            t = threading.Thread(target=target, name=f"arceus-hud-{name}", daemon=True)
            t.start()
            self._threads.append(t)

    def shutdown(self) -> None:
        """Stop background threads and release the voice pipeline (idempotent)."""
        if self._stop.is_set():
            return
        self._stop.set()
        voice = self._voice
        if voice is not None and hasattr(voice, "cleanup"):
            self._worker.submit(voice.cleanup)
        self._worker.stop()
        if self._started:
            self._worker.join(timeout=3.0)
        for t in self._threads:
            t.join(timeout=1.0)

    def subscribe(self, callback: Subscriber) -> None:
        with self._lock:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: Subscriber) -> None:
        with self._lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

    # â”€â”€ Read-only views â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    @property
    def state(self) -> HudState:
        return self._state

    @property
    def busy(self) -> bool:
        return self._busy is not None

    def snapshot(self) -> Event:
        """Full current state (also what the front-end gets on (re)connect)."""
        with self._lock:
            return self._snapshot_locked()

    def request_snapshot(self) -> None:
        """Publish a snapshot event (the front-end calls this once it is connected)."""
        with self._lock:
            self._seq += 1
            self._deliver(self._snapshot_locked())

    # â”€â”€ Commands from the front-end (validated; never block) â”€â”€â”€â”€â”€â”€â”€
    def submit_text(self, text: Any) -> Dict[str, Any]:
        """Send a typed message to the assistant on the worker thread."""
        if not isinstance(text, str):
            return self._reject("invalid", "Message must be text.")
        cleaned = sanitize_input(text)
        if not cleaned:
            return {"accepted": False, "reason": "empty"}
        if len(cleaned) > MAX_INPUT_CHARS:
            return self._reject("too_long", f"Message is too long (limit {MAX_INPUT_CHARS} characters).")

        with self._lock:
            if self._busy:
                return self._reject("busy", "ARCEUS is still working on the previous request.")
            self._busy = "text"
            self._add_message("user", cleaned, "text")
            self._set_state(HudState.PROCESSING, "GENERATING RESPONSE")
        self._worker.submit(lambda: self._execute(lambda: self._text_job(cleaned)))
        return {"accepted": True, "reason": ""}

    def start_voice(self) -> Dict[str, Any]:
        """Run one voice turn (listen, transcribe, answer, speak)."""
        with self._lock:
            if self._busy:
                return self._reject("busy", "A request is already running; wait for it to finish.")
            self._busy = "voice"
            self._job_error = None
            self._set_state(HudState.PROCESSING, "PREPARING MICROPHONE")
        self._worker.submit(lambda: self._execute(self._voice_job))
        return {"accepted": True, "reason": ""}

    def reset(self) -> Dict[str, Any]:
        """Clear the conversation (history is only touched while idle)."""
        with self._lock:
            if self._busy:
                return self._reject("busy", "Cannot reset while a request is running.")
            self._assistant.reset()
            self._messages.clear()
            self._emit("reset")
            self._log("info", "Conversation reset")
            self._set_state(HudState.STANDBY, "")
        return {"accepted": True, "reason": ""}

    # â”€â”€ Worker jobs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _execute(self, job: Callable[[], Tuple[HudState, str]]) -> None:
        """Run *job*, turn any failure into an ERROR state, always release busy."""
        try:
            final = job()
        except ArceusError as exc:
            self._log("error", str(exc))
            final = (HudState.ERROR, _concise(str(exc)))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected error in HUD job")
            self._log("error", f"Unexpected error: {exc}")
            final = (HudState.ERROR, _concise(f"Unexpected error: {exc}"))
        with self._lock:
            self._busy = None
            self._set_state(*final)
        # Backend health is checked by the existing periodic monitor.
        # Avoid spawning an additional probe thread after an error.   # a failure may mean the backend went away

    def _text_job(self, text: str) -> Tuple[HudState, str]:
        reply = self._assistant.chat(text)
        self._add_message("assistant", reply, "text")
        return HudState.STANDBY, ""

    def _voice_job(self) -> Tuple[HudState, str]:
        try:
            controller = self._ensure_voice()
        except ArceusError as exc:
            self._log("error", f"Voice pipeline unavailable: {exc}")
            return HudState.ERROR, _concise(f"Voice unavailable: {exc}")
        controller.run_turn()
        if self._job_error:
            return HudState.ERROR, self._job_error
        return HudState.STANDBY, ""

    def _ensure_voice(self) -> Any:
        if self._voice is not None:
            return self._voice
        self._set_state(HudState.PROCESSING, "LOADING VOICE PIPELINE")
        controller = self._voice_factory(self._assistant, self._config, self._on_voice_event)
        self._voice = controller
        stt, stt_online = _ENGINE_LABELS.get(type(controller.recognizer).__name__, (type(controller.recognizer).__name__, None))
        tts, _ = _ENGINE_LABELS.get(type(controller.synthesizer).__name__, (type(controller.synthesizer).__name__, None))
        with self._lock:
            self._voice_info = {
                "loaded": True,
                "stt_engine": stt + (" (ONLINE)" if stt_online else " (OFFLINE)" if stt_online is False else ""),
                "stt_online": stt_online,
                "tts_engine": tts,
            }
            self._emit("voice", **self._voice_info)
        self._log("info", f"Voice pipeline ready: {self._voice_info['stt_engine']}")
        if stt_online:
            self._log("warn", "Speech recognition sends audio to an online service (no local Vosk model found).")
        return controller

    def _on_voice_event(self, name: str, data: Dict[str, Any]) -> None:
        """Translate a real voice-pipeline event into HUD state / messages."""
        if name == "listening_started":
            self._set_state(HudState.LISTENING, f"RECORDING {float(data.get('duration', 0)):.0f}S")
        elif name == "captured":
            self._record_capture_level(data.get("wav_bytes"))
        elif name == "transcribing":
            self._set_state(HudState.PROCESSING, "TRANSCRIBING")
        elif name == "transcribed":
            self._add_message("user", str(data.get("text", "")), "voice")
        elif name == "thinking":
            self._set_state(HudState.PROCESSING, "GENERATING RESPONSE")
        elif name == "reply":
            self._add_message("assistant", str(data.get("text", "")), "voice")
        elif name == "speaking_started":
            self._set_state(HudState.SPEAKING, "SPEAKING RESPONSE")
        elif name == "notice":
            self._log("warn", str(data.get("message", "")))
        elif name == "exit_requested":
            self._log("info", "Spoken exit command heard; voice turn ended.")
        elif name == "error":
            stage = {
                "audio": "Microphone",
                "speech": "Speech recognition",
                "speech_output": "Speech output",
            }.get(str(data.get("stage")), "")
            message = str(data.get("message", "Unknown error"))
            full = f"{stage}: {message}" if stage else message
            self._log("error", full)
            self._job_error = _concise(full)

    def _record_capture_level(self, wav_bytes: Any) -> None:
        levels = metrics_mod.wav_levels(wav_bytes) if isinstance(wav_bytes, (bytes, bytearray)) else None
        with self._lock:
            self._devices["last_capture"] = levels
            self._emit("devices", **self._devices)
        if levels is not None and levels["peak_dbfs"] <= _SILENT_DBFS:
            self._log("warn", "Captured audio is almost silent; check that the microphone is not muted.")

    # â”€â”€ Monitoring threads â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _metrics_loop(self) -> None:
        while not self._stop.is_set():
            try:
                data = self._metrics.sample()
                data["uptime_s"] = int(self._clock() - self._started_at)
                with self._lock:
                    self._last_metrics = data
                    self._emit("metrics", **data)
            except Exception:  # noqa: BLE001
                logger.debug("metrics sample failed", exc_info=True)
            self._stop.wait(self._metrics_interval)

    def _probe_loop(self) -> None:
        tick = 0
        # Local Ollama is cheap to poll; a hosted API is only re-checked every 5 minutes.
        interval = self._probe_interval if self._kind == "ollama" else max(self._probe_interval, 300.0)
        while not self._stop.is_set():
            try:
                self._probe_backend()
                if tick % 3 == 0:  # microphone changes rarely
                    self._probe_devices()
            except Exception:  # noqa: BLE001
                logger.debug("probe failed", exc_info=True)
            tick += 1
            self._stop.wait(interval)

    def _request_backend_probe(self) -> None:
        """Re-check the backend soon after a turn (runs on its own short thread)."""
        threading.Thread(target=self._safe_probe_backend, name="arceus-hud-probe", daemon=True).start()

    def _safe_probe_backend(self) -> None:
        try:
            self._probe_backend()
        except Exception:  # noqa: BLE001
            logger.debug("probe failed", exc_info=True)

    def _probe_backend(self) -> None:
        if self._kind == "ollama":
            result = self._ollama_probe(self._config.ollama_host, self._config.ollama_model)
        elif self._kind == "echo":
            return
        else:
            try:
                ok = bool(self._assistant.model.health_check())
            except Exception:  # noqa: BLE001
                ok = False
            result = {
                "connection": "CONNECTED" if ok else "DISCONNECTED",
                "model_installed": None,
                "residency": {"state": probes.NA, "gpu_percent": None},
                "error": "" if ok else "Hosted AI is not reachable.",
            }
        with self._lock:
            previous = self._backend["connection"]
            self._backend.update(
                connection=result["connection"],
                model_installed=result.get("model_installed"),
                residency=result.get("residency", self._backend["residency"]),
                error=result.get("error", ""),
            )
            self._emit("backend", **self._backend)
            if previous != result["connection"]:
                if result["connection"] == "CONNECTED":
                    self._log("info", f"{self._backend['label']} connected")
                elif previous != "UNKNOWN" or result.get("error"):
                    self._log("warn", result.get("error") or f"{self._backend['label']} disconnected")
            if result.get("model_installed") is False and previous != result["connection"]:
                self._log("warn", f"Model '{self._backend['model']}' is not installed in Ollama (run: ollama pull {self._backend['model']}).")

    def _probe_devices(self) -> None:
        info = self._mic_probe()
        with self._lock:
            self._devices.update(mic=info.get("mic", probes.NA), mic_detail=info.get("mic_detail", ""))
            self._emit("devices", **self._devices)

    # â”€â”€ Internals: state, events, history â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _set_state(self, state: HudState, detail: str = "") -> None:
        with self._lock:
            self._state, self._detail = state, detail
            self._emit("state", state=state.value, detail=detail, busy=self._busy is not None)

    def _add_message(self, role: str, text: str, source: str) -> None:
        with self._lock:
            message = {"role": role, "text": text, "source": source, "ts": int(self._wall())}
            self._messages.append(message)
            del self._messages[:-MAX_MESSAGES]
            self._emit("message", **message)

    def _log(self, level: str, text: str) -> None:
        with self._lock:
            entry = {"level": level, "text": text, "ts": int(self._wall())}
            self._activity.append(entry)
            del self._activity[:-MAX_ACTIVITY]
            self._emit("activity", **entry)

    def _reject(self, reason: str, text: str) -> Dict[str, Any]:
        if text:
            self._log("warn", text)
        return {"accepted": False, "reason": reason}

    def _emit(self, type_: str, **payload: Any) -> None:
        with self._lock:
            self._seq += 1
            event: Event = {"type": type_, "seq": self._seq, "ts": int(self._wall())}
            event.update(payload)
            self._deliver(event)

    def _deliver(self, event: Event) -> None:
        for callback in list(self._subscribers):
            try:
                callback(event)
            except Exception:  # noqa: BLE001
                logger.exception("HUD subscriber failed")

    def _snapshot_locked(self) -> Event:
        return {
            "type": "snapshot",
            "seq": self._seq,
            "ts": int(self._wall()),
            "version": __version__,
            "app": {"fullscreen": self._fullscreen},
            "state": self._state.value,
            "detail": self._detail,
            "busy": self._busy is not None,
            "messages": list(self._messages),
            "activity": list(self._activity),
            "backend": dict(self._backend),
            "devices": dict(self._devices),
            "voice": dict(self._voice_info),
            "metrics": dict(self._last_metrics),
        }

    def _backend_kind(self) -> str:
        name = (self._config.model_backend or "").lower()
        return "ollama" if name in ("local", "ollama") else name

    def _model_name(self) -> str:
        if self._kind == "ollama":
            return self._config.ollama_model
        if self._kind == "openai":
            return self._config.openai_model
        return "none (echo)"
