"""
Pluggable AI model interface for ARCEUS Alpha.

Provides an abstract base class ``ModelInterface`` and three concrete
backends:

* **EchoModel** — deterministic echo (great for tests & offline use)
* **OpenAIModel** — OpenAI chat-completions API
* **OllamaModel** — local Ollama REST API

Use ``create_model()`` to instantiate the right backend from an
``ArceusConfig``.
"""

from __future__ import annotations

import abc
import logging
from typing import Any, Dict, List, Optional

from arceus.config import ArceusConfig
from arceus.exceptions import (
    MissingAPIKeyError,
    ModelConnectionError,
    ModelError,
    ModelResponseError,
)

logger = logging.getLogger(__name__)

# Type alias for a chat message
Message = Dict[str, str]   # {"role": "...", "content": "..."}


# ── Abstract base ──────────────────────────────────────────────────
class ModelInterface(abc.ABC):
    """Abstract base class every ARCEUS model backend must implement."""

    def __init__(self, config: ArceusConfig) -> None:
        self.config = config

    @abc.abstractmethod
    def generate(self, messages: List[Message]) -> str:
        """
        Given a conversation history, return the assistant's next reply.

        Parameters
        ----------
        messages : list[Message]
            Conversation history in OpenAI-style format.

        Returns
        -------
        str
            The model's reply text.

        Raises
        ------
        ModelError
            On any backend failure.
        """

    def health_check(self) -> bool:
        """Return ``True`` if the backend is reachable.  Override for
        real network checks."""
        return True

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} config={self.config.model_backend}>"


# ── Echo backend (testing / offline) ──────────────────────────────
class EchoModel(ModelInterface):
    """Returns the user's last message prefixed with *[ARCEUS echo]*."""

    def generate(self, messages: List[Message]) -> str:
        if not messages:
            return "[ARCEUS echo] (no input)"
        last = messages[-1].get("content", "")
        return f"[ARCEUS echo] {last}"


# ── OpenAI backend ────────────────────────────────────────────────
class OpenAIModel(ModelInterface):
    """Calls the OpenAI chat-completions endpoint."""

    def __init__(self, config: ArceusConfig) -> None:
        super().__init__(config)
        if not config.openai_api_key:
            raise MissingAPIKeyError("ARCEUS_OPENAI_API_KEY")
        # Lazy import so the package is optional at install time
        try:
            from openai import OpenAI  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ModelError(
                "The 'openai' package is required for the OpenAI backend. "
                "Install it with:  pip install openai"
            ) from exc
        self._client = OpenAI(api_key=config.openai_api_key)

    def generate(self, messages: List[Message]) -> str:
        try:
            response = self._client.chat.completions.create(
                model=self.config.openai_model,
                messages=messages,  # type: ignore[arg-type]
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            )
            text = response.choices[0].message.content
            if text is None:
                raise ModelResponseError("OpenAI returned an empty message.")
            return text.strip()
        except ModelResponseError:
            raise
        except Exception as exc:
            logger.exception("OpenAI request failed")
            raise ModelConnectionError(f"OpenAI API error: {exc}") from exc

    def health_check(self) -> bool:
        try:
            self._client.models.list()
            return True
        except Exception:
            return False


# ── Ollama backend ─────────────────────────────────────────────────
class OllamaModel(ModelInterface):
    """Calls a locally-running Ollama server over its /api/generate REST API."""

    def __init__(self, config: ArceusConfig) -> None:
        super().__init__(config)
        try:
            import requests  # noqa: F401  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ModelError(
                "The 'requests' package is required for the Ollama backend. "
                "Install it with:  pip install requests"
            ) from exc

    def _build_prompt_and_system(self, messages: List[Message]) -> tuple[str, str]:
        """
        Extract the system prompt and format conversation turns into a prompt
        suitable for Ollama's /api/generate endpoint.
        """
        system_prompt = self.config.system_prompt or ""
        conversation: List[str] = []

        for msg in messages:
            role = (msg.get("role") or "").lower()
            content = (msg.get("content") or "").strip()
            if not content:
                continue
            if role == "system":
                system_prompt = content
            elif role == "user":
                conversation.append(f"User: {content}")
            elif role == "assistant":
                conversation.append(f"Assistant: {content}")

        if not conversation:
            prompt = ""
        elif len(conversation) == 1 and conversation[0].startswith("User: "):
            # Single-turn user prompt
            prompt = messages[-1].get("content", "").strip()
        else:
            # Multi-turn conversation prompt
            prompt = "\n".join(conversation) + "\nAssistant:"

        return prompt, system_prompt

    def generate(self, messages: List[Message]) -> str:
        import requests

        url = f"{self.config.ollama_host.rstrip('/')}/api/generate"
        prompt, system = self._build_prompt_and_system(messages)

        payload = {
            "model": self.config.ollama_model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {
                "temperature": self.config.temperature,
                "num_predict": self.config.max_tokens,
            },
        }
        try:
            resp = requests.post(url, json=payload, timeout=60)
            if resp.status_code == 404:
                raise ModelError(
                    f"Model '{self.config.ollama_model}' not found in Ollama. "
                    f"Download it by running: ollama pull {self.config.ollama_model}"
                )
            resp.raise_for_status()
            data = resp.json()
            text = data.get("response", "")
            if not text:
                raise ModelResponseError("Ollama returned an empty response.")
            return text.strip()
        except (ModelError, ModelResponseError):
            raise
        except requests.exceptions.Timeout as exc:
            logger.error("Ollama request timed out: %s", exc)
            raise ModelConnectionError(
                f"Ollama request timed out after 60s at {self.config.ollama_host}."
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            logger.error("Ollama connection error: %s", exc)
            raise ModelConnectionError(
                f"Cannot reach Ollama at {self.config.ollama_host}. "
                "Ensure Ollama is running ('ollama serve' or open the Ollama app)."
            ) from exc
        except requests.exceptions.HTTPError as exc:
            logger.error("Ollama HTTP error: %s", exc)
            raise ModelResponseError(f"Ollama HTTP error: {exc}") from exc
        except Exception as exc:
            logger.exception("Ollama request failed")
            raise ModelError(f"Ollama error: {exc}") from exc

    def health_check(self) -> bool:
        import requests

        try:
            r = requests.get(f"{self.config.ollama_host.rstrip('/')}/api/tags", timeout=3)
            return r.status_code == 200
        except Exception:
            return False


# ── Factory ────────────────────────────────────────────────────────
_BACKENDS: Dict[str, type] = {
    "local": OllamaModel,
    "ollama": OllamaModel,
    "echo": EchoModel,
    "openai": OpenAIModel,
}


def create_model(config: ArceusConfig) -> ModelInterface:
    """
    Instantiate the model backend specified in *config.model_backend*.

    Raises ``ModelError`` if the backend name is unknown.
    """
    backend = config.model_backend.lower()
    cls = _BACKENDS.get(backend)
    if cls is None:
        raise ModelError(
            f"Unknown model backend '{backend}'. "
            f"Choose from: {', '.join(_BACKENDS)}"
        )
    logger.info("Creating model backend: %s", backend)
    return cls(config)
