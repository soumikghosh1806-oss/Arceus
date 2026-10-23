"""
Voice conversation controller for ARCEUS.

Orchestrates:
1. Explicit user trigger (Press Enter to record)
2. Audio recording via AudioRecorder
3. Speech-to-text via SpeechRecognizerInterface
4. Conversation delegation to ArceusAssistant
5. Text-to-speech via SpeechSynthesizerInterface
"""

from __future__ import annotations

import logging
import sys
from typing import Callable, Optional

from arceus.assistant import ArceusAssistant
from arceus.config import ArceusConfig
from arceus.exceptions import (
    ArceusError,
    AudioDeviceError,
    SpeechRecognitionError,
    SpeechSynthesisError,
)
from arceus.voice.audio_input import AudioRecorder
from arceus.voice.stt import SpeechRecognizerInterface, create_recognizer
from arceus.voice.tts import SpeechSynthesizerInterface, create_synthesizer

logger = logging.getLogger(__name__)


class VoiceConversationController:
    """
    Manages interactive voice conversations with ARCEUS.

    Parameters
    ----------
    assistant : ArceusAssistant
        The core conversation assistant (manages context, history, and AI model).
    recorder : AudioRecorder, optional
        Audio capture component. Defaults to standard AudioRecorder.
    recognizer : SpeechRecognizerInterface, optional
        Speech-to-text component. Defaults to configured recognizer.
    synthesizer : SpeechSynthesizerInterface, optional
        Text-to-speech component. Defaults to configured synthesizer.
    config : ArceusConfig, optional
        Configuration instance. Defaults to assistant's config.
    input_func : Callable[[str], str], optional
        Input handler for interactive prompt (defaults to built-in input).
    output_func : Callable[..., None], optional
        Output handler for messages (defaults to built-in print).
    """

    def __init__(
        self,
        assistant: ArceusAssistant,
        recorder: Optional[AudioRecorder] = None,
        recognizer: Optional[SpeechRecognizerInterface] = None,
        synthesizer: Optional[SpeechSynthesizerInterface] = None,
        config: Optional[ArceusConfig] = None,
        input_func: Optional[Callable[[str], str]] = None,
        output_func: Optional[Callable[..., None]] = None,
    ) -> None:
        self.assistant = assistant
        self.config = config or assistant.config
        self.recorder = recorder or AudioRecorder()
        self.recognizer = recognizer or create_recognizer(self.config)
        self.synthesizer = synthesizer or create_synthesizer(self.config)
        self.input_func = input_func or input
        self.output_func = output_func or print

    def step(self) -> bool:
        """
        Execute a single voice conversation cycle.

        Returns
        -------
        bool
            True to continue the voice session, False to exit.
        """
        # 1. Ready state & explicit user prompt
        try:
            prompt_text = (
                "\n[Ready to Listen] Press <Enter> to speak (or type 'exit' / 'quit' to leave): "
            )
            user_choice = self.input_func(prompt_text).strip()
        except (EOFError, KeyboardInterrupt):
            self.output_func("\nExiting voice mode.")
            return False

        if user_choice.lower() in ("exit", "quit", "q", "/exit", "/quit"):
            self.output_func("Exiting voice mode.")
            return False

        if user_choice.lower() == "/reset":
            self.assistant.reset()
            self.output_func("[Conversation history cleared]")
            return True

        # 2. Recording
        duration = float(self.config.voice_record_timeout or 5)
        self.output_func(f"[Listening...] Please speak now ({duration:.0f}s)...")
        try:
            wav_bytes = self.recorder.record(duration=duration)
        except AudioDeviceError as exc:
            self.output_func(f"[Audio Error] {exc}")
            logger.error("Audio recording failed: %s", exc)
            return True

        # 3. Transcribing
        self.output_func("[Transcribing speech...]")
        try:
            user_text = self.recognizer.transcribe(wav_bytes)
        except SpeechRecognitionError as exc:
            self.output_func(f"[Speech Error] {exc}")
            return True

        if not user_text or not user_text.strip():
            self.output_func("[Notice] No speech detected. Please try again.")
            return True

        # Display transcribed user speech
        self.output_func(f"\nYou (Voice) ➤ {user_text}")

        # Check for spoken exit commands
        if user_text.lower() in ("quit", "exit", "quit.", "exit.", "stop."):
            self.output_func("Spoken exit command received. Goodbye!")
            try:
                self.synthesizer.speak("Goodbye!")
            except Exception:
                pass
            return False

        # 4. Thinking & AI assistant processing
        self.output_func("[Thinking...]")
        try:
            reply = self.assistant.chat(user_text)
        except ArceusError as exc:
            self.output_func(f"[Assistant Error] {exc}")
            return True

        # Display assistant response
        self.output_func(f"ARCEUS ➤ {reply}\n")

        # 5. Speaking output
        self.output_func("[Speaking response...]")
        try:
            self.synthesizer.speak(reply)
        except SpeechSynthesisError as exc:
            logger.error("TTS audio synthesis error: %s", exc, exc_info=True)
            self.output_func(f"[Speech Synthesis Error] {exc}")

        return True

    def cleanup(self) -> None:
        """Release voice pipeline resources cleanly."""
        logger.debug("Cleaning up voice controller resources.")
        if hasattr(self.synthesizer, "cleanup"):
            try:
                self.synthesizer.cleanup()
            except Exception as exc:
                logger.warning("Error during synthesizer cleanup: %s", exc)

    def run_loop(self) -> None:
        """Run the interactive voice conversation loop until the user exits."""
        self.output_func(
            "\n═══════════════════════════════════════════\n"
            "       ARCEUS Voice Mode Active            \n"
            "  100% Local & Private Speech Pipeline     \n"
            "═══════════════════════════════════════════"
        )
        self.output_func("Speak into your microphone when prompted.")
        self.output_func("Type 'exit', 'quit', or press Ctrl+C to return to menu.\n")

        try:
            while True:
                try:
                    keep_going = self.step()
                    if not keep_going:
                        break
                except KeyboardInterrupt:
                    self.output_func("\nSession interrupted. Returning to menu.")
                    break
                except Exception as exc:
                    logger.exception("Unexpected error in voice loop: %s", exc)
                    self.output_func(f"[Unexpected Error] {exc}")
                    # Don't crash out completely; allow user to retry
                    try:
                        retry = self.input_func("Would you like to continue? (Y/n): ").strip().lower()
                        if retry in ("n", "no"):
                            break
                    except (EOFError, KeyboardInterrupt):
                        break
        finally:
            self.cleanup()
