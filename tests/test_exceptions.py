"""Unit tests for arceus.exceptions."""

import pytest

from arceus.exceptions import (
    ArceusError,
    AudioDeviceError,
    ConfigError,
    ConversationError,
    MissingAPIKeyError,
    ModelConnectionError,
    ModelError,
    ModelResponseError,
    SpeechRecognitionError,
    SpeechSynthesisError,
    VoiceError,
)


class TestExceptionHierarchy:
    """Every custom exception must be catchable as ArceusError."""

    @pytest.mark.parametrize(
        "exc_cls",
        [
            ConfigError,
            MissingAPIKeyError,
            ModelError,
            ModelConnectionError,
            ModelResponseError,
            ConversationError,
            VoiceError,
            AudioDeviceError,
            SpeechRecognitionError,
            SpeechSynthesisError,
        ],
    )
    def test_subclass_of_arceus_error(self, exc_cls):
        assert issubclass(exc_cls, ArceusError)

    def test_missing_api_key_message(self):
        exc = MissingAPIKeyError("MY_KEY")
        assert "MY_KEY" in str(exc)
        assert exc.key_name == "MY_KEY"
