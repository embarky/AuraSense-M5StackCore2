"""
services/bigquery_service.py — Google BigQuery data layer for AuraSense.

Actual table: caa-project-493719.iot_data.sensor_logs

Schema (matches what was created in BigQuery Console):
    timestamp       TIMESTAMP
    temperature     FLOAT
    humidity        FLOAT
    pressure        FLOAT
    tvoc            INTEGER
    eco2            INTEGER
    motion_detected INTEGER   (0 or 1, not BOOLEAN)
    timezone        STRING
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from google.cloud import bigquery
from google.api_core.exceptions import GoogleAPIError, RetryError
from urllib3.exceptions import ProtocolError

from config import Config


class BigQueryService:
    """Thin wrapper around the BigQuery client for AuraSense sensor operations."""

    def __init__(self) -> None:
        self._client = bigquery.Client(project=Config.GCP_PROJECT)
        self._table  = f"{Config.GCP_PROJECT}.{Config.BQ_DATASET}.{Config.BQ_TABLE}"
        print(f"[AuraSense | BigQuery] Connected to table: {self._table}")

    # ── Write ─────────────────────────────────────────────────────────────────

    def insert_sensor_reading(self, payload: dict) -> tuple[bool, str]:
        """
        Insert one row of sensor data into BigQuery. 
        Wrapped in comprehensive try/except blocks to prevent Google API 
        timeouts (e.g., due to local OS sleep or proxy drops) from crashing Flask.
        
        Returns (success, message).
        """
        row = {
            "timestamp":       datetime.now(timezone.utc).isoformat(),
            "temperature":     payload.get("temperature"),
            "humidity":        payload.get("humidity"),
            "pressure":        payload.get("pressure"),
            "eco2":            payload.get("eco2"),
            "tvoc":            payload.get("tvoc"),
            # motion_detected is INTEGER in this table (not BOOLEAN)
            "motion_detected": int(bool(payload.get("motion_detected", 0))),
            "timezone":        payload.get("timezone", "UTC"),
        }

        # 🌟 ARMOR PLATING: Catch network and API errors to prevent HTTP 500s
        try:
            errors = self._client.insert_rows_json(self._table, [row])
            if errors:
                msg = f"BigQuery row rejected: {errors}"
                print(f"[AuraSense | BigQuery] WARNING — {msg}")
                return False, msg
                
            return True, "ok"

        except (GoogleAPIError, RetryError, ProtocolError, ConnectionError) as exc:
            msg = f"Network or API Error while reaching Google Cloud: {type(exc).__name__}"
            print(f"[AuraSense | BigQuery] ERROR — {msg}")
            # We return False safely so the Flask route can handle it gracefully 
            # without crashing the whole application thread.
            return False, msg
            
        except Exception as exc:
            msg = f"Unexpected Error during BigQuery insert: {exc}"
            print(f"[AuraSense | BigQuery] FATAL — {msg}")
            return False, msg

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_latest(self) -> Optional[dict]:
        """Return the most recent sensor row, or None if the table is empty."""
        query = f"""
            SELECT *
            FROM `{self._table}`
            ORDER BY timestamp DESC
            LIMIT 1
        """
        try:
            rows = list(self._client.query(query).result())
            if not rows:
                return None
            return dict(rows[0])
        except Exception as exc:
            print(f"[AuraSense | BigQuery] Query Error (get_latest): {exc}")
            return None

    def get_history(self, hours: int = 24) -> list[dict]:
        """Return all rows from the last *hours* hours, newest first."""
        query = f"""
            SELECT *
            FROM `{self._table}`
            WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {hours} HOUR)
            ORDER BY timestamp DESC
        """
        try:
            return [dict(r) for r in self._client.query(query).result()]
        except Exception as exc:
            print(f"[AuraSense | BigQuery] Query Error (get_history): {exc}")
            return []

    def get_recent_summary(self, hours: int = 24) -> str:
        """
        Build a compact human-readable summary of recent sensor readings.
        Injected into the voice-assistant system prompt so Gemini can answer
        contextual questions.
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

    def get_daily_aggregates(self, days: int = 7) -> list[dict]:
        """Return daily min/max/avg aggregates for the AuraSense Streamlit dashboard."""
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
        try:
            return [dict(r) for r in self._client.query(query).result()]
        except Exception as exc:
            print(f"[AuraSense | BigQuery] Query Error (get_daily_aggregates): {exc}")
            return []