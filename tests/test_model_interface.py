"""Unit tests for arceus.model_interface."""

import pytest

from arceus.config import ArceusConfig
from arceus.exceptions import (
    MissingAPIKeyError,
    ModelConnectionError,
    ModelError,
    ModelResponseError,
)
from arceus.model_interface import (
    EchoModel,
    ModelInterface,
    OllamaModel,
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

    def test_creates_local(self):
        cfg = ArceusConfig(model_backend="local")
        model = create_model(cfg)
        assert isinstance(model, OllamaModel)

    def test_creates_ollama(self):
        cfg = ArceusConfig(model_backend="ollama")
        model = create_model(cfg)
        assert isinstance(model, OllamaModel)

    def test_unknown_backend_raises(self):
        cfg = ArceusConfig(model_backend="nonexistent")
        with pytest.raises(ModelError, match="Unknown model backend"):
            create_model(cfg)

    def test_openai_without_key_raises(self):
        cfg = ArceusConfig(model_backend="openai", openai_api_key="")
        with pytest.raises(MissingAPIKeyError):
            create_model(cfg)


class TestOllamaModel:
    """Unit tests for OllamaModel logic using mocked HTTP responses."""

    def test_build_prompt_single_turn(self):
        cfg = ArceusConfig(model_backend="local", ollama_model="qwen2.5:3b")
        model = OllamaModel(cfg)
        messages = [
            {"role": "system", "content": "You are ARCEUS."},
            {"role": "user", "content": "What is 2+2?"},
        ]
        prompt, system = model._build_prompt_and_system(messages)
        assert prompt == "What is 2+2?"
        assert system == "You are ARCEUS."

    def test_build_prompt_multi_turn(self):
        cfg = ArceusConfig(model_backend="local", ollama_model="qwen2.5:3b")
        model = OllamaModel(cfg)
        messages = [
            {"role": "system", "content": "You are ARCEUS."},
            {"role": "user", "content": "First turn"},
            {"role": "assistant", "content": "First reply"},
            {"role": "user", "content": "Second turn"},
        ]
        prompt, system = model._build_prompt_and_system(messages)
        assert "User: First turn" in prompt
        assert "Assistant: First reply" in prompt
        assert "User: Second turn" in prompt
        assert prompt.endswith("Assistant:")
        assert system == "You are ARCEUS."

    def test_generate_success(self, monkeypatch):
        import requests

        class FakeResponse:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"response": "The answer is 4."}

        def mock_post(url, json, timeout):
            assert "/api/generate" in url
            assert json["model"] == "qwen2.5:3b"
            return FakeResponse()

        monkeypatch.setattr(requests, "post", mock_post)

        cfg = ArceusConfig(model_backend="local", ollama_model="qwen2.5:3b")
        model = OllamaModel(cfg)
        reply = model.generate([{"role": "user", "content": "What is 2+2?"}])
        assert reply == "The answer is 4."

    def test_generate_missing_model_raises_model_error(self, monkeypatch):
        import requests

        class Fake404:
            status_code = 404

        monkeypatch.setattr(requests, "post", lambda *a, **k: Fake404())

        cfg = ArceusConfig(model_backend="local", ollama_model="nonexistent_model")
        model = OllamaModel(cfg)
        with pytest.raises(ModelError, match="not found in Ollama"):
            model.generate([{"role": "user", "content": "hi"}])

    def test_generate_connection_error(self, monkeypatch):
        import requests

        def mock_post(*a, **k):
            raise requests.exceptions.ConnectionError("Connection refused")

        monkeypatch.setattr(requests, "post", mock_post)

        cfg = ArceusConfig(model_backend="local", ollama_model="qwen2.5:3b")
        model = OllamaModel(cfg)
        with pytest.raises(ModelConnectionError, match="Cannot reach Ollama"):
            model.generate([{"role": "user", "content": "hi"}])

    def test_generate_timeout_error(self, monkeypatch):
        import requests

        def mock_post(*a, **k):
            raise requests.exceptions.Timeout("Timed out")

        monkeypatch.setattr(requests, "post", mock_post)

        cfg = ArceusConfig(model_backend="local", ollama_model="qwen2.5:3b")
        model = OllamaModel(cfg)
        with pytest.raises(ModelConnectionError, match="timed out"):
            model.generate([{"role": "user", "content": "hi"}])


class TestModelInterfaceABC:
    """Cannot instantiate the abstract base class directly."""

    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            ModelInterface(ArceusConfig.default())  # type: ignore[abstract]
