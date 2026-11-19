"""
storage/bigquery.py — Google BigQuery storage for AuraSense (cloud deployment).

Table: <gcp_project>.<bq_dataset>.<bq_table> (configured in config.json)

All time-window values are passed as query parameters and clamped to a
maximum range, so a request can never inject SQL or trigger a full-table scan.

Schema:
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

import logging
from typing import Optional

from config import Config
from google.api_core.exceptions import GoogleAPIError, RetryError
from google.cloud import bigquery
from urllib3.exceptions import ProtocolError

from storage.base import MAX_DAYS, MAX_HOURS, Storage
from storage.base import clamp as _clamp

log = logging.getLogger(__name__)

# Columns of the existing BigQuery table (device_id / location are not stored)
_BQ_COLUMNS = ("temperature", "humidity", "pressure", "eco2", "tvoc", "timezone")


class BigQueryStorage(Storage):
    """BigQuery implementation of the AuraSense storage interface."""

    name = "bigquery"

    def __init__(self) -> None:
        self._client = bigquery.Client(project=Config.GCP_PROJECT)
        self._table  = f"{Config.GCP_PROJECT}.{Config.BQ_DATASET}.{Config.BQ_TABLE}"
        log.info("Connected to BigQuery table: %s", self._table)

    # ── Write ─────────────────────────────────────────────────────────────────

    def insert_readings(self, rows: list[dict]) -> tuple[bool, str]:
        """
        Insert rows into BigQuery using the streaming API.
        Network and API errors are caught so a cloud outage never crashes the API.
        Returns (success, message).
        """
        bq_rows = [
            {
                "timestamp":       r["timestamp"].isoformat(),
                "motion_detected": int(r.get("motion_detected", 0)),
                **{c: r.get(c) for c in _BQ_COLUMNS},
            }
            for r in rows
        ]
        try:
            errors = self._client.insert_rows_json(self._table, bq_rows)
            if errors:
                msg = f"BigQuery rows rejected: {errors}"
                log.warning("%s", msg)
                return False, msg
            return True, "ok"

        except (GoogleAPIError, RetryError, ProtocolError, ConnectionError) as exc:
            msg = f"Network or API error while reaching Google Cloud: {type(exc).__name__}"
            log.error("%s", msg)
            return False, msg

        except Exception as exc:
            msg = f"Unexpected error during BigQuery insert: {exc}"
            log.exception("%s", msg)
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
            log.error("Query error (get_latest): %s", exc)
            return None

    def get_history(self, hours: int = 24) -> list[dict]:
        """Return all rows from the last *hours* hours, newest first."""
        query = f"""
            SELECT *
            FROM `{self._table}`
            WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @hours HOUR)
            ORDER BY timestamp DESC
        """
        params = [bigquery.ScalarQueryParameter("hours", "INT64", _clamp(hours, 1, MAX_HOURS))]
        try:
            return self._run(query, params)
        except Exception as exc:
            log.error("Query error (get_history): %s", exc)
            return []

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
            WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)
            GROUP BY day
            ORDER BY day DESC
        """
        params = [bigquery.ScalarQueryParameter("days", "INT64", _clamp(days, 1, MAX_DAYS))]
        try:
            return self._run(query, params)
        except Exception as exc:
            log.error("Query error (get_daily_aggregates): %s", exc)
            return []

    # ── Internal ──────────────────────────────────────────────────────────────

    def _run(self, query: str, params: list) -> list[dict]:
        """Execute a parameterised query and return rows as dictionaries."""
        job_config = bigquery.QueryJobConfig(query_parameters=params)
        return [dict(r) for r in self._client.query(query, job_config=job_config).result()]
