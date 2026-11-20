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


# Readings above a threshold that are less than this far apart belong to one
# episode. The device uploads every 30 s (every 5 s during an alert), so short
# dips below the threshold do not split an episode in two.
EPISODE_GAP = pd.Timedelta(minutes=5)

_UNITS = {"eco2": "ppm", "tvoc": "ppb", "humidity": "%"}
_EPISODE_COLUMNS = ["start", "end", "type", "level", "peak", "value", "readings"]


def anomaly_episodes(df: pd.DataFrame, gap: pd.Timedelta = EPISODE_GAP) -> pd.DataFrame:
    """
    Group raw readings (timestamp, eco2, tvoc, humidity) into anomaly episodes:
    one row per continuous period in which a metric stayed beyond its warning
    threshold. Columns: start, end, type, level (worst level reached), peak
    (highest value, lowest for low humidity), value (formatted peak) and
    readings (number of readings beyond the threshold). Newest first.
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=_EPISODE_COLUMNS)
    df = df.sort_values("timestamp")
    episodes = []
    for col, label, _unit, op, danger_key, warn_key in _RULES:
        values = pd.to_numeric(df[col], errors="coerce")
        beyond = values > THRESH[warn_key] if op == "gt" else values < THRESH[warn_key]
        hits = pd.DataFrame({"timestamp": df["timestamp"][beyond], "value": values[beyond]})
        if hits.empty:
            continue
        episode_id = (hits["timestamp"].diff() > gap).cumsum()
        for _, ep in hits.groupby(episode_id):
            peak = ep["value"].max() if op == "gt" else ep["value"].min()
            danger = peak > THRESH[danger_key] if op == "gt" else peak < THRESH[danger_key]
            unit = _UNITS[col]
            episodes.append({
                "start": ep["timestamp"].iloc[0],
                "end": ep["timestamp"].iloc[-1],
                "type": label,
                "level": "danger" if danger else "warning",
                "peak": float(peak),
                "value": f"{int(round(peak)):,}{'' if unit == '%' else ' '}{unit}",
                "readings": len(ep),
            })
    if not episodes:
        return pd.DataFrame(columns=_EPISODE_COLUMNS)
    out = pd.DataFrame(episodes, columns=_EPISODE_COLUMNS)
    return out.sort_values(["end", "start"], ascending=False).reset_index(drop=True)
