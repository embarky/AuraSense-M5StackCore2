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


# ── Episodes ──────────────────────────────────────────────────────────────────

from anomalies import anomaly_episodes  # noqa: E402


def _series(start, values, step_s=60, col="eco2"):
    t0 = pd.Timestamp(start, tz="Europe/Zurich")
    rows = []
    for i, v in enumerate(values):
        r = {"timestamp": t0 + pd.Timedelta(seconds=i * step_s), "eco2": 500, "tvoc": 50, "humidity": 45}
        r[col] = v
        rows.append(r)
    return pd.DataFrame(rows)


def test_consecutive_readings_form_one_episode_with_worst_level_and_peak():
    df = _series("2026-11-19 18:00", [700, 900, 1200, 1600, 1100, 700])
    ep = anomaly_episodes(df)
    assert len(ep) == 1
    row = ep.iloc[0]
    assert (row["type"], row["level"], row["peak"], row["value"], row["readings"]) == \
        ("CO2", "danger", 1600, "1,600 ppm", 4)
    assert row["start"] == pd.Timestamp("2026-11-19 18:01", tz="Europe/Zurich")
    assert row["end"] == pd.Timestamp("2026-11-19 18:04", tz="Europe/Zurich")


def test_a_long_gap_splits_episodes_and_a_short_dip_does_not():
    short_dip = _series("2026-11-19 08:00", [900, 900, 700, 700, 900])        # 2 min below
    assert len(anomaly_episodes(short_dip)) == 1
    long_gap = _series("2026-11-19 08:00", [900] + [700] * 10 + [900])         # 10 min below
    eps = anomaly_episodes(long_gap)
    assert len(eps) == 2 and eps["start"].is_monotonic_decreasing              # newest first


def test_low_humidity_peak_is_the_lowest_value():
    ep = anomaly_episodes(_series("2026-11-19 03:00", [45, 28, 18, 25, 45], col="humidity")).iloc[0]
    assert (ep["type"], ep["level"], ep["value"]) == ("Humidity low", "danger", "18%")


def test_metrics_are_grouped_separately():
    df = _series("2026-11-19 12:00", [900, 900])
    df["tvoc"] = [300, 300]
    assert sorted(anomaly_episodes(df)["type"]) == ["CO2", "TVOC"]


def test_no_anomalies_gives_an_empty_frame_with_columns():
    out = anomaly_episodes(_series("2026-11-19 12:00", [500, 600]))
    assert out.empty and "start" in out.columns
    assert anomaly_episodes(pd.DataFrame()).empty
