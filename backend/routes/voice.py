"""
routes/voice.py — Voice assistant + announcement endpoints.

POST /voice     WAV in → WAV out (voice assistant)
POST /speak     JSON in → WAV out (ambient announcement)
POST /alert     JSON in → WAV out (anomaly alert)
POST /reset     Clear conversation history
GET  /health    Service status
"""

from __future__ import annotations

import io
import time
import wave

from flask import Blueprint, Response, current_app, jsonify, request

voice_bp = Blueprint("voice", __name__)


@voice_bp.route("/voice", methods=["POST"])
def voice():
    """
    Core2 → WAV bytes → Gemini (STT + LLM) → TTS → WAV bytes → Core2.
    """
    t_start = time.time()
    gemini  = current_app.gemini_service
    tts     = current_app.tts_service
    bq      = current_app.bq_service

    wav_data = request.data
    if not wav_data or len(wav_data) < 44:
        return Response("Empty or invalid audio payload.", status=400)

    print(f"[/voice] Received {len(wav_data):,} bytes")

    try:
        with wave.open(io.BytesIO(wav_data)) as wf:
            print(
                f"[/voice] WAV — {wf.getframerate()} Hz  "
                f"{wf.getnchannels()}ch  "
                f"{wf.getsampwidth() * 8}-bit  "
                f"{wf.getnframes()} frames"
            )
    except Exception as exc:
        print(f"[/voice] WAV parse warning: {exc}")

    try:
        sensor_ctx = None
        if bq is not None:
            try:
                sensor_ctx = bq.get_recent_summary(hours=24)
            except Exception as exc:
                print(f"[/voice] BigQuery context fetch failed: {exc}")

        transcript, reply = gemini.send_audio(wav_data, sensor_context=sensor_ctx)
        print(f"[/voice] Total: {time.time() - t_start:.2f}s")

        if not reply:
            return Response(b"", status=204)

        wav_reply = tts.text_to_wav(reply)
        return Response(wav_reply, status=200, mimetype="audio/wav")

    except Exception as exc:
        import traceback
        traceback.print_exc()
        return Response(f"Internal error: {exc}", status=500)


@voice_bp.route("/speak", methods=["POST"])
def speak():
    """
    Ambient announcement triggered by PIR motion sensor (hourly).

    Request JSON:
    {
        "sensor_data": {...},   # current indoor sensor readings
        "outdoor":     {...},   # current outdoor weather
        "forecast":    [...]    # 5-day forecast list
    }

    Returns WAV audio bytes.
    """
    gemini = current_app.gemini_service
    tts    = current_app.tts_service

    body = request.json or {}
    sensor_data = body.get("sensor_data", {})
    outdoor     = body.get("outdoor",     {})
    forecast    = body.get("forecast",    [])

    print(f"[/speak] Generating announcement...")

    try:
        text = gemini.generate_announcement(sensor_data, outdoor, forecast)
        if not text:
            return Response(b"", status=204)

        wav = tts.text_to_wav(text)
        print(f"[/speak] Announcement ready: {len(wav)} bytes")
        return Response(wav, status=200, mimetype="audio/wav")

    except Exception as exc:
        import traceback
        traceback.print_exc()
        return Response(f"Internal error: {exc}", status=500)


@voice_bp.route("/alert", methods=["POST"])
def alert():
    """
    Anomaly alert triggered when sensor readings exceed thresholds.

    Request JSON:
    {
        "sensor_data":  {...},
        "anomaly_type": "co2_danger" | "co2_warning" | "humidity_low" | "humidity_high"
    }

    Returns WAV audio bytes.
    """
    gemini = current_app.gemini_service
    tts    = current_app.tts_service

    body        = request.json or {}
    sensor_data = body.get("sensor_data",  {})
    anomaly     = body.get("anomaly_type", "")

    print(f"[/alert] Anomaly: {anomaly}")

    try:
        text = gemini.generate_anomaly_alert(sensor_data, anomaly)
        if not text:
            return Response(b"", status=204)

        wav = tts.text_to_wav(text)
        print(f"[/alert] Alert ready: {len(wav)} bytes")
        return Response(wav, status=200, mimetype="audio/wav")

    except Exception as exc:
        import traceback
        traceback.print_exc()
        return Response(f"Internal error: {exc}", status=500)


@voice_bp.route("/reset", methods=["POST"])
def reset():
    """Clear the voice-assistant conversation history."""
    current_app.gemini_service.reset_history()
    return jsonify({"status": "ok", "message": "Conversation history cleared."})


@voice_bp.route("/health", methods=["GET"])
def health():
    """Service health check."""
    gemini = current_app.gemini_service
    return jsonify({
        "status":        "ok",
        "gemini_model":  current_app.config["GEMINI_MODEL"],
        "history_turns": gemini.history_turns,
    })