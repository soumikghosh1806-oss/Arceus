"""
Core conversation engine for ARCEUS Alpha.

``ArceusAssistant`` manages the message history and delegates generation
to whichever ``ModelInterface`` backend is active.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from arceus.config import ArceusConfig
from arceus.exceptions import ConversationError
from arceus.model_interface import Message, ModelInterface, create_model

logger = logging.getLogger(__name__)


class ArceusAssistant:
    """
    High-level conversational assistant.

    Parameters
    ----------
    config : ArceusConfig, optional
        If omitted, ``ArceusConfig.default()`` is used.
    model : ModelInterface, optional
        Inject a custom model backend (useful for testing).
        If omitted, one is created from *config*.
    """

    def __init__(
        self,
        config: Optional[ArceusConfig] = None,
        model: Optional[ModelInterface] = None,
    ) -> None:
        self.config = config or ArceusConfig.default()
        self.model = model or create_model(self.config)
        self._history: List[Message] = []

        # Seed with the system prompt
        if self.config.system_prompt:
            self._history.append(
                {"role": "system", "content": self.config.system_prompt}
            )

    # ── Public API ─────────────────────────────────────────────────
    def chat(self, user_input: str) -> str:
        """
        Send *user_input* to the model and return the assistant's reply.

        Raises ``ConversationError`` on empty input.
        """
        if not user_input or not user_input.strip():
            raise ConversationError("User input must not be empty.")

        self._history.append({"role": "user", "content": user_input.strip()})
        self._trim_history()

        reply = self.model.generate(self._history)

        self._history.append({"role": "assistant", "content": reply})
        logger.debug("User: %s | Assistant: %s", user_input.strip(), reply[:80])
        return reply

    def reset(self) -> None:
        """Clear conversation history (keeps the system prompt)."""
        system = [m for m in self._history if m["role"] == "system"]
        self._history = system
        logger.info("Conversation history reset.")

    @property
    def history(self) -> List[Message]:
        """Return a *copy* of the current message history."""
        return list(self._history)

    @property
    def turn_count(self) -> int:
        """Number of user messages sent so far."""
        return sum(1 for m in self._history if m["role"] == "user")

    # ── Internals ──────────────────────────────────────────────────
    def _trim_history(self) -> None:
        """Keep the history within ``max_history`` messages, always
        preserving the system prompt at index 0."""
        limit = self.config.max_history
        if len(self._history) <= limit:
            return
        system = [m for m in self._history if m["role"] == "system"]
        non_system = [m for m in self._history if m["role"] != "system"]
        # Keep only the most recent non-system messages
        keep = limit - len(system)
        self._history = system + non_system[-keep:]
