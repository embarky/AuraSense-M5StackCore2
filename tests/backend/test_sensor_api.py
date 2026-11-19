import threading
import time
from datetime import datetime, timedelta, timezone

from conftest import AUTH

READING = {"temperature": 21.5, "humidity": 40.2, "pressure": 963.1,
           "eco2": 950, "tvoc": 120, "motion": True}


def _iso(**delta):
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()


def test_ingest_returns_device_sync_payload(client):
    r = client.post("/api/sensor_data", json=READING, headers=AUTH)
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "ok" and body["location"] == "Lausanne, CH"
    assert body["utc_offset"] in (3600, 7200)            # CET / CEST
    assert len(body["utc_time"]) == 8                    # RTC datetime tuple


def test_ingest_updates_live_status_and_storage(client, app):
    client.post("/api/sensor_data", json=READING, headers={**AUTH, "X-Device-Id": "core2-01"})
    status = client.get("/api/current_status", headers=AUTH).get_json()
    assert status["indoor_temp"] == 21.5 and status["eco2"] == 950
    assert abs(status["timestamp"] - time.time()) < 5

    rows = app.storage.get_history(1)
    assert len(rows) == 1
    assert rows[0]["device_id"] == "core2-01" and rows[0]["location"] == "Lausanne, CH"
    assert rows[0]["motion_detected"] == 1


def test_status_before_any_data(client):
    assert client.get("/api/current_status", headers=AUTH).status_code == 202


def test_ai_advice_runs_in_background(client):
    client.post("/api/sensor_data", json={**READING, "eco2": 1700}, headers=AUTH)
    for _ in range(50):
        advice = client.get("/api/current_status", headers=AUTH).get_json()["ai_advice"]
        if "open a window" in advice:
            break
        time.sleep(0.02)
    assert "open a window" in advice


def test_rejects_invalid_payloads(client):
    assert client.post("/api/sensor_data", data="not json", headers=AUTH).status_code == 400
    assert client.post("/api/sensor_data", json=[], headers=AUTH).status_code == 400
    for ts in ("garbage", _iso(days=40), _iso(minutes=-10)):
        r = client.post("/api/sensor_data", json={**READING, "timestamp": ts}, headers=AUTH)
        assert r.status_code == 400, ts


def test_ingest_accepts_measurement_timestamp(client, app):
    ts = _iso(hours=3)
    assert client.post("/api/sensor_data", json={**READING, "timestamp": ts}, headers=AUTH).status_code == 200
    stored = app.storage.get_history(24)[0]["timestamp"]
    assert stored.startswith(ts[:16])


def test_batch_ingest(client, app):
    readings = [{**READING, "timestamp": _iso(minutes=i), "eco2": 500 + i} for i in range(1, 301)]
    r = client.post("/api/sensor_data/batch", json={"readings": readings}, headers=AUTH)
    assert r.status_code == 200 and r.get_json()["stored"] == 300
    assert len(app.storage.get_history(24)) == 300
    # the live snapshot is not touched by batch uploads
    assert client.get("/api/current_status", headers=AUTH).status_code == 202


def test_batch_validation(client):
    post = lambda body: client.post("/api/sensor_data/batch", json=body, headers=AUTH)  # noqa: E731
    assert post({}).status_code == 400
    assert post({"readings": []}).status_code == 400
    assert post({"readings": [READING]}).status_code == 400                    # no timestamp
    assert post({"readings": ["x"]}).status_code == 400
    assert post({"readings": [{**READING, "timestamp": "2001-01-01"}]}).status_code == 400
    too_many = [{**READING, "timestamp": _iso(minutes=1)}] * 1001
    assert post({"readings": too_many}).status_code == 413


def test_history_and_aggregate_ranges_are_clamped(client, app, monkeypatch):
    calls = {}
    monkeypatch.setattr(app.storage, "get_history", lambda hours: calls.setdefault("h", []).append(hours) or [])
    monkeypatch.setattr(app.storage, "get_daily_aggregates", lambda days: calls.setdefault("d", []).append(days) or [])
    for q in ("hours=100000", "hours=abc", "hours=0"):
        client.get(f"/api/history?{q}", headers=AUTH)
    for q in ("days=-5", "days=1000"):
        client.get(f"/api/aggregates?{q}", headers=AUTH)
    assert calls == {"h": [168, 24, 1], "d": [1, 90]}


def test_concurrent_ingest_keeps_a_consistent_snapshot(client):
    errors = []

    def send(i):
        r = client.post("/api/sensor_data", json={**READING, "temperature": float(i)},
                        headers=AUTH, environ_base={"REMOTE_ADDR": f"198.51.100.{i}"})
        if r.status_code != 200:
            errors.append(r.status_code)

    threads = [threading.Thread(target=send, args=(i,)) for i in range(25)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    status = client.get("/api/current_status", headers=AUTH).get_json()
    assert 0 <= status["indoor_temp"] < 25


def test_forecast(client):
    body = client.get("/api/forecast", headers=AUTH).get_json()
    assert body["status"] == "success" and len(body["forecast"]) == 5
    assert {"day", "date", "temp_min", "temp_max", "icon", "pop"} <= set(body["forecast"][0])
