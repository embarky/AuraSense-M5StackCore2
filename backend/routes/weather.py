"""
routes/weather.py — Weather API endpoints for AuraSense.
"AuraSense: See the air you breathe."

GET /api/forecast    Returns a 5-day daily aggregated weather forecast.
"""

from __future__ import annotations

import logging

from flask import Blueprint, current_app, jsonify
from security import get_public_client_ip, require_api_key

log = logging.getLogger(__name__)

weather_bp = Blueprint("weather", __name__)


@weather_bp.route("/api/forecast", methods=["GET"])
@require_api_key
def forecast():
    """
    Provides the 5-day aggregated weather forecast for the edge device UI.
    Pipeline: Core2 → GET request → WeatherService (OWM) → JSON Forecast → Core2.
    """
    try:
        # Fetch the service instance attached to the main Flask app
        ws = current_app.weather_service
        
        # Pass the client IP to fetch the localized forecast for the device
        forecast_data = ws.get_forecast(get_public_client_ip())
        
        if not forecast_data:
            log.warning("Forecast data returned empty")
            return jsonify({
                "status": "error",
                "message": "Forecast returned empty."
            }), 500

        return jsonify({
            "status": "success",
            "location": ws.location.get("city", "Unknown"), 
            "forecast": forecast_data
        }), 200

    except Exception:
        log.exception("Forecast request failed")
        return jsonify({"status": "error", "message": "Internal error."}), 500