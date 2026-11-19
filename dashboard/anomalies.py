"""
dashboard/anomalies.py — Alert thresholds and anomaly classification.
"AuraSense: See the air you breathe."

Shared by every data source so BigQuery and SQLite produce identical anomaly
logs. Thresholds match the device LED alert levels.
"""

from __future__ import annotations

import pandas as pd

THRESH = {
    "eco2_danger":     1500,
    "eco2_warning":    800,
    "tvoc_danger":     660,
    "tvoc_warning":    220,
    "hum_low_danger":  20,
    "hum_low_warn":    30,
    "hum_high_danger": 75,
    "hum_high_warn":   65,
}

# (column, label, unit, comparison, danger threshold, warning threshold)
_RULES = [
    ("eco2",     "CO2",           " ppm", "gt", "eco2_danger",     "eco2_warning"),
    ("tvoc",     "TVOC",          " ppb", "gt", "tvoc_danger",     "tvoc_warning"),
    ("humidity", "Humidity low",  "%",    "lt", "hum_low_danger",  "hum_low_warn"),
    ("humidity", "Humidity high", "%",    "gt", "hum_high_danger", "hum_high_warn"),
]


def is_anomalous(df: pd.DataFrame) -> pd.Series:
    """Boolean mask of rows that reach at least the warning level."""
    return (
        (df["eco2"] > THRESH["eco2_warning"])
        | (df["tvoc"] > THRESH["tvoc_warning"])
        | (df["humidity"] < THRESH["hum_low_warn"])
        | (df["humidity"] > THRESH["hum_high_warn"])
    )


def classify_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    """
    Turn raw readings (timestamp, eco2, tvoc, humidity) into an anomaly log
    with columns timestamp, type, level, value — newest first, danger before
    warning for the same timestamp.
    """
    rows = []
    for _, r in df.iterrows():
        for col, label, unit, op, danger_key, warn_key in _RULES:
            value = r[col]
            if pd.isna(value):
                continue
            beyond = (lambda t: value > t) if op == "gt" else (lambda t: value < t)
            if beyond(THRESH[danger_key]):
                level = "danger"
            elif beyond(THRESH[warn_key]):
                level = "warning"
            else:
                continue
            kind = label if label.startswith("Humidity") else f"{label} {level}"
            rows.append({"timestamp": r["timestamp"], "type": kind,
                         "level": level, "value": f"{int(value)}{unit}"})

    result = pd.DataFrame(rows)
    if not result.empty:
        result["_level_order"] = result["level"].map({"danger": 0, "warning": 1})
        result = result.sort_values(["timestamp", "_level_order"], ascending=[False, True])
        result = result.drop(columns=["_level_order"]).reset_index(drop=True)
    return result
