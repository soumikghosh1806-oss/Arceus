#!/usr/bin/env python3
"""
ARCEUS Alpha v0.1 — interactive CLI entry-point.

Run:
    python main.py                    # uses defaults (echo backend)
    python main.py --backend openai   # uses OpenAI (needs ARCEUS_OPENAI_API_KEY)
    python main.py --config arceus_config.json
"""

from __future__ import annotations

import argparse
import sys

from arceus.assistant import ArceusAssistant
from arceus.config import ArceusConfig
from arceus.exceptions import ArceusError
from arceus.utils import banner, sanitize_input, setup_logging


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ARCEUS Alpha conversational assistant")
    p.add_argument(
        "--backend",
        choices=["local", "ollama", "echo", "openai"],
        default=None,
        help="AI backend to use (default: 'local' / 'ollama' using qwen2.5:3b)",
    )
    p.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to a JSON config file",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    p.add_argument(
        "--voice",
        action="store_true",
        help="Launch ARCEUS in interactive voice conversation mode",
    )
    p.add_argument(
        "--hud",
        action="store_true",
        help="Launch the ARCEUS desktop HUD",
    )
    screen = p.add_mutually_exclusive_group()
    screen.add_argument(
        "--fullscreen",
        action="store_true",
        help="Launch the HUD full-screen",
    )
    screen.add_argument(
        "--windowed",
        action="store_true",
        help="Launch the HUD in a window",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    setup_logging("DEBUG" if args.debug else "INFO")

    if args.hud and args.voice:
        print(
            "[Config error] --hud and --voice cannot be combined: "
            "the HUD has its own microphone control.",
            file=sys.stderr,
        )
        sys.exit(1)

    # ── Build config ───────────────────────────────────────────
    try:
        if args.config:
            config = ArceusConfig.from_json(args.config)
        else:
            config = ArceusConfig.default()

        if args.backend:
            object.__setattr__(config, "model_backend", args.backend)
    except ArceusError as exc:
        print(f"[Config error] {exc}", file=sys.stderr)
        sys.exit(1)

    # ── Create assistant ───────────────────────────────────────
    try:
        assistant = ArceusAssistant(config=config)
    except ArceusError as exc:
        print(f"[Startup error] {exc}", file=sys.stderr)
        sys.exit(1)

    # ── Voice mode branch ──────────────────────────────────────
    if args.hud:
        from arceus.exceptions import HudError
        from arceus.hud import app as hud_app

        fullscreen = (
            args.fullscreen
            or (bool(config.hud_fullscreen) and not args.windowed)
        )
        try:
            sys.exit(
                hud_app.run_hud(
                    assistant=assistant,
                    config=config,
                    fullscreen=fullscreen,
                )
            )
        except HudError as exc:
            print(f"[HUD error] {exc}", file=sys.stderr)
            sys.exit(1)

    if args.voice:
        from arceus.voice.controller import VoiceConversationController

        print(banner())
        print(f"  Config: {config.summary()}")
        controller = VoiceConversationController(assistant=assistant, config=config)
        controller.run_loop()
        return

    # ── Text REPL ──────────────────────────────────────────────
    print(banner())
    print(f"  Config: {config.summary()}")
    print("  Type 'quit' or 'exit' to leave.  '/reset' clears history.\n")

    while True:
        try:
            user_input = input("You ➤ ")
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        cleaned = sanitize_input(user_input)
        if not cleaned:
            continue
        if cleaned.lower() in ("quit", "exit"):
            print("Goodbye!")
            break
        if cleaned.lower() == "/reset":
            assistant.reset()
            print("[History cleared]\n")
            continue

        try:
            reply = assistant.chat(cleaned)
            print(f"ARCEUS ➤ {reply}\n")
        except ArceusError as exc:
            print(f"[Error] {exc}\n", file=sys.stderr)


if __name__ == "__main__":
    main()
