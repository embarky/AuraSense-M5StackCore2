"""
app.py — Flask application factory for the AuraSense backend.
"AuraSense: See the air you breathe."

Architecture
------------
    device/          ←→  POST /api/sensor_data         (sensor telemetry)
                     ←→  POST /api/sensor_data/batch   (buffered / simulated history)
                     ←→  POST /voice /speak /alert     (voice features)
    dashboard/       ←→  GET  /api/current_status
                     ←→  GET  /api/history
                     ←→  GET  /api/aggregates
                     ←→  GET  /api/forecast

Every external dependency sits behind a provider that can be swapped through
configuration (see config.py):

    storage   sqlite | bigquery
    ai        mock   | gemini
    weather   mock   | openweather
    tts       mock   | edge

Real providers are imported only when selected, so demo mode needs none of
the cloud SDKs to be configured.

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
from storage import create_storage

log = logging.getLogger("aurasense.app")


def _build_services(app: Flask) -> None:
    """Instantiate the configured providers once and attach them to the app."""
    from services import mock_services as mock

    if Config.AI_PROVIDER == "gemini":
        from services.ai_advice_service import AIAdviceService
        from services.gemini_service import GeminiService
        app.gemini_service, app.ai_advice_service = GeminiService(), AIAdviceService()
    else:
        app.gemini_service, app.ai_advice_service = mock.MockGeminiService(), mock.MockAdviceService()

    if Config.TTS_PROVIDER == "edge":
        from services.tts_service import TTSService
        app.tts_service = TTSService()
    else:
        app.tts_service = mock.MockTTSService()

    if Config.WEATHER_PROVIDER == "openweather":
        from services.weather_service import WeatherService
        app.weather_service = WeatherService()
    else:
        app.weather_service = mock.MockWeatherService()

    # Storage is optional: without it the API still serves live data.
    app.storage = create_storage(Config.STORAGE_BACKEND, Config.SQLITE_PATH)


def create_app() -> Flask:
    """Initialize and return the configured AuraSense Flask application."""
    app = Flask(__name__)

    app.config["GEMINI_MODEL"]        = Config.GEMINI_MODEL
    app.config["AI_COOLDOWN_SECONDS"] = Config.AI_COOLDOWN_SECONDS
    app.config["API_KEY"]             = Config.API_KEY

    if not Config.API_KEY:
        log.warning(
            "No API key configured (AURASENSE_API_KEY / api_key): all endpoints "
            "are OPEN. Use this only for local development."
        )

    _build_services(app)
    log.info(
        "Providers — storage: %s | ai: %s | weather: %s | tts: %s",
        app.storage.name if app.storage else "none",
        Config.AI_PROVIDER, Config.WEATHER_PROVIDER, Config.TTS_PROVIDER,
    )

    app.register_blueprint(voice_bp)
    app.register_blueprint(sensors_bp)
    app.register_blueprint(weather_bp)

    return app


if __name__ == "__main__":
    application = create_app()
    log.info("AuraSense backend starting on port %s", Config.PORT)
    application.run(host="0.0.0.0", port=Config.PORT, debug=Config.DEBUG)
