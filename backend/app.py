"""
app.py — Flask application factory for the AuraSense backend.
"AuraSense: See the air you breathe."

Architecture
------------
    device/          ←→  POST /api/sensor_data   (sensor telemetry)
                     ←→  POST /voice             (voice assistant)
    dashboard/       ←→  GET  /api/current_status
                     ←→  GET  /api/history
                     ←→  GET  /api/aggregates

Services are instantiated once at startup and attached to the Flask
application object. This ensures all route handlers share the same 
singleton instances (e.g., conversation history, memory caches).

Usage
-----
    python app.py                                 # Development
    gunicorn "app:create_app()" -b 0.0.0.0:5001 --workers 1 --threads 8   # Production

The in-memory device snapshot and conversation histories live in this
process, so production runs ONE worker with several threads (see Dockerfile).
"""

from __future__ import annotations

import logging

from config import Config
from flask import Flask
from routes.sensors import sensors_bp
from routes.voice import voice_bp
from routes.weather import weather_bp

log = logging.getLogger("aurasense.app")

# Core AI and Data Services
from services.ai_advice_service import AIAdviceService
from services.bigquery_service import BigQueryService
from services.gemini_service import GeminiService
from services.tts_service import TTSService
from services.weather_service import WeatherService


def create_app() -> Flask:
    """Initialize and return the configured AuraSense Flask application."""
    app = Flask(__name__)

    # ── Expose config values to the app context ───────────────────────────────
    app.config["GEMINI_MODEL"]         = Config.GEMINI_MODEL
    app.config["AI_COOLDOWN_SECONDS"]  = Config.AI_COOLDOWN_SECONDS
    app.config["API_KEY"]              = Config.API_KEY

    if not Config.API_KEY:
        log.warning(
            "No API key configured (AURASENSE_API_KEY / api_key): all endpoints "
            "are OPEN. Use this only for local development."
        )

    # ── Instantiate services (Singletons for the lifetime of the process) ─────
    # Attaching these to the 'app' object prevents memory leaks and ensures
    # a shared context across all incoming HTTP requests.
    app.gemini_service    = GeminiService()
    app.tts_service       = TTSService()
    app.weather_service   = WeatherService()
    app.ai_advice_service = AIAdviceService()

    # BigQuery is optional — gracefully degrade if cloud credentials are missing
    # so the local dashboard can still function without cloud storage.
    try:
        app.bq_service = BigQueryService()
    except Exception as exc:
        log.warning("BigQuery unavailable, running without persistence: %s", exc)
        app.bq_service = None

    # ── Register blueprints ───────────────────────────────────────────────────
    app.register_blueprint(voice_bp)
    app.register_blueprint(sensors_bp)
    app.register_blueprint(weather_bp)

    return app


if __name__ == "__main__":
    application = create_app()
    log.info("AuraSense backend starting on port %s", Config.PORT)
    application.run(host="0.0.0.0", port=Config.PORT, debug=Config.DEBUG)