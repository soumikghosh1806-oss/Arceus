"""
Audio recording module for ARCEUS Voice.

Captures audio from the default input device (microphone) using sounddevice.
Outputs clean 16kHz mono 16-bit PCM WAV data in-memory without leaving
temporary audio files on disk.
"""

from __future__ import annotations

import io
import logging
import wave
from typing import Optional

from arceus.exceptions import AudioDeviceError

logger = logging.getLogger(__name__)


class AudioRecorder:
    """
    Microphone recorder with Windows 11 compatibility.

    Parameters
    ----------
    sample_rate : int
        Audio sampling rate in Hz (default: 16000, optimal for STT).
    channels : int
        Number of audio channels (default: 1 for mono).
    """

    def __init__(self, sample_rate: int = 16000, channels: int = 1) -> None:
        self.sample_rate = sample_rate
        self.channels = channels

    @staticmethod
    def check_microphone() -> bool:
        """
        Check if at least one audio input device is available.
        """
        try:
            import sounddevice as sd

            devices = sd.query_devices()
            # Look for devices with at least 1 input channel
            input_devs = [
                d for d in devices if isinstance(d, dict) and d.get("max_input_channels", 0) > 0
            ]
            return len(input_devs) > 0
        except Exception as exc:
            logger.warning("Microphone check failed: %s", exc)
            return False

    def record(self, duration: float = 5.0) -> bytes:
        """
        Record audio from the default microphone for *duration* seconds.

        Returns
        -------
        bytes
            In-memory WAV file bytes.

        Raises
        ------
        AudioDeviceError
            If no microphone is available or recording fails.
        """
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise AudioDeviceError(
                "The 'sounddevice' package is required for recording. "
                "Install it with: pip install sounddevice"
            ) from exc

        if not self.check_microphone():
            raise AudioDeviceError(
                "No active microphone detected. Please check your Windows 11 "
                "Microphone settings (Settings > Privacy & security > Microphone) "
                "and ensure microphone access is turned ON."
            )

        num_frames = int(duration * self.sample_rate)
        logger.info("Recording for %.1f seconds (%d frames)...", duration, num_frames)

        try:
            # Record 16-bit signed PCM directly
            audio_array = sd.rec(
                frames=num_frames,
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="int16",
                blocking=True,
            )
        except Exception as exc:
            raise AudioDeviceError(
                f"Audio recording failed: {exc}. Verify that your microphone "
                "is not in use exclusively by another application."
            ) from exc

        # Convert numpy/raw array buffer into a valid in-memory WAV byte stream
        wav_buffer = io.BytesIO()
        try:
            with wave.open(wav_buffer, "wb") as wf:
                wf.setnchannels(self.channels)
                wf.setsampwidth(2)  # 16-bit = 2 bytes
                wf.setframerate(self.sample_rate)
                wf.writeframes(audio_array.tobytes())
            return wav_buffer.getvalue()
        finally:
            wav_buffer.close()
