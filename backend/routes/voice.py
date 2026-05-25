"""
routes/voice.py — Voice assistant and audio announcement endpoints for AuraSense.
"AuraSense: See the air you breathe."

POST /voice     WAV in → WAV out (Interactive voice assistant)
POST /speak     JSON in → WAV out (Ambient environmental announcement)
POST /alert     JSON in → WAV out (Critical anomaly alert)
POST /reset     Clear conversation history buffer
GET  /health    Service status and metrics
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
    Primary voice interaction endpoint for the edge device.
    Pipeline: Core2 → WAV bytes → Gemini (STT + LLM) → TTS → WAV bytes → Core2.
    """
    t_start = time.time()
    gemini  = current_app.gemini_service
    tts     = current_app.tts_service
    bq      = current_app.bq_service

    wav_data = request.data
    if not wav_data or len(wav_data) < 44:
        return Response("Empty or invalid audio payload.", status=400)

    print(f"[AuraSense | Voice] Received audio payload: {len(wav_data):,} bytes")

    # Diagnostic block: Validates the incoming WAV header from the ESP32.
    # Crucial for debugging hardware microphone configuration issues.
    try:
        with wave.open(io.BytesIO(wav_data)) as wf:
            print(
                f"[AuraSense | Voice] Format: {wf.getframerate()}Hz | "
                f"{wf.getnchannels()}ch | "
                f"{wf.getsSpampwidth() * 8}-bit | "
                f"{wf.getnframes()} frames"
            )
    except Exception as exc:
        print(f"[AuraSense | Voice] WARNING: Malformed WAV header - {exc}")

    try:
        # Fetch the latest 24-hour environmental context so the AI can 
        # answer questions like "How was the air quality last night?"
        sensor_ctx = None
        if bq is not None:
            try:
                sensor_ctx = bq.get_recent_summary(hours=24)
            except Exception as exc:
                print(f"[AuraSense | Voice] BigQuery context fetch failed: {exc}")

        # Process through Gemini AI
        transcript, reply = gemini.send_audio(wav_data, sensor_context=sensor_ctx)
        print(f"[AuraSense | Voice] Processing latency: {time.time() - t_start:.2f}s")

        if not reply:
            return Response(b"", status=204)

        # Synthesize reply back to audio
        wav_reply = tts.text_to_wav(reply)
        return Response(wav_reply, status=200, mimetype="audio/wav")

    except Exception as exc:
        import traceback
        traceback.print_exc()
        return Response(f"Internal error: {exc}", status=500)


@voice_bp.route("/speak", methods=["POST"])
def speak():
    """
    Ambient announcement triggered by the device's PIR motion sensor.

    Request JSON:
    {
        "sensor_data": {...},   # Current indoor sensor telemetry
        "outdoor":     {...},   # Current outdoor weather
        "forecast":    [...]    # 5-day forecast list
    }

    Returns WAV audio bytes ready for playback.
    """
    gemini = current_app.gemini_service
    tts    = current_app.tts_service

    body = request.json or {}
    sensor_data = body.get("sensor_data", {})
    outdoor     = body.get("outdoor",     {})
    forecast    = body.get("forecast",    [])

    print(f"[AuraSense | Speak] Generating ambient announcement...")

    try:
        text = gemini.generate_announcement(sensor_data, outdoor, forecast)
        if not text:
            return Response(b"", status=204)

        wav = tts.text_to_wav(text)
        print(f"[AuraSense | Speak] Audio ready: {len(wav):,} bytes")
        return Response(wav, status=200, mimetype="audio/wav")

    except Exception as exc:
        import traceback
        traceback.print_exc()
        return Response(f"Internal error: {exc}", status=500)


@voice_bp.route("/alert", methods=["POST"])
def alert():
    """
    Urgent anomaly alert triggered when environmental readings exceed safe thresholds.

    Request JSON:
    {
        "sensor_data":  {...},
        "anomaly_type": "co2_danger" | "co2_warning" | "humidity_low" | "humidity_high"
    }

    Returns WAV audio bytes prioritizing immediate user action (e.g., "Open a window").
    """
    gemini = current_app.gemini_service
    tts    = current_app.tts_service

    body        = request.json or {}
    sensor_data = body.get("sensor_data",  {})
    anomaly     = body.get("anomaly_type", "")

    print(f"[AuraSense | Alert] Triggered: {anomaly}")

    try:
        text = gemini.generate_anomaly_alert(sensor_data, anomaly)
        if not text:
            return Response(b"", status=204)

        wav = tts.text_to_wav(text)
        print(f"[AuraSense | Alert] Audio ready: {len(wav):,} bytes")
        return Response(wav, status=200, mimetype="audio/wav")

    except Exception as exc:
        import traceback
        traceback.print_exc()
        return Response(f"Internal error: {exc}", status=500)


@voice_bp.route("/reset", methods=["POST"])
def reset():
    """Clear the voice-assistant conversation history buffer."""
    current_app.gemini_service.reset_history()
    return jsonify({"status": "ok", "message": "AuraSense conversation history cleared."})


@voice_bp.route("/health", methods=["GET"])
def health():
    """Service health and diagnostic check."""
    gemini = current_app.gemini_service
    return jsonify({
        "status":        "ok",
        "service":       "AuraSense Voice API",
        "gemini_model":  current_app.config["GEMINI_MODEL"],
        "history_turns": gemini.history_turns,
    })