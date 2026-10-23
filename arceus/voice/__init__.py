"""
ARCEUS Voice package.
Provides modular audio input, speech-to-text, text-to-speech,
and voice conversation orchestration.
"""

from arceus.voice.audio_input import AudioRecorder
from arceus.voice.controller import VoiceConversationController
from arceus.voice.stt import SpeechRecognizerInterface, create_recognizer
from arceus.voice.tts import SpeechSynthesizerInterface, create_synthesizer

__all__ = [
    "AudioRecorder",
    "VoiceConversationController",
    "SpeechRecognizerInterface",
    "create_recognizer",
    "SpeechSynthesizerInterface",
    "create_synthesizer",
]
