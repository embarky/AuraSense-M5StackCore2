"""
routes/sensors.py — Sensor data ingestion and query endpoints.

POST /api/sensor_data      Receive readings from the Core2 device.
GET  /api/current_status   Latest state snapshot for Streamlit dashboard.
GET  /api/history          Historical readings (query param: hours).
GET  /api/aggregates       Daily aggregates for charts (query param: days).
"""

from __future__ import annotations

import time
import threading

from flask import Blueprint, Response, current_app, jsonify, request

sensors_bp = Blueprint("sensors", __name__)

# ── In-memory state (shared between device and dashboard) ─────────────────────

_state: dict = {
    "ai_advice": "Waiting for initial AI analysis…",
}
_last_ai_time: float = 0.0


@sensors_bp.route("/api/sensor_data", methods=["POST"])
def receive_sensor_data():
    """
    Primary ingestion endpoint called by the Core2 every polling cycle.

    1. Stores the reading in BigQuery.
    2. Fetches current outdoor weather.
    3. Triggers a background AI-advice generation (rate-limited).
    4. Returns outdoor weather + NTP time-sync payload to the device.
    """
    global _state, _last_ai_time

    payload = request.json
    if not payload:
        return jsonify({"error": "Missing JSON payload."}), 400

    bq      = current_app.bq_service
    weather = current_app.weather_service
    ai      = current_app.ai_advice_service

    # ── 1. Outdoor weather (cached) ───────────────────────────────────────────
    outdoor = weather.get_current()
    loc     = weather.location

    # ── 2. Update in-memory state ─────────────────────────────────────────────
    now = time.time()
    _state = {
        "timestamp":     now,
        "location":      loc.get("city"),
        "indoor_temp":   payload.get("temperature"),
        "indoor_hum":    payload.get("humidity"),
        "pressure":      payload.get("pressure"),
        "eco2":          payload.get("eco2"),
        "tvoc":          payload.get("tvoc"),
        "motion":        payload.get("motion", False),
        "outdoor_temp":  outdoor.get("temp"),
        "outdoor_desc":  outdoor.get("description"),
        "outdoor_icon":  outdoor.get("icon"),
        "timezone":      loc.get("timezone", "UTC"),
        "ai_advice":     _state.get("ai_advice", "Analysing…"),
    }

    # ── 3. BigQuery persistence ───────────────────────────────────────────────
    bq_payload = {
        "temperature":     payload.get("temperature"),
        "humidity":        payload.get("humidity"),
        "pressure":        payload.get("pressure"),
        "eco2":            payload.get("eco2"),
        "tvoc":            payload.get("tvoc"),
        "motion_detected": payload.get("motion", False),
        "timezone":        loc.get("timezone", "UTC"),
    }
    success, msg = bq.insert_sensor_reading(bq_payload)
    if not success:
        print(f"[/api/sensor_data] BigQuery error: {msg}")

    # ── 4. AI advice (rate-limited background task) ───────────────────────────
    cooldown = current_app.config.get("AI_COOLDOWN_SECONDS", 600)
    if now - _last_ai_time >= cooldown:
        _last_ai_time = now
        thread = threading.Thread(
            target=_run_ai_advice,
            args=(
                ai,
                payload.get("temperature"),
                payload.get("humidity"),
                payload.get("eco2"),
                payload.get("tvoc"),
                outdoor.get("temp"),
                outdoor.get("description"),
            ),
            daemon=True,
        )
        thread.start()

    # ── 5. NTP time-sync response ─────────────────────────────────────────────
    offset    = loc.get("offset", 3600)
    local_utc = time.gmtime(now + offset)
    ntp_sync  = [
        local_utc.tm_year, local_utc.tm_mon, local_utc.tm_mday, 0,
        local_utc.tm_hour, local_utc.tm_min, local_utc.tm_sec,  0,
    ]

    return jsonify({
        "status":       "ok",
        "outdoor_temp": outdoor.get("temp"),
        "outdoor_desc": outdoor.get("description"),
        "outdoor_icon": outdoor.get("icon"),
        "location":     loc.get("city"),
        "utc_time":     ntp_sync,
        "ai_advice":    _state.get("ai_advice"),
    }), 200


@sensors_bp.route("/api/current_status", methods=["GET"])
def current_status():
    """Real-time snapshot consumed by the Streamlit dashboard."""
    if not _state.get("timestamp"):
        return jsonify({"message": "Device offline or no data received yet."}), 202

    response = jsonify(_state)
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response, 200


@sensors_bp.route("/api/history", methods=["GET"])
def history():
    """
    Return raw sensor readings for the requested window.
    Query param: hours (default 24).
    """
    hours = int(request.args.get("hours", 24))
    rows  = current_app.bq_service.get_history(hours=hours)
    return jsonify(rows), 200


@sensors_bp.route("/api/aggregates", methods=["GET"])
def aggregates():
    """
    Return daily min/max/avg aggregates for charting.
    Query param: days (default 7).
    """
    days = int(request.args.get("days", 7))
    rows = current_app.bq_service.get_daily_aggregates(days=days)
    return jsonify(rows), 200


# ── Background helper ─────────────────────────────────────────────────────────

def _run_ai_advice(
    ai_service,
    indoor_temp, indoor_hum, eco2, tvoc,
    outdoor_temp, outdoor_desc,
) -> None:
    """Called in a daemon thread so the POST response is never blocked."""
    global _state
    advice = ai_service.generate_advice(
        indoor_temp=indoor_temp,
        indoor_hum=indoor_hum,
        eco2=eco2,
        tvoc=tvoc,
        outdoor_temp=outdoor_temp,
        outdoor_desc=outdoor_desc,
    )
    _state["ai_advice"] = advice