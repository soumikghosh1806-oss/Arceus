"""Unit tests for arceus.assistant."""

import pytest

from arceus.assistant import ArceusAssistant
from arceus.config import ArceusConfig
from arceus.exceptions import ConversationError
from arceus.model_interface import EchoModel


@pytest.fixture
def assistant():
    """Create an assistant with the echo backend for deterministic tests."""
    cfg = ArceusConfig(model_backend="echo")
    return ArceusAssistant(config=cfg)


class TestChat:
    def test_basic_reply(self, assistant):
        reply = assistant.chat("Hi there")
        assert "[ARCEUS echo]" in reply
        assert "Hi there" in reply

    def test_empty_input_raises(self, assistant):
        with pytest.raises(ConversationError, match="empty"):
            assistant.chat("")

    def test_whitespace_only_raises(self, assistant):
        with pytest.raises(ConversationError, match="empty"):
            assistant.chat("   ")

    def test_turn_count_increments(self, assistant):
        assert assistant.turn_count == 0
        assistant.chat("one")
        assert assistant.turn_count == 1
        assistant.chat("two")
        assert assistant.turn_count == 2


class TestHistory:
    def test_history_starts_with_system(self, assistant):
        history = assistant.history
        assert history[0]["role"] == "system"

    def test_history_grows_after_chat(self, assistant):
        before = len(assistant.history)
        assistant.chat("Hello")
        after = len(assistant.history)
        # +2: one user message, one assistant reply
        assert after == before + 2

    def test_reset_clears_user_messages(self, assistant):
        assistant.chat("Hello")
        assistant.reset()
        assert assistant.turn_count == 0
        # System prompt should survive
        assert any(m["role"] == "system" for m in assistant.history)

    def test_history_returns_copy(self, assistant):
        h = assistant.history
        h.clear()
        assert len(assistant.history) > 0  # original unchanged


class TestTrimHistory:
    def test_trims_when_exceeding_max(self):
        cfg = ArceusConfig(model_backend="echo", max_history=5)
        a = ArceusAssistant(config=cfg)
        for i in range(10):
            a.chat(f"message {i}")
        # Trim fires before generate(); the assistant reply is appended
        # after, so the ceiling is max_history + 1.
        assert len(a.history) <= cfg.max_history + 1

    def test_system_prompt_survives_trim(self):
        cfg = ArceusConfig(model_backend="echo", max_history=4)
        a = ArceusAssistant(config=cfg)
        for i in range(10):
            a.chat(f"msg {i}")
        assert a.history[0]["role"] == "system"


class TestCustomModel:
    def test_injected_model(self):
        """You can inject any ModelInterface for testing."""
        cfg = ArceusConfig.default()
        custom = EchoModel(cfg)
        a = ArceusAssistant(config=cfg, model=custom)
        reply = a.chat("ping")
        assert "ping" in reply
