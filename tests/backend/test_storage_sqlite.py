from datetime import datetime, timedelta, timezone

import pytest
from storage import normalise_reading
from storage.sqlite import SQLiteStorage


@pytest.fixture
def store(tmp_path):
    return SQLiteStorage(str(tmp_path / "s.db"))


def _row(hours_ago, **values):
    ts = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return normalise_reading({"temperature": 20.0, "humidity": 40, "eco2": 600, **values}, ts)


def test_insert_and_history_window(store):
    ok, _ = store.insert_readings([_row(1), _row(5), _row(30)])
    assert ok
    hist = store.get_history(24)
    assert len(hist) == 2
    assert hist[0]["timestamp"] > hist[1]["timestamp"]           # newest first


def test_history_window_is_clamped(store):
    store.insert_readings([_row(24 * 6), _row(24 * 10)])
    assert len(store.get_history(10_000)) == 1                    # max 7 days


def test_daily_aggregates(store):
    store.insert_readings([_row(0.1, temperature=19.0, eco2=500), _row(0.2, temperature=23.0, eco2=900)])
    day = store.get_daily_aggregates(1)[0]
    assert (day["min_temp"], day["max_temp"], day["avg_temp"], day["avg_eco2"]) == (19.0, 23.0, 21.0, 700)


def test_recent_summary(store):
    assert store.get_recent_summary() == "No recent AuraSense data available."
    store.insert_readings([_row(0.1, temperature=22.0), _row(2, temperature=18.0)])
    summary = store.get_recent_summary()
    assert "22.0 °C" in summary and "min 18.0" in summary


def test_normalise_reading_accepts_device_and_storage_field_names():
    assert normalise_reading({"motion": True})["motion_detected"] == 1
    assert normalise_reading({"motion_detected": 0})["motion_detected"] == 0
    assert normalise_reading({})["timestamp"].tzinfo is not None
