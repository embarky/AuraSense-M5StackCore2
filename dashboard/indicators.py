"""
dashboard/indicators.py — Status captions derived from recent history.
"AuraSense: See the air you breathe."
"""

from __future__ import annotations

import pandas as pd

# Change over 3 hours, in hPa. Heuristic thresholds for an indoor display:
# below STEADY the weather is settled; above FAST a change is likely coming.
PRESSURE_STEADY_HPA = 1.0
PRESSURE_FAST_HPA   = 3.5
TREND_WINDOW        = pd.Timedelta(hours=3)


def pressure_trend(history: pd.DataFrame) -> str:
    """
    Caption for the air-pressure card based on the 3-hour pressure tendency.

    Absolute pressure depends on altitude (≈ 960 hPa in Lausanne, ≈ 1013 hPa
    at sea level), so a fixed "normal" range mislabels readings away from sea
    level. The change over time is altitude-independent and is what forecasts
    use: a steady reading means settled weather, a fast fall often means rain.
    """
    if history is None or history.empty or "pressure" not in history or "timestamp" not in history:
        return "⚪ Trend available after 3 h"
    df = history[["timestamp", "pressure"]].dropna().sort_values("timestamp")
    if df.empty:
        return "⚪ Trend available after 3 h"
    latest_ts, latest = df["timestamp"].iloc[-1], df["pressure"].iloc[-1]
    past = df[df["timestamp"] <= latest_ts - TREND_WINDOW]
    if past.empty:
        return "⚪ Trend available after 3 h"
    change = latest - past["pressure"].iloc[-1]
    if abs(change) < PRESSURE_STEADY_HPA:
        return "🟢 Stable"
    direction = "Rising" if change > 0 else "Falling"
    if abs(change) < PRESSURE_FAST_HPA:
        return f"🟡 {direction} ({change:+.1f} hPa / 3 h)"
    return f"🟠 {direction} fast ({change:+.1f} hPa / 3 h)"
