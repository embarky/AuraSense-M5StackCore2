"""
routes/sensors.py — Sensor telemetry ingestion and query endpoints for AuraSense.
"AuraSense: See the air you breathe."

POST /api/sensor_data      Receive readings from the edge device.
GET  /api/current_status   Latest state snapshot for the web dashboard.
GET  /api/history          Historical readings (query param: hours, 1-168).
GET  /api/aggregates       Daily aggregates for charts (query param: days, 1-90).

All endpoints require the X-API-Key header (see security.py).

Concurrency note
----------------
The latest snapshot is held in process memory. The backend therefore runs as a
single gunicorn worker with several threads (see Dockerfile), so every request
sees the same snapshot; a lock guards concurrent access from those threads.
"""

from __future__ import annotations

import logging
import threading
import time

from flask import Blueprint, current_app, jsonify, request
from security import get_public_client_ip, rate_limit, require_api_key

log = logging.getLogger(__name__)

sensors_bp = Blueprint("sensors", __name__)

MAX_HISTORY_HOURS   = 24 * 7
MAX_AGGREGATE_DAYS  = 90

# ── In-Memory State (shared between edge device and dashboard) ────────────────

_state_lock = threading.Lock()
_state: dict = {"ai_advice": "AuraSense is initializing..."}
_last_ai_time: float = 0.0


def _bounded_int_arg(name: str, default: int, minimum: int, maximum: int) -> int:
    """Read an integer query parameter and clamp it to [minimum, maximum]."""
    try:
        value = int(request.args.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


@sensors_bp.route("/api/sensor_data", methods=["POST"])
@require_api_key
@rate_limit(limit=60, per_seconds=60)
def receive_sensor_data():
    """
    Primary telemetry ingestion endpoint called by the edge device every cycle.

    1. Caches current outdoor weather based on the device's public IP.
    2. Stores the indoor reading in BigQuery.
    3. Triggers a background AI-advice generation (rate-limited by cooldown).
    4. Returns outdoor weather, local time and UTC offset to the edge device.
    """
    global _state, _last_ai_time

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not payload:
        return jsonify({"error": "Missing JSON payload."}), 400

    bq      = current_app.bq_service
    weather = current_app.weather_service
    ai      = current_app.ai_advice_service

    # ── 1. Outdoor weather (cached, located via the device's public IP) ───────
    outdoor = weather.get_current(get_public_client_ip())
    loc     = weather.location

    # ── 2. Update in-memory state ─────────────────────────────────────────────
    now = time.time()
    with _state_lock:
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
        ai_advice = _state["ai_advice"]

        cooldown = current_app.config.get("AI_COOLDOWN_SECONDS", 600)
        start_ai = now - _last_ai_time >= cooldown
        if start_ai:
            _last_ai_time = now

    # ── 3. BigQuery persistence ───────────────────────────────────────────────
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
            log.warning("BigQuery persistence failed: %s", msg)

    # ── 4. AI advice (background thread so the device is never blocked) ───────
    if start_ai:
        threading.Thread(
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
        ).start()

    # ── 5. Device synchronisation response ────────────────────────────────────
    offset    = int(loc.get("offset", 3600))
    local_now = time.gmtime(now + offset)
    local_time = [
        local_now.tm_year, local_now.tm_mon, local_now.tm_mday, 0,
        local_now.tm_hour, local_now.tm_min, local_now.tm_sec,  0,
    ]

    return jsonify({
        "status":       "ok",
        "outdoor_temp": outdoor.get("temp"),
        "outdoor_desc": outdoor.get("description"),
        "outdoor_icon": outdoor.get("icon"),
        "location":     loc.get("city", "Unknown"),
        # Local wall-clock time (kept under the legacy key for older firmware)
        "utc_time":     local_time,
        # Seconds east of UTC, DST-aware; the device uses it for its clock.
        "utc_offset":   offset,
        "ai_advice":    ai_advice,
    }), 200


@sensors_bp.route("/api/current_status", methods=["GET"])
@require_api_key
def current_status():
    """Real-time snapshot consumed by the AuraSense Streamlit dashboard."""
    with _state_lock:
        snapshot = dict(_state)
    if not snapshot.get("timestamp"):
        return jsonify({"message": "Device offline or no telemetry received yet."}), 202
    return jsonify(snapshot), 200


@sensors_bp.route("/api/history", methods=["GET"])
@require_api_key
def history():
    """Raw sensor readings for the last `hours` hours (1-168, default 24)."""
    bq = current_app.bq_service
    if not bq:
        return jsonify([]), 200

    hours = _bounded_int_arg("hours", 24, 1, MAX_HISTORY_HOURS)
    return jsonify(bq.get_history(hours=hours)), 200


@sensors_bp.route("/api/aggregates", methods=["GET"])
@require_api_key
def aggregates():
    """Daily min/max/avg aggregates for the last `days` days (1-90, default 7)."""
    bq = current_app.bq_service
    if not bq:
        return jsonify([]), 200

    days = _bounded_int_arg("days", 7, 1, MAX_AGGREGATE_DAYS)
    return jsonify(bq.get_daily_aggregates(days=days)), 200


# ── Background thread helper ──────────────────────────────────────────────────

def _run_ai_advice(
    ai_service,
    indoor_temp, indoor_hum, eco2, tvoc,
    outdoor_temp, outdoor_desc,
) -> None:
    """Executed in a daemon thread so the HTTP POST response is never blocked."""
    advice = ai_service.generate_advice(
        indoor_temp=indoor_temp,
        indoor_hum=indoor_hum,
        eco2=eco2,
        tvoc=tvoc,
        outdoor_temp=outdoor_temp,
        outdoor_desc=outdoor_desc,
    )
    with _state_lock:
        _state["ai_advice"] = advice
