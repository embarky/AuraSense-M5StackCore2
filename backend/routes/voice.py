"""
routes/voice.py — Voice assistant and audio announcement endpoints for AuraSense.
"AuraSense: See the air you breathe."

POST /voice     WAV in → WAV out (interactive voice assistant)
POST /speak     JSON in → WAV out (ambient environmental announcement)
POST /alert     JSON in → WAV out (critical anomaly alert)
POST /reset     Clear the calling device's conversation history
GET  /health    Service status (no authentication, for uptime checks)

Every endpoint except /health requires the X-API-Key header. The endpoints
that call paid LLM / TTS APIs are rate-limited per client.
"""

from __future__ import annotations

import io
import logging
import time
import wave

from flask import Blueprint, Response, current_app, jsonify, request
from security import get_device_id, rate_limit, require_api_key

log = logging.getLogger(__name__)

voice_bp = Blueprint("voice", __name__)

_INTERNAL_ERROR = "Internal error."


@voice_bp.route("/voice", methods=["POST"])
@require_api_key
@rate_limit(limit=10, per_seconds=60)
def voice():
    """
    Primary voice interaction endpoint for the edge device.
    Pipeline: Core2 → WAV bytes → Gemini (STT + LLM) → TTS → WAV bytes → Core2.
    """
    t_start = time.time()
    gemini  = current_app.gemini_service
    tts     = current_app.tts_service
    storage = current_app.storage

    wav_data = request.data
    if not wav_data or len(wav_data) < 44:
        return Response("Empty or invalid audio payload.", status=400)

    log.info("Received audio payload: %s bytes", f"{len(wav_data):,}")

    # Validate the incoming WAV header from the ESP32 — useful when debugging
    # the hardware microphone configuration.
    try:
        with wave.open(io.BytesIO(wav_data)) as wf:
            log.info(
                "Audio format: %sHz | %sch | %s-bit | %s frames",
                wf.getframerate(), wf.getnchannels(),
                wf.getsampwidth() * 8, wf.getnframes(),
            )
    except Exception as exc:
        log.warning("Malformed WAV header: %s", exc)

    try:
        # Recent 24-hour context so the AI can answer questions such as
        # "How was the air quality last night?"
        sensor_ctx = None
        if storage is not None:
            try:
                sensor_ctx = storage.get_recent_summary(hours=24)
            except Exception as exc:
                log.warning("Sensor context fetch failed: %s", exc)

        transcript, reply = gemini.send_audio(
            wav_data, sensor_context=sensor_ctx, session_id=get_device_id()
        )
        log.info("Voice processing latency: %.2fs", time.time() - t_start)

        if not reply:
            return Response(b"", status=204)

        wav_reply = tts.text_to_wav(reply)
        return Response(wav_reply, status=200, mimetype="audio/wav")

    except Exception:
        log.exception("Voice pipeline failed")
        return Response(_INTERNAL_ERROR, status=500)


@voice_bp.route("/speak", methods=["POST"])
@require_api_key
@rate_limit(limit=6, per_seconds=60)
def speak():
    """
    Hourly ambient announcement.

    Request JSON: {"sensor_data": {...}, "outdoor": {...}, "forecast": [...]}
    Returns WAV audio bytes ready for playback.
    """
    gemini = current_app.gemini_service
    tts    = current_app.tts_service

    body = request.get_json(silent=True) or {}
    sensor_data = body.get("sensor_data", {})
    outdoor     = body.get("outdoor",     {})
    forecast    = body.get("forecast",    [])

    log.info("Generating ambient announcement")

    try:
        text = gemini.generate_announcement(sensor_data, outdoor, forecast)
        if not text:
            return Response(b"", status=204)

        wav = tts.text_to_wav(text)
        log.info("Announcement audio ready: %s bytes", f"{len(wav):,}")
        return Response(wav, status=200, mimetype="audio/wav")

    except Exception:
        log.exception("Announcement pipeline failed")
        return Response(_INTERNAL_ERROR, status=500)


@voice_bp.route("/alert", methods=["POST"])
@require_api_key
@rate_limit(limit=6, per_seconds=60)
def alert():
    """
    Spoken alert when readings exceed the critical thresholds.

    Request JSON: {"sensor_data": {...}, "anomaly_type": "co2_danger" | ...}
    Returns WAV audio bytes prioritising immediate action ("Open a window").
    """
    gemini = current_app.gemini_service
    tts    = current_app.tts_service

    body        = request.get_json(silent=True) or {}
    sensor_data = body.get("sensor_data",  {})
    anomaly     = str(body.get("anomaly_type", ""))[:100]

    log.info("Alert triggered: %s", anomaly)

    try:
        text = gemini.generate_anomaly_alert(sensor_data, anomaly)
        if not text:
            return Response(b"", status=204)

        wav = tts.text_to_wav(text)
        log.info("Alert audio ready: %s bytes", f"{len(wav):,}")
        return Response(wav, status=200, mimetype="audio/wav")

    except Exception:
        log.exception("Alert pipeline failed")
        return Response(_INTERNAL_ERROR, status=500)


@voice_bp.route("/reset", methods=["POST"])
@require_api_key
def reset():
    """Clear the calling device's voice-assistant conversation history."""
    current_app.gemini_service.reset_history(get_device_id())
    return jsonify({"status": "ok", "message": "Conversation history cleared."})


@voice_bp.route("/health", methods=["GET"])
def health():
    """Unauthenticated liveness check; reveals no configuration details."""
    return jsonify({"status": "ok", "service": "AuraSense API"})
