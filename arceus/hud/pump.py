"""Thread-safe hand-off of events from worker threads to the UI thread."""

from __future__ import annotations

import json
import threading
from typing import Any, Dict, List

# For these types only the newest event matters, so older ones that are still
# queued are dropped (keeps the web view quiet if the UI thread is busy).
_COALESCE = {"metrics", "backend", "devices"}


class EventPump:
    """Collects events from any thread; the UI thread calls :meth:`drain`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: List[Dict[str, Any]] = []

    def push(self, event: Dict[str, Any]) -> None:
        with self._lock:
            if event.get("type") in _COALESCE:
                self._events = [e for e in self._events if e.get("type") != event["type"]]
            self._events.append(event)

    def drain(self) -> List[str]:
        """Return queued events as JSON strings (oldest first) and clear the queue."""
        with self._lock:
            events, self._events = self._events, []
        return [json.dumps(e, ensure_ascii=False) for e in events]
