"""
Text-to-speech (TTS) interface and implementations for ARCEUS Voice.

Supports:
- Local offline synthesis via pyttsx3 (using native Windows 11 SAPI5 voices)
- Mock synthesizer for deterministic unit tests
"""

from __future__ import annotations

import abc
import logging
import warnings
from typing import Optional

from arceus.config import ArceusConfig
from arceus.exceptions import SpeechSynthesisError

logger = logging.getLogger(__name__)


class SpeechSynthesizerInterface(abc.ABC):
    """Abstract base class for all ARCEUS text-to-speech engines."""

    def __init__(self, config: ArceusConfig) -> None:
        self.config = config

    @abc.abstractmethod
    def speak(self, text: str) -> None:
        """
        Synthesize and play *text* through system audio output.

        Parameters
        ----------
        text : str
            The text response to speak aloud.

        Raises
        ------
        SpeechSynthesisError
            If speech generation or playback fails.
        """

    def health_check(self) -> bool:
        """Check if the synthesis backend is functional."""
        return True

    def cleanup(self) -> None:
        """Release audio resources and shut down playback engines cleanly."""
        pass


# ── Windows SAPI5 / pyttsx3 Local TTS Engine ────────────────────────
class Pyttsx3Synthesizer(SpeechSynthesizerInterface):
    """
    100% offline text-to-speech using Windows native voices via pyttsx3.
    Requires no internet and makes no external API calls.
    """

    def __init__(self, config: ArceusConfig) -> None:
        super().__init__(config)
        self._engine = None
        self._init_engine()

    def _init_engine(self) -> None:
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=FutureWarning)
                import pyttsx3

                self._engine = pyttsx3.init()

                # Configure speech rate and volume
                if self.config.voice_tts_rate > 0:
                    self._engine.setProperty("rate", self.config.voice_tts_rate)
                if 0.0 <= self.config.voice_tts_volume <= 1.0:
                    self._engine.setProperty("volume", self.config.voice_tts_volume)

                # Ensure initial proxy state is ready
                if hasattr(self._engine, "proxy") and hasattr(self._engine.proxy, "setBusy"):
                    self._engine.proxy.setBusy(True)

        except Exception as exc:
            raise SpeechSynthesisError(
                f"Failed to initialize pyttsx3 Windows speech engine: {exc}"
            ) from exc

    def _reset_proxy_state(self) -> None:
        """
        Reset pyttsx3 internal proxy state before and after each utterance.

        Root cause explanation:
        In pyttsx3, Engine.runAndWait() leaves DriverProxy._busy = False when it exits.
        On subsequent turns, Engine.say() immediately dispatches the speak command to
        SAPI5 via _pump() before runAndWait() can hook Engine.endLoop into the command queue.
        Then, when runAndWait() starts its loop, the first loop tick immediately executes
        endLoop, which calls SAPI5Driver.stop() (SVSFPurgeBeforeSpeak), instantly canceling
        and purging the speech before any audio can be played.

        Explicitly setting proxy.setBusy(True) and clearing any stale queue items keeps
        the command queued until runAndWait() starts, guaranteeing reliable playback on
        the 2nd, 3rd, and all subsequent turns.
        """
        if self._engine is None:
            return

        if hasattr(self._engine, "proxy"):
            proxy = self._engine.proxy
            if hasattr(proxy, "setBusy"):
                proxy.setBusy(True)
            if hasattr(proxy, "_queue") and isinstance(proxy._queue, list):
                proxy._queue.clear()

        if getattr(self._engine, "_inLoop", False):
            try:
                self._engine.endLoop()
            except Exception:
                pass

    def speak(self, text: str) -> None:
        """Synthesize text and play it aloud via system speakers."""
        if not text or not text.strip():
            return

        cleaned_text = text.strip()
        logger.info("Speaking: %s", cleaned_text[:60])

        try:
            if self._engine is None:
                self._init_engine()

            # Prepare pyttsx3 state for repeated execution
            self._reset_proxy_state()

            self._engine.say(cleaned_text)
            self._engine.runAndWait()

            # Ensure proxy is reset for the next turn
            self._reset_proxy_state()

        except Exception as exc:
            logger.error("pyttsx3 speech playback error: %s", exc, exc_info=True)
            # Resilient fallback: attempt direct Windows SAPI5 playback
            try:
                logger.info("Attempting direct SAPI5 COM fallback playback...")
                self._fallback_sapi_speak(cleaned_text)
            except Exception as fb_exc:
                logger.error("Direct SAPI fallback also failed: %s", fb_exc, exc_info=True)
                raise SpeechSynthesisError(
                    f"Audio playback failed on engine ({exc}); fallback error ({fb_exc})"
                ) from exc

    def _fallback_sapi_speak(self, text: str) -> None:
        """Direct Windows SAPI.SpVoice COM fallback."""
        import win32com.client

        voice = win32com.client.Dispatch("SAPI.SpVoice")
        if 0.0 <= self.config.voice_tts_volume <= 1.0:
            voice.Volume = int(self.config.voice_tts_volume * 100)
        # Flag 0 = SVSFDefault (Synchronous: blocks until playback completes)
        voice.Speak(text, 0)

    def cleanup(self) -> None:
        """Clean up audio engine resources."""
        if self._engine is not None:
            try:
                if getattr(self._engine, "_inLoop", False):
                    self._engine.endLoop()
                self._engine.stop()
            except Exception as exc:
                logger.debug("Error while stopping TTS engine during cleanup: %s", exc)


# ── Mock Synthesizer for Unit Tests ─────────────────────────────────
class MockSpeechSynthesizer(SpeechSynthesizerInterface):
    """Mock text-to-speech engine that tracks spoken utterances without audio output."""

    def __init__(self, config: ArceusConfig) -> None:
        super().__init__(config)
        self.spoken_texts: list[str] = []
        self.fail_next: Optional[str] = None
        self.cleaned_up: bool = False

    def speak(self, text: str) -> None:
        if self.fail_next:
            msg = self.fail_next
            self.fail_next = None
            raise SpeechSynthesisError(msg)
        if text and text.strip():
            self.spoken_texts.append(text.strip())

    def cleanup(self) -> None:
        self.cleaned_up = True


# ── Factory ────────────────────────────────────────────────────────
def create_synthesizer(config: ArceusConfig) -> SpeechSynthesizerInterface:
    """Instantiate the configured SpeechSynthesizerInterface."""
    # Unit tests can set voice_tts_engine to 'mock'
    engine = (getattr(config, "voice_tts_engine", "pyttsx3") or "pyttsx3").lower()
    if engine == "mock":
        return MockSpeechSynthesizer(config)
    return Pyttsx3Synthesizer(config)
