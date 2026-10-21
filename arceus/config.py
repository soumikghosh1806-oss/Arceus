"""
Configuration management for ARCEUS Alpha.

Priority order (highest → lowest):
  1. Keyword arguments passed directly to ArceusConfig()
  2. Environment variables (loaded from .env via python-dotenv)
  3. Built-in defaults
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from dotenv import load_dotenv

    load_dotenv()  # load .env into os.environ early
except ImportError:
    pass  # python-dotenv is optional at import time

from arceus.exceptions import ConfigError

# ── Defaults ───────────────────────────────────────────────────────
_DEFAULTS: Dict[str, Any] = {
    "model_backend": "echo",          # echo | openai | ollama
    "openai_api_key": "",
    "openai_model": "gpt-3.5-turbo",
    "ollama_host": "http://localhost:11434",
    "ollama_model": "llama3",
    "system_prompt": (
        "You are ARCEUS, a friendly and helpful conversational assistant. "
        "Answer clearly and concisely."
    ),
    "max_history": 50,                # messages kept in context
    "temperature": 0.7,
    "max_tokens": 1024,
}


@dataclass
class ArceusConfig:
    """Immutable-ish configuration object with layered resolution."""

    model_backend: str = ""
    openai_api_key: str = ""
    openai_model: str = ""
    ollama_host: str = ""
    ollama_model: str = ""
    system_prompt: str = ""
    max_history: int = 0
    temperature: float = 0.0
    max_tokens: int = 0

    # private store for extra / unknown keys
    _extras: Dict[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        """Resolve each field: explicit → env var → default."""
        for key, default in _DEFAULTS.items():
            current = getattr(self, key, None)
            if current in (None, "", 0, 0.0):
                env_val = os.environ.get(f"ARCEUS_{key.upper()}", "")
                if env_val:
                    # cast to the type of the default
                    if isinstance(default, int):
                        current = int(env_val)
                    elif isinstance(default, float):
                        current = float(env_val)
                    else:
                        current = env_val
                else:
                    current = default
                object.__setattr__(self, key, current)

    # ── Convenience loaders ────────────────────────────────────────
    @classmethod
    def from_json(cls, path: str | Path) -> "ArceusConfig":
        """Load config from a JSON file, with defaults as fallback."""
        path = Path(path)
        if not path.exists():
            raise ConfigError(f"Config file not found: {path}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"Invalid JSON in {path}: {exc}") from exc

        known_keys = set(_DEFAULTS.keys())
        known = {k: v for k, v in data.items() if k in known_keys}
        extras = {k: v for k, v in data.items() if k not in known_keys}

        cfg = cls(**known)
        cfg._extras = extras
        return cfg

    @classmethod
    def default(cls) -> "ArceusConfig":
        """Return a config built entirely from env vars / defaults."""
        return cls()

    # ── Helpers ────────────────────────────────────────────────────
    def to_dict(self) -> Dict[str, Any]:
        """Serialize config (excluding extras) to a plain dict."""
        return {k: getattr(self, k) for k in _DEFAULTS}

    def summary(self) -> str:
        """Human-readable one-liner for startup banners."""
        return (
            f"backend={self.model_backend}  "
            f"model={self.openai_model if self.model_backend == 'openai' else self.ollama_model}  "
            f"temp={self.temperature}  max_tokens={self.max_tokens}"
        )
