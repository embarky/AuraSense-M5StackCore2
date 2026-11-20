"""The SQLite views must return the same columns the BigQuery queries return."""

from datetime import datetime, timedelta

import pandas as pd


def test_history_is_per_minute_and_ordered(source):
    h = source.get_history(24)
    assert list(h.columns) == ["timestamp", "temperature", "humidity", "eco2", "tvoc",
                               "pressure", "motion_detected"]
    assert 1380 <= len(h) <= 1441 and h["timestamp"].is_monotonic_increasing
    assert (h["timestamp"].dt.second == 0).all()


def test_history_uses_local_wall_clock_like_bigquery(source):
    latest = source.get_history(1)["timestamp"].iloc[-1]
    now_local = pd.Timestamp.now(tz="Europe/Zurich").tz_localize(None)
    assert abs(latest.tz_localize(None) - now_local) < pd.Timedelta(minutes=3)


def test_daily_aggregates(source):
    d = source.get_daily_aggregates(7)
    assert list(d.columns) == ["date", "temp_min", "temp_avg", "temp_max", "hum_min",
                               "hum_avg", "hum_max", "eco2_avg", "eco2_max"]
    assert 7 <= len(d) <= 8
    assert (d.temp_min <= d.temp_avg).all() and (d.temp_avg <= d.temp_max).all()


def test_motion_heatmap(source):
    m = source.get_motion_heatmap(7)
    assert set(m.columns) == {"day", "hour", "motion_count"}
    assert m.hour.between(0, 23).all()
    by_hour = m.groupby("hour").motion_count.sum()
    assert by_hour[20] > by_hour[3]                         # evenings busier than nights


def test_anomaly_logs(source):
    a = source.get_anomalies(7)
    assert list(a.columns) == ["start", "end", "type", "level", "peak", "value", "readings"]
    assert str(a["start"].dt.tz) == "Europe/Zurich"
    assert set(a["level"]) <= {"warning", "danger"}
    assert (a["end"] >= a["start"]).all()
    # a week of simulated data has many readings above a threshold but far
    # fewer episodes: the log no longer lists every reading
    assert 0 < len(a) < a["readings"].sum() / 5
    assert list(a["end"]) == sorted(a["end"], reverse=True)

    end = datetime.now()
    window = source.get_anomalies_by_dates(end - timedelta(hours=6), end)
    if not window.empty:
        assert window["start"].min() >= pd.Timestamp(end - timedelta(hours=6), tz="Europe/Zurich")


def test_co2_peak_stats(source):
    s = source.get_co2_peak_stats(24)
    assert s["peak"] >= s["avg"] > 400 and s["mins_above_800"] >= s["mins_above_1500"]


def test_last_known_context(source):
    ctx = source.get_last_known_context()
    assert ctx["location"] == "Lausanne, CH"
    assert abs(ctx["timestamp"] - datetime.now().timestamp()) < 180


def test_missing_database_returns_empty_results(source, monkeypatch):
    monkeypatch.setattr(source, "SQLITE_PATH", "/nonexistent/aurasense.db")
    assert source.get_history(24).empty and source.get_anomalies(1).empty
    assert source.get_last_known_context() == {}
    assert source.get_co2_peak_stats()["peak"] == 0


def test_data_module_switches_to_sqlite():
    import data
    assert data.DATA_SOURCE == "sqlite" and data.get_history.__module__ == "sqlite_source"
