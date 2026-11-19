"""
routes/sensors.py — Sensor telemetry ingestion and query endpoints for AuraSense.
"AuraSense: See the air you breathe."

POST /api/sensor_data      Receive one reading from the edge device.
POST /api/sensor_data/batch  Store up to 1000 timestamped readings at once
                           (buffered offline data, simulator history).
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
from datetime import datetime, timedelta, timezone
from typing import Optional

from flask import Blueprint, current_app, jsonify, request
from security import get_device_id, get_public_client_ip, rate_limit, require_api_key
from storage import normalise_reading

log = logging.getLogger(__name__)

sensors_bp = Blueprint("sensors", __name__)

MAX_HISTORY_HOURS   = 24 * 7
MAX_AGGREGATE_DAYS  = 90
MAX_BATCH_SIZE      = 1000
MAX_BACKFILL_DAYS   = 30

# ── In-Memory State (shared between edge device and dashboard) ────────────────

_state_lock = threading.Lock()
_state: dict = {"ai_advice": "AuraSense is initializing..."}
_last_ai_time: float = 0.0


def _parse_timestamp(value) -> Optional[datetime]:
    """
    Parse an optional reading timestamp (ISO 8601 string or Unix seconds).
    Returns None when absent; raises ValueError when invalid or out of range
    (more than 30 days old or more than 1 minute in the future).
    """
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        ts = datetime.fromtimestamp(value, tz=timezone.utc)
    else:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if not now - timedelta(days=MAX_BACKFILL_DAYS) <= ts <= now + timedelta(minutes=1):
        raise ValueError("timestamp out of accepted range")
    return ts


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
    2. Stores the reading (SQLite or BigQuery). An optional "timestamp" field
       records when it was measured, e.g. for readings buffered while offline.
    3. Triggers a background AI-advice generation (rate-limited by cooldown).
    4. Returns outdoor weather, local time and UTC offset to the edge device.
    """
    global _state, _last_ai_time

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not payload:
        return jsonify({"error": "Missing JSON payload."}), 400
    try:
        reading_ts = _parse_timestamp(payload.get("timestamp"))
    except (TypeError, ValueError) as exc:
        return jsonify({"error": f"Invalid timestamp: {exc}"}), 400

    storage = current_app.storage
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

    # ── 3. Persistence ────────────────────────────────────────────────────────
    if storage is not None:
        row = normalise_reading(
            {**payload,
             "timezone":  loc.get("timezone", "UTC"),
             "location":  loc.get("city"),
             "device_id": get_device_id()},
            reading_ts,
        )
        success, msg = storage.insert_readings([row])
        if not success:
            log.warning("Persistence failed: %s", msg)

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


@sensors_bp.route("/api/sensor_data/batch", methods=["POST"])
@require_api_key
@rate_limit(limit=30, per_seconds=60)
def receive_sensor_batch():
    """
    Store many timestamped readings in one request.

    Request JSON: {"readings": [{"timestamp": "...", "temperature": ..., ...}, ...]}
    Every reading must carry a timestamp (ISO 8601 or Unix seconds).
    Does not update the live snapshot or trigger AI advice.
    """
    body = request.get_json(silent=True) or {}
    readings = body.get("readings")
    if not isinstance(readings, list) or not readings:
        return jsonify({"error": "Expected a non-empty 'readings' list."}), 400
    if len(readings) > MAX_BATCH_SIZE:
        return jsonify({"error": f"At most {MAX_BATCH_SIZE} readings per request."}), 413

    storage = current_app.storage
    if storage is None:
        return jsonify({"error": "No storage configured."}), 503

    loc = current_app.weather_service.location
    rows = []
    for i, item in enumerate(readings):
        if not isinstance(item, dict):
            return jsonify({"error": f"Reading {i} is not an object."}), 400
        try:
            ts = _parse_timestamp(item.get("timestamp"))
        except (TypeError, ValueError) as exc:
            return jsonify({"error": f"Reading {i}: invalid timestamp ({exc})."}), 400
        if ts is None:
            return jsonify({"error": f"Reading {i}: timestamp is required."}), 400
        rows.append(normalise_reading(
            {**item,
             "timezone":  loc.get("timezone", "UTC"),
             "location":  loc.get("city"),
             "device_id": get_device_id()},
            ts,
        ))

    success, msg = storage.insert_readings(rows)
    if not success:
        return jsonify({"error": "Persistence failed."}), 502
    return jsonify({"status": "ok", "stored": len(rows)}), 200


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
    storage = current_app.storage
    if not storage:
        return jsonify([]), 200

    hours = _bounded_int_arg("hours", 24, 1, MAX_HISTORY_HOURS)
    return jsonify(storage.get_history(hours=hours)), 200


@sensors_bp.route("/api/aggregates", methods=["GET"])
@require_api_key
def aggregates():
    """Daily min/max/avg aggregates for the last `days` days (1-90, default 7)."""
    storage = current_app.storage
    if not storage:
        return jsonify([]), 200

    days = _bounded_int_arg("days", 7, 1, MAX_AGGREGATE_DAYS)
    return jsonify(storage.get_daily_aggregates(days=days)), 200


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
