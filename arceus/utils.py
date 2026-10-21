"""
Small helper utilities used across ARCEUS Alpha.
"""

from __future__ import annotations

import logging
import sys


def setup_logging(level: str = "INFO") -> None:
    """Configure root logging with a clean console format."""
    numeric = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric,
        format="%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def banner() -> str:
    """Return the ARCEUS startup banner."""
    return (
        "\n"
        "    ╔═══════════════════════════════════════╗\n"
        "    ║       A R C E U S   Alpha  v0.1       ║\n"
        "    ║   Beginner-Friendly AI Assistant       ║\n"
        "    ╚═══════════════════════════════════════╝\n"
    )


def sanitize_input(text: str) -> str:
    """Strip leading/trailing whitespace and collapse internal runs of
    whitespace to single spaces."""
    return " ".join(text.split())
