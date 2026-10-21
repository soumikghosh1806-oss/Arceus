"""Unit tests for arceus.model_interface."""

import pytest

from arceus.config import ArceusConfig
from arceus.exceptions import ModelError, MissingAPIKeyError
from arceus.model_interface import (
    EchoModel,
    ModelInterface,
    create_model,
)


class TestEchoModel:
    """EchoModel should deterministically echo the last user message."""

    def setup_method(self):
        self.model = EchoModel(ArceusConfig.default())

    def test_echoes_last_message(self):
        messages = [{"role": "user", "content": "Hello, ARCEUS!"}]
        reply = self.model.generate(messages)
        assert reply == "[ARCEUS echo] Hello, ARCEUS!"

    def test_echoes_last_in_multi_turn(self):
        messages = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "second"},
        ]
        reply = self.model.generate(messages)
        assert "second" in reply

    def test_empty_messages(self):
        reply = self.model.generate([])
        assert "no input" in reply.lower()

    def test_health_check(self):
        assert self.model.health_check() is True

    def test_repr(self):
        r = repr(self.model)
        assert "EchoModel" in r


class TestCreateModel:
    """Factory should create the right backend or raise on unknown."""

    def test_creates_echo(self):
        cfg = ArceusConfig(model_backend="echo")
        model = create_model(cfg)
        assert isinstance(model, EchoModel)

    def test_unknown_backend_raises(self):
        cfg = ArceusConfig(model_backend="nonexistent")
        with pytest.raises(ModelError, match="Unknown model backend"):
            create_model(cfg)

    def test_openai_without_key_raises(self):
        cfg = ArceusConfig(model_backend="openai", openai_api_key="")
        with pytest.raises(MissingAPIKeyError):
            create_model(cfg)


class TestModelInterfaceABC:
    """Cannot instantiate the abstract base class directly."""

    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            ModelInterface(ArceusConfig.default())  # type: ignore[abstract]
