"""Names and limits shared between the Python backend and the web front-end."""

from __future__ import annotations

from enum import Enum


class HudState(str, Enum):
    """The five assistant states the HUD core can show."""

    STANDBY = "STANDBY"
    LISTENING = "LISTENING"
    PROCESSING = "PROCESSING"
    SPEAKING = "SPEAKING"
    ERROR = "ERROR"


# Events sent to the front-end (every event also carries ``type``, ``seq``, ``ts``).
EVENT_TYPES = (
    "snapshot",   # full state, sent on (re)connect
    "state",      # core state change
    "message",    # one transcript line
    "activity",   # one recent-activity line
    "backend",    # AI backend connection / model / residency
    "devices",    # microphone status, last capture level
    "voice",      # speech engines once the voice pipeline is loaded
    "metrics",    # CPU / RAM / runtime
    "reset",      # conversation cleared
)

MAX_INPUT_CHARS = 4000        # longest message accepted from the UI
MAX_MESSAGES = 500            # transcript lines kept for snapshots
MAX_ACTIVITY = 200            # activity lines kept for snapshots
MAX_DETAIL_CHARS = 180        # status-line length for ERROR details
