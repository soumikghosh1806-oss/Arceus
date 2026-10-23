"""
Speech-to-text (STT) interface and implementations for ARCEUS Voice.

Supports:
- Local offline recognition via Vosk (when a model directory is present)
- Online recognition via SpeechRecognition (Google Web Speech API)
- Mock recognizer for deterministic unit testing
"""

from __future__ import annotations

import abc
import io
import json
import logging
import os
from pathlib import Path
from typing import Optional

from arceus.config import ArceusConfig
from arceus.exceptions import SpeechRecognitionError

logger = logging.getLogger(__name__)


class SpeechRecognizerInterface(abc.ABC):
    """Abstract base class for all ARCEUS speech-to-text engines."""

    def __init__(self, config: ArceusConfig) -> None:
        self.config = config

    @abc.abstractmethod
    def transcribe(self, wav_bytes: bytes) -> str:
        """
        Transcribe in-memory WAV audio bytes to text.

        Parameters
        ----------
        wav_bytes : bytes
            WAV audio stream (16kHz mono recommended).

        Returns
        -------
        str
            Transcribed text.

        Raises
        ------
        SpeechRecognitionError
            If transcription fails or speech is unintelligible.
        """

    def health_check(self) -> bool:
        """Check if the recognition backend is functional."""
        return True


# ── Local Offline Vosk Backend ──────────────────────────────────────
class VoskRecognizerBackend(SpeechRecognizerInterface):
    """
    100% offline speech recognition using Vosk.
    Requires a downloaded Vosk model folder.
    """

    def __init__(self, config: ArceusConfig, model_path: Optional[str] = None) -> None:
        super().__init__(config)
        self.model_path = model_path or config.voice_vosk_model_path or "model"
        self._model = None
        self._load_model()

    def _load_model(self) -> None:
        path = Path(self.model_path)
        if not path.exists() or not path.is_dir():
            raise SpeechRecognitionError(
                f"Vosk model directory not found at '{path}'. "
                "Download a lightweight model (e.g., vosk-model-small-en-us) "
                "from https://alphacephei.com/vosk/models and extract it to the project root."
            )
        try:
            import vosk

            vosk.SetLogLevel(-1)  # quiet C logging
            self._model = vosk.Model(str(path))
            logger.info("Loaded local Vosk model from %s", path)
        except Exception as exc:
            raise SpeechRecognitionError(f"Failed to load Vosk model: {exc}") from exc

    def transcribe(self, wav_bytes: bytes) -> str:
        if not wav_bytes:
            raise SpeechRecognitionError("Audio buffer is empty.")

        try:
            import wave
            import vosk

            with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                sample_rate = wf.getframerate()
                rec = vosk.KaldiRecognizer(self._model, sample_rate)
                rec.SetWords(False)

                while True:
                    data = wf.readframes(4000)
                    if len(data) == 0:
                        break
                    rec.AcceptWaveform(data)

                res = json.loads(rec.FinalResult())
                text = res.get("text", "").strip()
                if not text:
                    raise SpeechRecognitionError(
                        "No speech recognized. Please speak clearly into the microphone."
                    )
                return text
        except SpeechRecognitionError:
            raise
        except Exception as exc:
            raise SpeechRecognitionError(f"Vosk recognition error: {exc}") from exc


# ── SpeechRecognition (Online Google API) Backend ───────────────────
class GoogleSpeechRecognizer(SpeechRecognizerInterface):
    """
    Speech recognition using the SpeechRecognition package.
    Note: Sends audio to Google's public Web Speech API.
    """

    def __init__(self, config: ArceusConfig) -> None:
        super().__init__(config)
        try:
            import speech_recognition as sr  # type: ignore[import-untyped]

            self._sr = sr
            self._recognizer = sr.Recognizer()
        except ImportError as exc:
            raise SpeechRecognitionError(
                "SpeechRecognition package is not installed. "
                "Install it with: pip install SpeechRecognition"
            ) from exc

    def transcribe(self, wav_bytes: bytes) -> str:
        if not wav_bytes:
            raise SpeechRecognitionError("Audio buffer is empty.")

        try:
            with io.BytesIO(wav_bytes) as audio_file:
                with self._sr.AudioFile(audio_file) as source:
                    audio_data = self._recognizer.record(source)
                    text = self._recognizer.recognize_google(audio_data)
                    if not text or not text.strip():
                        raise SpeechRecognitionError(
                            "No speech detected. Please speak closer to the microphone."
                        )
                    return text.strip()
        except self._sr.UnknownValueError:
            raise SpeechRecognitionError(
                "Could not understand the audio. Please speak clearly and try again."
            )
        except self._sr.RequestError as exc:
            raise SpeechRecognitionError(
                f"Speech recognition service request error: {exc}. "
                "Verify your internet connection."
            ) from exc
        except SpeechRecognitionError:
            raise
        except Exception as exc:
            raise SpeechRecognitionError(f"Speech recognition failure: {exc}") from exc


# ── Mock Recognizer for Automated Tests ─────────────────────────────
class MockSpeechRecognizer(SpeechRecognizerInterface):
    """Deterministic mock speech recognizer for unit tests."""

    def __init__(self, config: ArceusConfig, responses: Optional[list[str]] = None) -> None:
        super().__init__(config)
        self.responses = list(responses or ["Hello ARCEUS"])
        self.call_count = 0

    def transcribe(self, wav_bytes: bytes) -> str:
        self.call_count += 1
        if not wav_bytes:
            raise SpeechRecognitionError("Audio buffer is empty.")
        if not self.responses:
            raise SpeechRecognitionError("No speech detected.")
        resp = self.responses.pop(0)
        if resp.startswith("__ERROR__"):
            raise SpeechRecognitionError(resp.replace("__ERROR__", "").strip())
        return resp


# ── Factory ────────────────────────────────────────────────────────
def create_recognizer(config: ArceusConfig) -> SpeechRecognizerInterface:
    """
    Factory creating the configured SpeechRecognizerInterface.
    Priority:
    1. If engine == 'vosk': load Vosk (offline).
    2. If engine == 'google': load Google Web Speech API.
    3. If engine == 'auto': check if Vosk model exists locally; if yes use Vosk,
       otherwise use Google SpeechRecognition with an informational log.
    """
    engine = (config.voice_stt_engine or "auto").lower()

    if engine == "vosk":
        return VoskRecognizerBackend(config)

    if engine == "google":
        return GoogleSpeechRecognizer(config)

    if engine == "mock":
        return MockSpeechRecognizer(config)

    # Auto mode:
    # Check if a local vosk model exists in default locations
    possible_paths = [
        Path(config.voice_vosk_model_path) if config.voice_vosk_model_path else None,
        Path("model"),
        Path("vosk-model"),
    ]
    for p in possible_paths:
        if p and p.exists() and p.is_dir():
            logger.info("Auto-selected offline Vosk STT engine with model at %s", p)
            return VoskRecognizerBackend(config, model_path=str(p))

    logger.info("Auto-selected SpeechRecognition (Google API) for STT")
    return GoogleSpeechRecognizer(config)
