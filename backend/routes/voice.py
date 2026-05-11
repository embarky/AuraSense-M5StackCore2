"""
routes/voice.py — Voice-assistant endpoints.

POST /voice     Accepts a WAV file, returns a WAV file.
POST /reset     Clears the conversation history.
GET  /health    Returns service status (used by monitoring).
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
    Core2 → WAV bytes → Gemini (STT + LLM + Google Search) → edge-tts → WAV bytes → Core2.

    The sensor context (recent BigQuery readings) is injected automatically
    when the user's question appears to be about the home environment.
    """
    t_start = time.time()
    gemini  = current_app.gemini_service
    tts     = current_app.tts_service
    bq      = current_app.bq_service

    wav_data = request.data
    if not wav_data or len(wav_data) < 44:
        return Response("Empty or invalid audio payload.", status=400)

    print(f"[/voice] Received {len(wav_data):,} bytes")

    # Log WAV metadata for debugging.
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
        # ── 1. Gemini: understand audio ───────────────────────────────────────
        t1 = time.time()

        # Quick first-pass transcription is NOT available without Whisper, so we
        # let Gemini handle everything.  For sensor-context injection we use the
        # previous turn's transcript stored in history if available.
        sensor_ctx = None
        if bq is not None:
            try:
                sensor_ctx = bq.get_recent_summary(hours=24)
            except Exception as exc:
                print(f"[/voice] BigQuery context fetch failed: {exc}")

        transcript, reply = gemini.send_audio(wav_data, sensor_context=sensor_ctx)
        print(f"[/voice] Gemini: {time.time() - t1:.2f}s")

        if not reply:
            return Response(b"", status=204)

        # ── 2. TTS: convert reply to WAV ──────────────────────────────────────
        t2 = time.time()
        wav_reply = tts.text_to_wav(reply)
        print(f"[/voice] TTS: {time.time() - t2:.2f}s")
        print(f"[/voice] Total server time: {time.time() - t_start:.2f}s")

        return Response(wav_reply, status=200, mimetype="audio/wav")

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
    """Service health check and status summary."""
    gemini = current_app.gemini_service
    return jsonify({
        "status":          "ok",
        "gemini_model":    current_app.config["GEMINI_MODEL"],
        "history_turns":   gemini.history_turns,
    })