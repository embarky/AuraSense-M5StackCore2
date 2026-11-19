"""
dashboard/data.py — Data fetching layer for AuraSense.
"AuraSense: See the air you breathe."

Live values come from the backend API. Historical views come from one of two
sources, chosen with DATA_SOURCE:

* "bigquery" — the cloud deployment (queries below)
* "sqlite"   — the local demo (sqlite_source.py, same columns)

Defaults to BigQuery when GCP_PROJECT is set, otherwise SQLite.
"""
from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from google.cloud import bigquery

from anomalies import THRESH, classify_anomalies

# ── Config ────────────────────────────────────────────────────────────────────

FLASK_URL   = os.getenv("FLASK_URL", "http://localhost:5001")
API_KEY     = os.getenv("AURASENSE_API_KEY", "")
GCP_PROJECT = os.getenv("GCP_PROJECT", "")
DATA_SOURCE = os.getenv("DATA_SOURCE", "bigquery" if GCP_PROJECT else "sqlite")
BQ_DATASET  = os.getenv("BQ_DATASET", "iot_data")
BQ_TABLE    = os.getenv("BQ_TABLE",   "sensor_logs")
TABLE_ID    = f"{GCP_PROJECT}.{BQ_DATASET}.{BQ_TABLE}"


# ── BigQuery client (cached) ──────────────────────────────────────────────────

_bq_client = None

def _bq() -> bigquery.Client:
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client(project=GCP_PROJECT)
    return _bq_client


def _run(query: str, **params) -> pd.DataFrame:
    """
    Run a parameterised BigQuery query and return a DataFrame.

    Values are sent as query parameters (never formatted into the SQL text);
    integers become INT64 and datetimes become TIMESTAMP parameters.
    """
    query_params = []
    for name, value in params.items():
        if isinstance(value, datetime):
            query_params.append(bigquery.ScalarQueryParameter(name, "TIMESTAMP", value))
        else:
            query_params.append(bigquery.ScalarQueryParameter(name, "INT64", int(value)))
    job_config = bigquery.QueryJobConfig(query_parameters=query_params)
    return _bq().query(query, job_config=job_config).to_dataframe()


# ── Real-time & Context Status ────────────────────────────────────────────────

def get_current_status() -> dict:
    """Fetch latest sensor snapshot from Flask backend safely."""
    try:
        r = requests.get(
            f"{FLASK_URL}/api/current_status",
            headers={"X-API-Key": API_KEY},
            timeout=3,
        )
        if r.status_code == 200:
            return r.json()
    except requests.exceptions.RequestException as e:
        print(f"[AuraSense | Data] Live backend offline: {e}")
        pass
    
    return {} 


def get_last_known_context() -> dict:
    """
    FALLBACK: If the real-time API is offline, query BigQuery for the 
    absolute latest row to determine the last known timestamp and location.
    """
    query = f"""
        SELECT 
            timestamp, 
            location
        FROM `{TABLE_ID}`
        ORDER BY timestamp DESC
        LIMIT 1
    """
    try:
        df = _run(query)
        if not df.empty:
            row = df.iloc[0]
            return {
                "timestamp": pd.to_datetime(row["timestamp"]).timestamp(),
                "location": row.get("location", "Unknown Location")
            }
    except Exception as e:
        print(f"[AuraSense | Data] get_last_known_context error: {e}")
    
    return {}


# ── Historical data ───────────────────────────────────────────────────────────

def get_history(hours: int = 24) -> pd.DataFrame:
    """Return raw sensor readings for the last N hours."""
    query = f"""
        SELECT
            TIMESTAMP_TRUNC(
                TIMESTAMP(DATETIME(timestamp, 'Europe/Zurich')),
                MINUTE
            ) AS timestamp,
            AVG(temperature)     AS temperature,
            AVG(humidity)        AS humidity,
            AVG(eco2)            AS eco2,
            AVG(tvoc)            AS tvoc,
            AVG(pressure)        AS pressure,
            MAX(CAST(motion_detected AS INT64)) AS motion_detected
        FROM `{TABLE_ID}`
        WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @hours HOUR)
        GROUP BY 1
        ORDER BY 1
    """
    try:
        df = _run(query, hours=hours)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df
    except Exception as e:
        print(f"[AuraSense | Data] get_history error: {e}")
        return pd.DataFrame()


def get_daily_aggregates(days: int = 7) -> pd.DataFrame:
    """Return daily min/avg/max for temperature, humidity, CO2."""
    query = f"""
        SELECT
            DATE(DATETIME(timestamp, 'Europe/Zurich')) AS date,
            ROUND(MIN(temperature), 1)  AS temp_min,
            ROUND(AVG(temperature), 1)  AS temp_avg,
            ROUND(MAX(temperature), 1)  AS temp_max,
            ROUND(MIN(humidity), 1)     AS hum_min,
            ROUND(AVG(humidity), 1)     AS hum_avg,
            ROUND(MAX(humidity), 1)     AS hum_max,
            ROUND(AVG(eco2), 0)         AS eco2_avg,
            ROUND(MAX(eco2), 0)         AS eco2_max
        FROM `{TABLE_ID}`
        WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)
        GROUP BY 1
        ORDER BY 1
    """
    try:
        df = _run(query, days=days)
        if 'date' in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception as e:
        print(f"[AuraSense | Data] get_daily_aggregates error: {e}")
        return pd.DataFrame()


def get_motion_heatmap(days: int = 7) -> pd.DataFrame:
    """Return hourly motion detection counts for heatmap."""
    query = f"""
        SELECT
            FORMAT_DATE('%a', DATE(DATETIME(timestamp, 'Europe/Zurich'))) AS day,
            EXTRACT(HOUR FROM DATETIME(timestamp, 'Europe/Zurich')) AS hour,
            SUM(CASE WHEN CAST(motion_detected AS STRING) IN ('true','True','1') THEN 1 ELSE 0 END) AS motion_count
        FROM `{TABLE_ID}`
        WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)
        GROUP BY 1, 2
        ORDER BY 2
    """
    try:
        return _run(query, days=days)
    except Exception as e:
        print(f"[AuraSense | Data] get_motion_heatmap error: {e}")
        return pd.DataFrame()


# ── Anomaly detection ─────────────────────────────────────────────────────────

def get_anomalies(days: int = 1) -> pd.DataFrame:
    """Returns dataframe with: timestamp, type, level, value"""
    query = f"""
        SELECT timestamp, eco2, tvoc, humidity
        FROM `{TABLE_ID}`
        WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)
          AND timezone = 'Europe/Zurich'
          AND (
            eco2     > {THRESH["eco2_warning"]}
            OR tvoc  > {THRESH["tvoc_warning"]}
            OR humidity < {THRESH["hum_low_warn"]}
            OR humidity > {THRESH["hum_high_warn"]}
          )
        ORDER BY timestamp DESC
        LIMIT 200
    """
    try:
        df = _run(query, days=days)
        if df.empty:
            return df
        df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_convert("Europe/Zurich")

        return classify_anomalies(df)

    except Exception as e:
        print(f"[AuraSense | Data] get_anomalies error: {e}")
        return pd.DataFrame()
    

def get_anomalies_by_dates(start_dt, end_dt) -> pd.DataFrame:
    """Fetch anomalies between two specific exact datetimes (down to the second)."""
    # The UI picks wall-clock times in Zurich; make them timezone-aware so that
    # BigQuery does not interpret them as UTC (which shifted the window by 1-2 h).
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=ZoneInfo("Europe/Zurich"))
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=ZoneInfo("Europe/Zurich"))
    query = f"""
        SELECT timestamp, eco2, tvoc, humidity
        FROM `{TABLE_ID}`
        WHERE timestamp >= @start_ts
          AND timestamp <= @end_ts
          AND timezone = 'Europe/Zurich'
          AND (
            eco2     > {THRESH["eco2_warning"]}
            OR tvoc  > {THRESH["tvoc_warning"]}
            OR humidity < {THRESH["hum_low_warn"]}
            OR humidity > {THRESH["hum_high_warn"]}
          )
        ORDER BY timestamp DESC
        LIMIT 500
    """
    try:
        df = _run(query, start_ts=start_dt, end_ts=end_dt)
        if df.empty: return df
        df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_convert("Europe/Zurich")

        return classify_anomalies(df)
    except Exception as e:
        print(f"[AuraSense | Data] get_anomalies_by_dates error: {e}")
        return pd.DataFrame()


def get_co2_peak_stats(hours: int = 24) -> dict:
    """Return CO2 peak value, time, daily avg, time above thresholds."""
    query = f"""
        SELECT
            MAX(eco2)            AS peak,
            AVG(eco2)            AS avg,
            TIMESTAMP_TRUNC(
                (SELECT timestamp FROM `{TABLE_ID}`
                 WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @hours HOUR)
                 ORDER BY eco2 DESC LIMIT 1),
                MINUTE
            )                    AS peak_time,
            COUNTIF(eco2 > {THRESH["eco2_warning"]}) AS mins_above_800,
            COUNTIF(eco2 > {THRESH["eco2_danger"]})  AS mins_above_1500
        FROM `{TABLE_ID}`
        WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @hours HOUR)
    """
    try:
        df = _run(query, hours=hours)
        if df.empty:
            return {"peak": 0, "avg": 0, "peak_time": None, "mins_above_800": 0, "mins_above_1500": 0}
            
        row = df.iloc[0]
        return {
            "peak":            int(row["peak"]) if pd.notna(row["peak"]) else 0,
            "avg":             int(row["avg"])  if pd.notna(row["avg"])  else 0,
            "peak_time":       row["peak_time"] if pd.notna(row["peak_time"]) else None,
            "mins_above_800":  int(row["mins_above_800"]) if pd.notna(row["mins_above_800"]) else 0,
            "mins_above_1500": int(row["mins_above_1500"]) if pd.notna(row["mins_above_1500"]) else 0,
        }
    except Exception as e:
        print(f"[AuraSense | Data] get_co2_peak_stats error: {e}")
        return {"peak": 0, "avg": 0, "peak_time": None, "mins_above_800": 0, "mins_above_1500": 0}


# ── Local demo: replace the BigQuery views with the SQLite implementations ────

if DATA_SOURCE == "sqlite":
    import sqlite_source as _local  # noqa: E402

    get_last_known_context = _local.get_last_known_context
    get_history            = _local.get_history
    get_daily_aggregates   = _local.get_daily_aggregates
    get_motion_heatmap     = _local.get_motion_heatmap
    get_anomalies          = _local.get_anomalies
    get_anomalies_by_dates = _local.get_anomalies_by_dates
    get_co2_peak_stats     = _local.get_co2_peak_stats
