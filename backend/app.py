"""
app.py — Flask application factory for the Smart Space backend.

Architecture
------------
    device/          ←→  POST /api/sensor_data   (sensor telemetry)
                     ←→  POST /voice             (voice assistant)
    dashboard/       ←→  GET  /api/current_status
                     ←→  GET  /api/history
                     ←→  GET  /api/aggregates

Services are instantiated once at startup and attached to the Flask
application object so that all route handlers share the same instances
(conversation history, caches, etc.).

Usage
-----
    python app.py                          # development
    gunicorn "app:create_app()" -b 0.0.0.0:5001   # production
"""

from __future__ import annotations

from flask import Flask

from config import Config
from routes.voice   import voice_bp
from routes.sensors import sensors_bp
from routes.weather import weather_bp
from services.gemini_service    import GeminiService
from services.tts_service       import TTSService
from services.bigquery_service  import BigQueryService
from services.weather_service   import WeatherService
from services.ai_advice_service import AIAdviceService


def create_app() -> Flask:
    """Initialise and return the configured Flask application."""
    app = Flask(__name__)

    # ── Expose config values to the app context ───────────────────────────────
    app.config["GEMINI_MODEL"]         = Config.GEMINI_MODEL
    app.config["AI_COOLDOWN_SECONDS"]  = Config.AI_COOLDOWN_SECONDS

    # ── Instantiate services (singletons for the lifetime of the process) ─────
    app.gemini_service    = GeminiService()
    app.tts_service       = TTSService()
    app.weather_service   = WeatherService()
    app.ai_advice_service = AIAdviceService()

    # BigQuery is optional — gracefully degrade if credentials are missing.
    try:
        app.bq_service = BigQueryService()
    except Exception as exc:
        print(f"[app] WARNING: BigQuery unavailable — {exc}")
        app.bq_service = None

    # ── Register blueprints ───────────────────────────────────────────────────
    app.register_blueprint(voice_bp)
    app.register_blueprint(sensors_bp)
    app.register_blueprint(weather_bp)

    return app


if __name__ == "__main__":
    application = create_app()
    print("=" * 55)
    print(f"  Smart Space Backend — port {Config.PORT}")
    print("=" * 55)
    application.run(host="0.0.0.0", port=Config.PORT, debug=Config.DEBUG)