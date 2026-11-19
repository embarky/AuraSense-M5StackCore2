"""
storage/base.py — Storage interface for AuraSense sensor readings.
"AuraSense: See the air you breathe."

Two implementations exist:

* ``SQLiteStorage``   — local file, zero setup; default for development and demos
* ``BigQueryStorage`` — Google BigQuery; used for the cloud deployment

Routes only talk to this interface, so the backend runs the same way with
either one. Choose with the ``STORAGE_BACKEND`` setting ("sqlite" or "bigquery").
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

MAX_HOURS = 24 * 7
MAX_DAYS  = 90


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def normalise_reading(payload: dict, ts: Optional[datetime] = None) -> dict:
    """Map a device payload to a storage row with a timezone-aware UTC timestamp."""
    ts = ts or datetime.now(timezone.utc)
    return {
        "timestamp":       ts.astimezone(timezone.utc),
        "temperature":     payload.get("temperature"),
        "humidity":        payload.get("humidity"),
        "pressure":        payload.get("pressure"),
        "eco2":            payload.get("eco2"),
        "tvoc":            payload.get("tvoc"),
        "motion_detected": int(bool(payload.get("motion_detected", payload.get("motion", 0)))),
        "timezone":        payload.get("timezone", "UTC"),
        "location":        payload.get("location"),
        "device_id":       payload.get("device_id", "default"),
    }


class Storage(ABC):
    """Persistence for sensor readings."""

    name = "abstract"

    @abstractmethod
    def insert_readings(self, rows: list[dict]) -> tuple[bool, str]:
        """Persist rows produced by ``normalise_reading``. Returns (success, message)."""

    @abstractmethod
    def get_history(self, hours: int = 24) -> list[dict]:
        """All readings from the last ``hours`` hours, newest first."""

    @abstractmethod
    def get_daily_aggregates(self, days: int = 7) -> list[dict]:
        """Per-day avg/min/max of temperature, avg humidity and avg eCO2."""

    # ── Shared helpers ────────────────────────────────────────────────────────

    def insert_sensor_reading(self, payload: dict) -> tuple[bool, str]:
        """Store a single reading timestamped now (kept for compatibility)."""
        return self.insert_readings([normalise_reading(payload)])

    def get_recent_summary(self, hours: int = 24) -> str:
        """
        Compact human-readable summary of recent readings. Injected into the
        voice-assistant prompt so it can answer questions about the home.
        """
        rows = self.get_history(hours)
        if not rows:
            return "No recent AuraSense data available."

        latest = rows[0]
        temps  = [r["temperature"] for r in rows if r.get("temperature") is not None]
        hums   = [r["humidity"]    for r in rows if r.get("humidity")    is not None]
        eco2s  = [r["eco2"]        for r in rows if r.get("eco2")        is not None]

        parts = [
            f"Latest reading ({hours}h window):",
            (f"  Temp    : {latest.get('temperature', 'N/A')} °C "
             f"(min {min(temps):.1f}, max {max(temps):.1f})") if temps else "",
            (f"  Humidity: {latest.get('humidity', 'N/A')} % "
             f"(min {min(hums):.1f}, max {max(hums):.1f})") if hums else "",
            (f"  eCO2    : {latest.get('eco2', 'N/A')} ppm "
             f"(max {max(eco2s)})") if eco2s else "",
            f"  TVOC    : {latest.get('tvoc', 'N/A')} ppb",
            f"  Pressure: {latest.get('pressure', 'N/A')} hPa",
        ]
        return "\n".join(p for p in parts if p)
