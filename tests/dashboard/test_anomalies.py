import pandas as pd
from anomalies import THRESH, classify_anomalies, is_anomalous


def _df(rows):
    return pd.DataFrame(rows, columns=["timestamp", "eco2", "tvoc", "humidity"])


def test_levels_and_labels():
    t = pd.Timestamp("2026-11-19 20:00", tz="Europe/Zurich")
    out = classify_anomalies(_df([
        (t, 1600, 50, 45),     # CO2 danger
        (t, 900, 300, 45),     # CO2 warning + TVOC warning
        (t, 500, 700, 15),     # TVOC danger + humidity low danger
        (t, 500, 50, 70),      # humidity high warning
        (t, 500, 50, 45),      # normal → nothing
    ]))
    got = sorted(zip(out["type"], out["level"], out["value"]))
    assert got == sorted([
        ("CO2 danger", "danger", "1600 ppm"), ("CO2 warning", "warning", "900 ppm"),
        ("TVOC warning", "warning", "300 ppb"), ("TVOC danger", "danger", "700 ppb"),
        ("Humidity low", "danger", "15%"), ("Humidity high", "warning", "70%"),
    ])


def test_ordering_newest_first_danger_before_warning():
    t1, t2 = pd.Timestamp("2026-11-19 08:00", tz="UTC"), pd.Timestamp("2026-11-19 09:00", tz="UTC")
    out = classify_anomalies(_df([(t1, 1600, 300, 45), (t2, 900, 700, 45)]))
    assert list(out["timestamp"]) == [t2, t2, t1, t1]
    assert list(out["level"]) == ["danger", "warning", "danger", "warning"]


def test_boundaries_are_exclusive():
    t = pd.Timestamp("2026-11-19", tz="UTC")
    exact = _df([(t, THRESH["eco2_warning"], THRESH["tvoc_warning"], THRESH["hum_low_warn"])])
    assert classify_anomalies(exact).empty and not is_anomalous(exact).any()


def test_missing_values_are_skipped():
    t = pd.Timestamp("2026-11-19", tz="UTC")
    assert classify_anomalies(_df([(t, None, None, None)])).empty
