import pandas as pd
from indicators import pressure_trend


def _history(values, minutes_apart=10):
    ts = pd.date_range("2026-11-19 08:00", periods=len(values), freq=f"{minutes_apart}min", tz="UTC")
    return pd.DataFrame({"timestamp": ts, "pressure": values})


def test_stable_at_any_altitude():
    # Lausanne (~960 hPa) and sea level (~1013 hPa) are both "stable" if unchanged
    for base in (958.0, 1013.0):
        assert pressure_trend(_history([base + 0.1 * (i % 3) for i in range(24)])) == "🟢 Stable"


def test_rising_falling_and_fast_change():
    assert pressure_trend(_history([960 + 0.1 * i for i in range(24)])).startswith("🟡 Rising")
    assert pressure_trend(_history([960 - 0.1 * i for i in range(24)])).startswith("🟡 Falling")
    assert pressure_trend(_history([960 - 0.3 * i for i in range(24)])).startswith("🟠 Falling fast")


def test_change_is_measured_over_three_hours():
    # 4 h of data, flat for the last 3 h after an earlier drop → stable
    values = [970.0] * 6 + [960.0] * 19
    assert pressure_trend(_history(values)) == "🟢 Stable"


def test_not_enough_history():
    assert pressure_trend(_history([960, 961, 962])) == "⚪ Trend available after 3 h"
    assert pressure_trend(pd.DataFrame()) == "⚪ Trend available after 3 h"
    assert pressure_trend(_history([None] * 30)) == "⚪ Trend available after 3 h"
