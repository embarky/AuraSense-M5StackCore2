"""
dashboard/sqlite_source.py — Local SQLite data source for the dashboard.
"AuraSense: See the air you breathe."

Used when DATA_SOURCE=sqlite (the local demo). Reads the database file the
backend writes (shared through a Docker volume) and computes every view with
pandas, returning exactly the same columns as the BigQuery queries in data.py,
so app.py and charts.py work unchanged with either source.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from anomalies import anomaly_episodes, is_anomalous, THRESH

log = logging.getLogger(__name__)

SQLITE_PATH = os.getenv("SQLITE_PATH", "/data/aurasense.db")
LOCAL_TZ    = ZoneInfo("Europe/Zurich")

_EMPTY_PEAK = {"peak": 0, "avg": 0, "peak_time": None, "mins_above_800": 0, "mins_above_1500": 0}


def _iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


def _load(since: datetime, until: datetime | None = None) -> pd.DataFrame:
    """Raw readings in [since, until], with a tz-aware UTC timestamp column."""
    if not os.path.exists(SQLITE_PATH):
        return pd.DataFrame()
    query = "SELECT * FROM sensor_readings WHERE timestamp >= ?"
    params = [_iso(since)]
    if until is not None:
        query += " AND timestamp <= ?"
        params.append(_iso(until))
    try:
        # Read-only connection: the dashboard never writes.
        with sqlite3.connect(f"file:{SQLITE_PATH}?mode=ro", uri=True, timeout=5) as conn:
            df = pd.read_sql_query(query + " ORDER BY timestamp", conn, params=params)
    except (sqlite3.Error, pd.errors.DatabaseError) as exc:
        log.warning("SQLite read failed: %s", exc)
        return pd.DataFrame()
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="ISO8601")
    return df


def _since(**delta) -> datetime:
    return datetime.now(timezone.utc) - timedelta(**delta)


def _local_wallclock_as_utc(ts: pd.Series) -> pd.Series:
    """Mirror BigQuery's TIMESTAMP(DATETIME(ts, 'Europe/Zurich')): local wall time labelled UTC."""
    return ts.dt.tz_convert(LOCAL_TZ).dt.tz_localize(None).dt.tz_localize("UTC")


# ── Views (same signatures and columns as data.py) ────────────────────────────

def get_last_known_context() -> dict:
    df = _load(_since(days=30))
    if df.empty:
        return {}
    row = df.iloc[-1]
    return {"timestamp": row["timestamp"].timestamp(),
            "location": row.get("location") or "Unknown Location"}


def get_history(hours: int = 24) -> pd.DataFrame:
    df = _load(_since(hours=int(hours)))
    if df.empty:
        return pd.DataFrame()
    df["timestamp"] = _local_wallclock_as_utc(df["timestamp"]).dt.floor("min")
    out = df.groupby("timestamp").agg(
        temperature=("temperature", "mean"), humidity=("humidity", "mean"),
        eco2=("eco2", "mean"), tvoc=("tvoc", "mean"), pressure=("pressure", "mean"),
        motion_detected=("motion_detected", "max"),
    ).reset_index()
    return out.sort_values("timestamp").reset_index(drop=True)


def get_daily_aggregates(days: int = 7) -> pd.DataFrame:
    df = _load(_since(days=int(days)))
    if df.empty:
        return pd.DataFrame()
    df["date"] = df["timestamp"].dt.tz_convert(LOCAL_TZ).dt.date
    g = df.groupby("date")
    out = pd.DataFrame({
        "temp_min": g["temperature"].min().round(1), "temp_avg": g["temperature"].mean().round(1),
        "temp_max": g["temperature"].max().round(1),
        "hum_min":  g["humidity"].min().round(1),    "hum_avg":  g["humidity"].mean().round(1),
        "hum_max":  g["humidity"].max().round(1),
        "eco2_avg": g["eco2"].mean().round(0),       "eco2_max": g["eco2"].max().round(0),
    }).reset_index()
    out["date"] = pd.to_datetime(out["date"])
    return out.sort_values("date").reset_index(drop=True)


def get_motion_heatmap(days: int = 7) -> pd.DataFrame:
    df = _load(_since(days=int(days)))
    if df.empty:
        return pd.DataFrame()
    local = df["timestamp"].dt.tz_convert(LOCAL_TZ)
    df["day"], df["hour"] = local.dt.strftime("%a"), local.dt.hour
    out = df.groupby(["day", "hour"])["motion_detected"].sum().reset_index(name="motion_count")
    return out.sort_values("hour").reset_index(drop=True)


# Readings beyond a threshold fetched per query, newest first. Enough for a
# 30-day window at the device's normal upload rate; grouped into episodes.
ANOMALY_ROW_LIMIT = 20000


def _anomaly_log(df: pd.DataFrame, limit: int) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    df = df[is_anomalous(df)].sort_values("timestamp", ascending=False).head(limit)
    if df.empty:
        return pd.DataFrame()
    df = df[["timestamp", "eco2", "tvoc", "humidity"]].copy()
    df["timestamp"] = df["timestamp"].dt.tz_convert(LOCAL_TZ)
    return anomaly_episodes(df)


def get_anomalies(days: int = 1) -> pd.DataFrame:
    return _anomaly_log(_load(_since(days=int(days))), limit=ANOMALY_ROW_LIMIT)


def get_anomalies_by_dates(start_dt, end_dt) -> pd.DataFrame:
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=LOCAL_TZ)
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=LOCAL_TZ)
    return _anomaly_log(_load(start_dt, end_dt), limit=ANOMALY_ROW_LIMIT)


def get_co2_peak_stats(hours: int = 24) -> dict:
    df = _load(_since(hours=int(hours)))
    if df.empty:
        return dict(_EMPTY_PEAK)
    df = df.dropna(subset=["eco2"])
    if df.empty:
        return dict(_EMPTY_PEAK)
    peak_row = df.loc[df["eco2"].idxmax()]
    return {
        "peak":            int(df["eco2"].max()),
        "avg":             int(df["eco2"].mean()),
        "peak_time":       peak_row["timestamp"].floor("min"),
        "mins_above_800":  int((df["eco2"] > THRESH["eco2_warning"]).sum()),
        "mins_above_1500": int((df["eco2"] > THRESH["eco2_danger"]).sum()),
    }
