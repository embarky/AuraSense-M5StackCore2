"""
routes/sensors.py — Sensor telemetry ingestion and query endpoints for AuraSense.
"AuraSense: See the air you breathe."

POST /api/sensor_data      Receive readings from the edge device.
GET  /api/current_status   Latest state snapshot for the web dashboard.
GET  /api/history          Historical readings (query param: hours).
GET  /api/aggregates       Daily aggregates for charts (query param: days).
"""

from __future__ import annotations

import time
import threading

from flask import Blueprint, Response, current_app, jsonify, request

sensors_bp = Blueprint("sensors", __name__)

# ── In-Memory State (Shared between edge device and dashboard) ────────────────

_state: dict = {
    "ai_advice": "AuraSense is initializing...",
}
_last_ai_time: float = 0.0


@sensors_bp.route("/api/sensor_data", methods=["POST"])
def receive_sensor_data():
    """
    Primary telemetry ingestion endpoint called by the edge device every cycle.

    1. Caches current outdoor weather based on device IP.
    2. Stores the indoor reading in BigQuery.
    3. Triggers a background AuraSense AI-advice generation (rate-limited).
    4. Returns outdoor weather + NTP time-sync payload to the edge device.
    """
    global _state, _last_ai_time

    payload = request.json
    if not payload:
        return jsonify({"error": "Missing JSON payload."}), 400

    bq      = current_app.bq_service
    weather = current_app.weather_service
    ai      = current_app.ai_advice_service

    # ── 1. Outdoor Weather (Cached using Device IP) ───────────────────────────
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if client_ip:
        client_ip = client_ip.split(',')[0].strip()
        # [CRITICAL FIX 1] Ignore Docker bridge IPs to get real geolocation
        if client_ip.startswith(("172.", "192.168.", "10.")):
            client_ip = None
            
    outdoor = weather.get_current(client_ip)
    loc     = weather.location

    # ── 2. Update In-Memory State ─────────────────────────────────────────────
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
        "ai_advice":     _state.get("ai_advice", "Analyzing environment..."),
    }

    # ── 3. BigQuery Persistence ───────────────────────────────────────────────
    if bq is not None:
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
            print(f"[AuraSense | API] BigQuery persistence failed: {msg}")
    else:
        pass

    # ── 4. AI Advice (Rate-limited background task) ───────────────────────────
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

    # ── 5. Device Synchronization Response ────────────────────────────────────
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
        # [CRITICAL FIX 2] Return the location back to the M5Stack UI
        "location":     loc.get("city", "Unknown"), 
        "utc_time":     ntp_sync,
        "ai_advice":    _state.get("ai_advice"),
    }), 200


@sensors_bp.route("/api/current_status", methods=["GET"])
def current_status():
    """Real-time snapshot consumed by the AuraSense Streamlit dashboard."""
    if not _state.get("timestamp"):
        return jsonify({"message": "Device offline or no telemetry received yet."}), 202

    response = jsonify(_state)
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response, 200


@sensors_bp.route("/api/history", methods=["GET"])
def history():
    """
    Return raw sensor readings for the requested time window.
    Query param: hours (default 24).
    """
    bq = current_app.bq_service
    if not bq:
        return jsonify([]), 200

    hours = int(request.args.get("hours", 24))
    rows  = bq.get_history(hours=hours)
    return jsonify(rows), 200


@sensors_bp.route("/api/aggregates", methods=["GET"])
def aggregates():
    """
    Return daily min/max/avg aggregates for dashboard charting.
    Query param: days (default 7).
    """
    bq = current_app.bq_service
    if not bq:
        return jsonify([]), 200

    days = int(request.args.get("days", 7))
    rows = bq.get_daily_aggregates(days=days)
    return jsonify(rows), 200


# ── Background Thread Helper ──────────────────────────────────────────────────

def _run_ai_advice(
    ai_service,
    indoor_temp, indoor_hum, eco2, tvoc,
    outdoor_temp, outdoor_desc,
) -> None:
    """Executed in a daemon thread so the HTTP POST response is never blocked."""
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