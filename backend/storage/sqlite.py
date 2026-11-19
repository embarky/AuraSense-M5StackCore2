"""
storage/sqlite.py — Local SQLite storage for AuraSense.
"AuraSense: See the air you breathe."

Zero-setup persistence for development and the one-command demo. The file is
shared with the dashboard container through a Docker volume. WAL mode lets the
dashboard read while the backend writes.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

from storage.base import MAX_DAYS, MAX_HOURS, Storage, clamp

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS sensor_readings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,          -- ISO 8601, UTC
    device_id       TEXT    NOT NULL DEFAULT 'default',
    temperature     REAL,
    humidity        REAL,
    pressure        REAL,
    eco2            INTEGER,
    tvoc            INTEGER,
    motion_detected INTEGER NOT NULL DEFAULT 0,
    timezone        TEXT,
    location        TEXT
);
CREATE INDEX IF NOT EXISTS idx_readings_ts ON sensor_readings (timestamp);
"""

_COLUMNS = ("timestamp", "device_id", "temperature", "humidity", "pressure",
            "eco2", "tvoc", "motion_detected", "timezone", "location")


def _iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


class SQLiteStorage(Storage):
    name = "sqlite"

    def __init__(self, path: str) -> None:
        self._path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
        log.info("SQLite storage ready at %s", path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    # ── Write ─────────────────────────────────────────────────────────────────

    def insert_readings(self, rows: list[dict]) -> tuple[bool, str]:
        if not rows:
            return True, "nothing to insert"
        values = [
            tuple(_iso(r["timestamp"]) if c == "timestamp" else r.get(c) for c in _COLUMNS)
            for r in rows
        ]
        placeholders = ", ".join("?" for _ in _COLUMNS)
        try:
            with self._lock, self._connect() as conn:
                conn.executemany(
                    f"INSERT INTO sensor_readings ({', '.join(_COLUMNS)}) VALUES ({placeholders})",
                    values,
                )
            return True, f"{len(values)} row(s) stored"
        except sqlite3.Error as exc:
            log.error("SQLite insert failed: %s", exc)
            return False, str(exc)

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_history(self, hours: int = 24) -> list[dict]:
        since = datetime.now(timezone.utc) - timedelta(hours=clamp(hours, 1, MAX_HOURS))
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT * FROM sensor_readings WHERE timestamp >= ? ORDER BY timestamp DESC",
                (_iso(since),),
            )
            return [dict(r) for r in cur.fetchall()]

    def get_daily_aggregates(self, days: int = 7) -> list[dict]:
        since = datetime.now(timezone.utc) - timedelta(days=clamp(days, 1, MAX_DAYS))
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT substr(timestamp, 1, 10)       AS day,
                       ROUND(AVG(temperature), 2)     AS avg_temp,
                       ROUND(MIN(temperature), 2)     AS min_temp,
                       ROUND(MAX(temperature), 2)     AS max_temp,
                       ROUND(AVG(humidity), 2)        AS avg_hum,
                       ROUND(AVG(eco2), 0)            AS avg_eco2
                FROM sensor_readings
                WHERE timestamp >= ?
                GROUP BY day
                ORDER BY day DESC
                """,
                (_iso(since),),
            )
            return [dict(r) for r in cur.fetchall()]
