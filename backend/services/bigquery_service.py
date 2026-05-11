"""
services/bigquery_service.py — Google BigQuery data layer.

Handles all reads and writes for sensor telemetry.  The table schema is:

    timestamp       TIMESTAMP
    temperature     FLOAT64      (°C, indoor)
    humidity        FLOAT64      (%, indoor)
    pressure        FLOAT64      (hPa, indoor)
    eco2            INT64        (ppm)
    tvoc            INT64        (ppb)
    motion_detected BOOL
    timezone        STRING
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from google.cloud import bigquery

from config import Config


class BigQueryService:
    """Thin wrapper around the BigQuery client for sensor data operations."""

    def __init__(self) -> None:
        self._client  = bigquery.Client(project=Config.GCP_PROJECT)
        self._table   = f"{Config.GCP_PROJECT}.{Config.BQ_DATASET}.{Config.BQ_TABLE}"
        print(f"[BigQueryService] Connected — table: {self._table}")

    # ── Write ─────────────────────────────────────────────────────────────────

    def insert_sensor_reading(self, payload: dict) -> tuple[bool, str]:
        """
        Insert one row of sensor data.

        Parameters
        ----------
        payload:  Dict with keys matching the table schema above.

        Returns
        -------
        (success, message)
        """
        row = {
            "timestamp":       datetime.now(timezone.utc).isoformat(),
            "temperature":     payload.get("temperature"),
            "humidity":        payload.get("humidity"),
            "pressure":        payload.get("pressure"),
            "eco2":            payload.get("eco2"),
            "tvoc":            payload.get("tvoc"),
            "motion_detected": payload.get("motion_detected", False),
            "timezone":        payload.get("timezone", "UTC"),
        }
        errors = self._client.insert_rows_json(self._table, [row])
        if errors:
            msg = f"BigQuery insert error: {errors}"
            print(f"[BigQueryService] ERROR — {msg}")
            return False, msg
        return True, "ok"

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_latest(self) -> Optional[dict]:
        """Return the most recent sensor row, or None if the table is empty."""
        query = f"""
            SELECT *
            FROM `{self._table}`
            ORDER BY timestamp DESC
            LIMIT 1
        """
        rows = list(self._client.query(query).result())
        if not rows:
            return None
        return dict(rows[0])

    def get_history(self, hours: int = 24) -> list[dict]:
        """Return all rows from the last *hours* hours, newest first."""
        query = f"""
            SELECT *
            FROM `{self._table}`
            WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {hours} HOUR)
            ORDER BY timestamp DESC
        """
        return [dict(r) for r in self._client.query(query).result()]

    def get_recent_summary(self, hours: int = 24) -> str:
        """
        Build a compact human-readable summary of recent sensor readings.
        This string is injected into the voice-assistant system prompt so
        Gemini can answer questions like "what was the humidity yesterday?".
        """
        rows = self.get_history(hours)
        if not rows:
            return "No sensor data available."

        latest = rows[0]
        temps  = [r["temperature"] for r in rows if r.get("temperature") is not None]
        hums   = [r["humidity"]    for r in rows if r.get("humidity")    is not None]
        eco2s  = [r["eco2"]        for r in rows if r.get("eco2")        is not None]

        parts = [
            f"Latest reading ({hours}h window):",
            f"  Temp    : {latest.get('temperature', 'N/A')} °C "
            f"(min {min(temps):.1f}, max {max(temps):.1f})" if temps else "",
            f"  Humidity: {latest.get('humidity', 'N/A')} % "
            f"(min {min(hums):.1f}, max {max(hums):.1f})" if hums else "",
            f"  eCO₂    : {latest.get('eco2', 'N/A')} ppm "
            f"(max {max(eco2s)})" if eco2s else "",
            f"  TVOC    : {latest.get('tvoc', 'N/A')} ppb",
            f"  Pressure: {latest.get('pressure', 'N/A')} hPa",
        ]
        return "\n".join(p for p in parts if p)

    def get_daily_aggregates(self, days: int = 7) -> list[dict]:
        """Return daily min/max/avg aggregates for the Streamlit dashboard."""
        query = f"""
            SELECT
                DATE(timestamp) AS day,
                ROUND(AVG(temperature), 2) AS avg_temp,
                ROUND(MIN(temperature), 2) AS min_temp,
                ROUND(MAX(temperature), 2) AS max_temp,
                ROUND(AVG(humidity),    2) AS avg_hum,
                ROUND(AVG(eco2),        0) AS avg_eco2
            FROM `{self._table}`
            WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
            GROUP BY day
            ORDER BY day DESC
        """
        return [dict(r) for r in self._client.query(query).result()]