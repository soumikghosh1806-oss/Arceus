"""
Real system measurements for the HUD, using only the standard library.

Every reader returns ``None`` when a value cannot be measured on this
platform, and the UI then shows ``N/A`` — nothing is ever estimated.
"""

from __future__ import annotations

import array
import io
import math
import sys
import wave
from typing import Dict, Optional, Tuple

GIB = 1024 ** 3


# ── Pure calculations (unit-tested) ────────────────────────────────
def cpu_percent_between(
    prev: Tuple[int, int], curr: Tuple[int, int]
) -> Optional[float]:
    """CPU busy % between two ``(idle, total)`` counter samples."""
    d_idle = curr[0] - prev[0]
    d_total = curr[1] - prev[1]
    if d_total <= 0 or d_idle < 0:
        return None
    return round(max(0.0, min(100.0, (1.0 - d_idle / d_total) * 100.0)), 1)


def wav_levels(wav_bytes: bytes) -> Optional[Dict[str, float]]:
    """
    Peak and RMS level of a 16-bit PCM WAV buffer, in dBFS.

    This is a real measurement of what the microphone captured.  Returns
    ``None`` for empty / unsupported audio.
    """
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            if wf.getsampwidth() != 2 or wf.getnframes() == 0:
                return None
            raw = wf.readframes(wf.getnframes())
    except (wave.Error, EOFError):
        return None

    samples = array.array("h")
    samples.frombytes(raw[: len(raw) - (len(raw) % 2)])
    if sys.byteorder == "big":
        samples.byteswap()
    if not samples:
        return None

    peak = max(max(samples), -min(samples))
    mean_square = sum(s * s for s in samples) / len(samples)
    return {
        "peak_dbfs": _dbfs(peak),
        "rms_dbfs": _dbfs(math.sqrt(mean_square)),
    }


def _dbfs(amplitude: float) -> float:
    if amplitude <= 0:
        return -96.0
    return round(max(-96.0, 20.0 * math.log10(amplitude / 32768.0)), 1)


# ── Platform readers ───────────────────────────────────────────────
def _read_cpu_counters() -> Optional[Tuple[int, int]]:
    """Return cumulative ``(idle, total)`` CPU time, or ``None`` if unreadable."""
    try:
        if sys.platform == "win32":
            import ctypes

            class FILETIME(ctypes.Structure):
                _fields_ = [("lo", ctypes.c_uint32), ("hi", ctypes.c_uint32)]

            idle, kernel, user = FILETIME(), FILETIME(), FILETIME()
            ok = ctypes.windll.kernel32.GetSystemTimes(  # type: ignore[attr-defined]
                ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
            )
            if not ok:
                return None
            to_int = lambda ft: (ft.hi << 32) | ft.lo  # noqa: E731
            # Kernel time already includes idle time on Windows.
            return to_int(idle), to_int(kernel) + to_int(user)

        if sys.platform.startswith("linux"):
            with open("/proc/stat", "r", encoding="ascii") as fh:
                fields = [int(x) for x in fh.readline().split()[1:]]
            idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
            return idle, sum(fields[:8])
    except Exception:  # noqa: BLE001 - metrics must never crash the HUD
        return None
    return None


def _read_memory() -> Optional[Tuple[int, int]]:
    """Return ``(used_bytes, total_bytes)`` of physical RAM, or ``None``."""
    try:
        if sys.platform == "win32":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_uint32),
                    ("dwMemoryLoad", ctypes.c_uint32),
                    ("ullTotalPhys", ctypes.c_uint64),
                    ("ullAvailPhys", ctypes.c_uint64),
                    ("ullTotalPageFile", ctypes.c_uint64),
                    ("ullAvailPageFile", ctypes.c_uint64),
                    ("ullTotalVirtual", ctypes.c_uint64),
                    ("ullAvailVirtual", ctypes.c_uint64),
                    ("ullAvailExtendedVirtual", ctypes.c_uint64),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(  # type: ignore[attr-defined]
                ctypes.byref(stat)
            ):
                return None
            return stat.ullTotalPhys - stat.ullAvailPhys, stat.ullTotalPhys

        if sys.platform.startswith("linux"):
            info: Dict[str, int] = {}
            with open("/proc/meminfo", "r", encoding="ascii") as fh:
                for line in fh:
                    key, _, rest = line.partition(":")
                    info[key] = int(rest.split()[0]) * 1024
            total = info["MemTotal"]
            return total - info["MemAvailable"], total
    except Exception:  # noqa: BLE001
        return None
    return None


class SystemMetrics:
    """Samples CPU and RAM.  Call :meth:`sample` about once per second."""

    def __init__(self) -> None:
        self._prev_cpu = _read_cpu_counters()

    def sample(self) -> Dict[str, Optional[float]]:
        cpu: Optional[float] = None
        curr = _read_cpu_counters()
        if curr is not None and self._prev_cpu is not None:
            cpu = cpu_percent_between(self._prev_cpu, curr)
        if curr is not None:
            self._prev_cpu = curr

        used_gb = total_gb = ram_pct = None
        mem = _read_memory()
        if mem is not None and mem[1] > 0:
            used_gb = round(mem[0] / GIB, 1)
            total_gb = round(mem[1] / GIB, 1)
            ram_pct = round(mem[0] / mem[1] * 100.0, 1)

        return {
            "cpu_percent": cpu,
            "ram_used_gb": used_gb,
            "ram_total_gb": total_gb,
            "ram_percent": ram_pct,
        }
