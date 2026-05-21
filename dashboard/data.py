"""
dashboard/data.py — Data fetching layer.
"""
from __future__ import annotations

import os
import requests
import pandas as pd
from google.cloud import bigquery

# ── Config ────────────────────────────────────────────────────────────────────

FLASK_URL   = os.getenv("FLASK_URL", "http://localhost:5001")
GCP_PROJECT = os.getenv("GCP_PROJECT", "caa-project-493719")
BQ_DATASET  = os.getenv("BQ_DATASET", "iot_data")
BQ_TABLE    = os.getenv("BQ_TABLE",   "sensor_logs")
TABLE_ID    = f"{GCP_PROJECT}.{BQ_DATASET}.{BQ_TABLE}"

# Anomaly thresholds
THRESH = {
    "eco2_danger":    1500,
    "eco2_warning":   800,
    "tvoc_danger":    660,
    "tvoc_warning":   220,
    "hum_low_danger": 20,
    "hum_low_warn":   30,
    "hum_high_danger":75,
    "hum_high_warn":  65,
}

# ── BigQuery client (cached) ──────────────────────────────────────────────────

_bq_client = None

def _bq() -> bigquery.Client:
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client(project=GCP_PROJECT)
    return _bq_client


# ── Real-time & Context Status ────────────────────────────────────────────────

def get_current_status() -> dict:
    """Fetch latest sensor snapshot from Flask backend safely."""
    try:
        r = requests.get(f"{FLASK_URL}/api/current_status", timeout=3)
        if r.status_code == 200:
            return r.json()
    except requests.exceptions.RequestException as e:
        print(f"[data] Live backend offline: {e}")
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
        df = _bq().query(query).to_dataframe()
        if not df.empty:
            row = df.iloc[0]
            return {
                "timestamp": pd.to_datetime(row["timestamp"]).timestamp(),
                "location": row.get("location", "Unknown Location")
            }
    except Exception as e:
        print(f"[data] get_last_known_context error: {e}")
    
    return {}


# ── Historical data ───────────────────────────────────────────────────────────

def get_history(hours: int = 24) -> pd.DataFrame:
    """Return raw sensor readings for the last N hours."""
    query = f"""
        SELECT
            TIMESTAMP_TRUNC(timestamp, MINUTE) AS timestamp,
            AVG(temperature)     AS temperature,
            AVG(humidity)        AS humidity,
            AVG(eco2)            AS eco2,
            AVG(tvoc)            AS tvoc,
            AVG(pressure)        AS pressure,
            MAX(CAST(motion_detected AS INT64)) AS motion_detected
        FROM `{TABLE_ID}`
        WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {hours} HOUR)
        GROUP BY 1
        ORDER BY 1
    """
    try:
        df = _bq().query(query).to_dataframe()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df
    except Exception as e:
        print(f"[data] get_history error: {e}")
        return pd.DataFrame()


def get_daily_aggregates(days: int = 7) -> pd.DataFrame:
    """Return daily min/avg/max for temperature, humidity, CO2."""
    query = f"""
        SELECT
            DATE(timestamp) AS date,
            ROUND(MIN(temperature), 1)  AS temp_min,
            ROUND(AVG(temperature), 1)  AS temp_avg,
            ROUND(MAX(temperature), 1)  AS temp_max,
            ROUND(MIN(humidity), 1)     AS hum_min,
            ROUND(AVG(humidity), 1)     AS hum_avg,
            ROUND(MAX(humidity), 1)     AS hum_max,
            ROUND(AVG(eco2), 0)         AS eco2_avg,
            ROUND(MAX(eco2), 0)         AS eco2_max
        FROM `{TABLE_ID}`
        WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
        GROUP BY 1
        ORDER BY 1
    """
    try:
        df = _bq().query(query).to_dataframe()
        if 'date' in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception as e:
        print(f"[data] get_daily_aggregates error: {e}")
        return pd.DataFrame()


def get_motion_heatmap(days: int = 7) -> pd.DataFrame:
    """Return hourly motion detection counts for heatmap."""
    query = f"""
        SELECT
            FORMAT_DATE('%a', DATE(timestamp)) AS day,
            EXTRACT(HOUR FROM timestamp) AS hour,
            SUM(CASE WHEN CAST(motion_detected AS STRING) IN ('true','True','1') THEN 1 ELSE 0 END) AS motion_count
        FROM `{TABLE_ID}`
        WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
        GROUP BY 1, 2
        ORDER BY 2
    """
    try:
        return _bq().query(query).to_dataframe()
    except Exception as e:
        print(f"[data] get_motion_heatmap error: {e}")
        return pd.DataFrame()


# ── Anomaly detection ─────────────────────────────────────────────────────────

def get_anomalies(days: int = 1) -> pd.DataFrame:
    """Returns dataframe with: timestamp, type, level, value"""
    query = f"""
        SELECT timestamp, eco2, tvoc, humidity
        FROM `{TABLE_ID}`
        WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
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
        df = _bq().query(query).to_dataframe()
        if df.empty:
            return df
        df["timestamp"] = pd.to_datetime(df["timestamp"])

        rows = []
        for _, r in df.iterrows():
            if r["eco2"] > THRESH["eco2_danger"]:
                rows.append({"timestamp": r["timestamp"], "type": "CO2 danger", "level": "danger", "value": f"{int(r['eco2'])} ppm"})
            elif r["eco2"] > THRESH["eco2_warning"]:
                rows.append({"timestamp": r["timestamp"], "type": "CO2 warning", "level": "warning", "value": f"{int(r['eco2'])} ppm"})
            
            if r["tvoc"] > THRESH["tvoc_danger"]:
                rows.append({"timestamp": r["timestamp"], "type": "TVOC danger", "level": "danger", "value": f"{int(r['tvoc'])} ppb"})
            elif r["tvoc"] > THRESH["tvoc_warning"]:
                rows.append({"timestamp": r["timestamp"], "type": "TVOC warning", "level": "warning", "value": f"{int(r['tvoc'])} ppb"})
                
            if r["humidity"] < THRESH["hum_low_danger"]:
                rows.append({"timestamp": r["timestamp"], "type": "Humidity low", "level": "danger", "value": f"{int(r['humidity'])}%"})
            elif r["humidity"] < THRESH["hum_low_warn"]:
                rows.append({"timestamp": r["timestamp"], "type": "Humidity low", "level": "warning", "value": f"{int(r['humidity'])}%"})
                
            if r["humidity"] > THRESH["hum_high_danger"]:
                rows.append({"timestamp": r["timestamp"], "type": "Humidity high", "level": "danger", "value": f"{int(r['humidity'])}%"})
            elif r["humidity"] > THRESH["hum_high_warn"]:
                rows.append({"timestamp": r["timestamp"], "type": "Humidity high", "level": "warning", "value": f"{int(r['humidity'])}%"})

        result = pd.DataFrame(rows)
        if not result.empty:
            result = result.sort_values("timestamp", ascending=False).reset_index(drop=True)
        return result

    except Exception as e:
        print(f"[data] get_anomalies error: {e}")
        return pd.DataFrame()
    

def get_anomalies_by_dates(start_dt, end_dt) -> pd.DataFrame:
    """Fetch anomalies between two specific exact datetimes (down to the second)."""
    # 直接格式化传入的 datetime 对象，精确到秒
    start_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
    end_str   = end_dt.strftime("%Y-%m-%d %H:%M:%S")
    
    query = f"""
        SELECT timestamp, eco2, tvoc, humidity
        FROM `{TABLE_ID}`
        WHERE timestamp >= TIMESTAMP('{start_str}')
          AND timestamp <= TIMESTAMP('{end_str}')
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
        df = _bq().query(query).to_dataframe()
        if df.empty: return df
        df["timestamp"] = pd.to_datetime(df["timestamp"])

        rows = []
        for _, r in df.iterrows():
            if r["eco2"] > THRESH["eco2_danger"]:
                rows.append({"timestamp": r["timestamp"], "type": "CO2 danger", "level": "danger", "value": f"{int(r['eco2'])} ppm"})
            elif r["eco2"] > THRESH["eco2_warning"]:
                rows.append({"timestamp": r["timestamp"], "type": "CO2 warning", "level": "warning", "value": f"{int(r['eco2'])} ppm"})
            if r["tvoc"] > THRESH["tvoc_danger"]:
                rows.append({"timestamp": r["timestamp"], "type": "TVOC danger", "level": "danger", "value": f"{int(r['tvoc'])} ppb"})
            elif r["tvoc"] > THRESH["tvoc_warning"]:
                rows.append({"timestamp": r["timestamp"], "type": "TVOC warning", "level": "warning", "value": f"{int(r['tvoc'])} ppb"})
            if r["humidity"] < THRESH["hum_low_danger"]:
                rows.append({"timestamp": r["timestamp"], "type": "Humidity low", "level": "danger", "value": f"{int(r['humidity'])}%"})
            elif r["humidity"] < THRESH["hum_low_warn"]:
                rows.append({"timestamp": r["timestamp"], "type": "Humidity low", "level": "warning", "value": f"{int(r['humidity'])}%"})
            if r["humidity"] > THRESH["hum_high_danger"]:
                rows.append({"timestamp": r["timestamp"], "type": "Humidity high", "level": "danger", "value": f"{int(r['humidity'])}%"})
            elif r["humidity"] > THRESH["hum_high_warn"]:
                rows.append({"timestamp": r["timestamp"], "type": "Humidity high", "level": "warning", "value": f"{int(r['humidity'])}%"})

        result = pd.DataFrame(rows)
        if not result.empty:
            result = result.sort_values("timestamp", ascending=False).reset_index(drop=True)
        return result
    except Exception as e:
        print(f"[data] get_anomalies_by_dates error: {e}")
        return pd.DataFrame()


def get_co2_peak_stats(hours: int = 24) -> dict:
    """Return CO2 peak value, time, daily avg, time above thresholds."""
    query = f"""
        SELECT
            MAX(eco2)            AS peak,
            AVG(eco2)            AS avg,
            TIMESTAMP_TRUNC(
                (SELECT timestamp FROM `{TABLE_ID}`
                 WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {hours} HOUR)
                 ORDER BY eco2 DESC LIMIT 1),
                MINUTE
            )                    AS peak_time,
            COUNTIF(eco2 > {THRESH["eco2_warning"]}) AS mins_above_800,
            COUNTIF(eco2 > {THRESH["eco2_danger"]})  AS mins_above_1500
        FROM `{TABLE_ID}`
        WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {hours} HOUR)
    """
    try:
        df = _bq().query(query).to_dataframe()
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
        print(f"[data] get_co2_peak_stats error: {e}")
        return {"peak": 0, "avg": 0, "peak_time": None, "mins_above_800": 0, "mins_above_1500": 0}
    