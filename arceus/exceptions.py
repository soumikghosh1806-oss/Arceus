"""
Custom exception hierarchy for ARCEUS Alpha.

Every ARCEUS-specific error inherits from ArceusError so callers can
catch a single base class when they want a broad safety-net.
"""


class ArceusError(Exception):
    """Base exception for all ARCEUS errors."""


# ── Configuration ──────────────────────────────────────────────────
class ConfigError(ArceusError):
    """Raised when configuration is missing or invalid."""


class MissingAPIKeyError(ConfigError):
    """Raised when a required API key is not set."""

    def __init__(self, key_name: str = "API key") -> None:
        super().__init__(
            f"{key_name} is not configured. "
            f"Set it in your .env file or pass it to the config."
        )
        self.key_name = key_name


# ── Model / backend ───────────────────────────────────────────────
class ModelError(ArceusError):
    """Raised when the AI model backend fails."""


class ModelConnectionError(ModelError):
    """Raised when the model backend is unreachable."""


class ModelResponseError(ModelError):
    """Raised when the model returns an unusable response."""


# ── Conversation ───────────────────────────────────────────────────
class ConversationError(ArceusError):
    """Raised for problems inside the conversation loop."""
