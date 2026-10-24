"""
Probes that ask the real services what state they are in.

* Ollama: reachable? is the configured model installed? is it loaded, and
  in GPU or CPU memory?  (answered by Ollama's own ``/api/tags`` and
  ``/api/ps`` endpoints — the HUD never assumes the GPU is in use.)
* Microphone: is an input device present?
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

NA = "N/A"


def classify_residency(size: Optional[int], size_vram: Optional[int]) -> Dict[str, Any]:
    """Turn Ollama's ``size`` / ``size_vram`` byte counts into GPU / CPU / SPLIT."""
    if not size or size <= 0 or size_vram is None:
        return {"state": NA, "gpu_percent": None}
    pct = round(max(0.0, min(100.0, size_vram / size * 100.0)), 0)
    if size_vram <= 0:
        return {"state": "CPU", "gpu_percent": 0.0}
    if size_vram >= size:
        return {"state": "GPU", "gpu_percent": 100.0}
    return {"state": "SPLIT", "gpu_percent": pct}


def _model_matches(configured: str, listed: str) -> bool:
    """Ollama lists ``name:tag``; a bare configured name means ``:latest``."""
    configured = configured.strip().lower()
    listed = listed.strip().lower()
    if configured == listed:
        return True
    if ":" not in configured:
        return listed == f"{configured}:latest"
    return False


def probe_ollama(
    host: str,
    model: str,
    timeout: float = 3.0,
    http_get: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """
    Ask a running Ollama server about itself.

    Returns a dict with ``connection`` ("CONNECTED" / "DISCONNECTED"),
    ``model_installed`` (bool | None) and ``residency``.
    """
    result: Dict[str, Any] = {
        "connection": "DISCONNECTED",
        "model_installed": None,
        "residency": {"state": NA, "gpu_percent": None},
        "error": "",
    }
    if http_get is None:
        try:
            import requests

            http_get = requests.get
        except ImportError:
            result["error"] = "The 'requests' package is not installed."
            return result

    base = host.rstrip("/")
    try:
        tags = http_get(f"{base}/api/tags", timeout=timeout)
        if tags.status_code != 200:
            result["error"] = f"Ollama answered HTTP {tags.status_code}."
            return result
    except Exception as exc:  # noqa: BLE001 - any failure means "not reachable"
        result["error"] = f"Cannot reach Ollama at {host}."
        logger.debug("Ollama probe failed: %s", exc)
        return result

    result["connection"] = "CONNECTED"
    try:
        names = [m.get("name", "") for m in tags.json().get("models", [])]
        result["model_installed"] = any(_model_matches(model, n) for n in names)
    except Exception:  # noqa: BLE001
        result["model_installed"] = None

    try:
        ps = http_get(f"{base}/api/ps", timeout=timeout)
        if ps.status_code == 200:
            loaded = [
                m for m in ps.json().get("models", [])
                if _model_matches(model, m.get("name", "") or m.get("model", ""))
            ]
            if loaded:
                result["residency"] = classify_residency(
                    loaded[0].get("size"), loaded[0].get("size_vram")
                )
            else:
                result["residency"] = {"state": "IDLE", "gpu_percent": None}
    except Exception:  # noqa: BLE001
        pass  # residency stays N/A

    return result


def probe_microphone() -> Dict[str, Any]:
    """Report whether an audio input device exists (real device query)."""
    try:
        import sounddevice  # noqa: F401
    except Exception:  # noqa: BLE001 - ImportError or a broken PortAudio install
        return {"mic": NA, "mic_detail": "sounddevice is not available"}

    from arceus.voice.audio_input import AudioRecorder

    if AudioRecorder.check_microphone():
        return {"mic": "AVAILABLE", "mic_detail": ""}
    return {"mic": "NOT DETECTED", "mic_detail": "No input device found"}
