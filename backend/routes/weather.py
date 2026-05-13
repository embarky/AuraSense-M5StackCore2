"""
routes/weather.py — Weather API endpoints.

GET /weather    Returns a 5-day daily aggregated weather forecast.
"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify

weather_bp = Blueprint("weather", __name__)


@weather_bp.route("/api/forecast", methods=["GET"])
def forecast():
    """
    Core2 → GET Request → weather_service (OWM) → JSON Forecast → Core2.
    
    Returns the 5-day / daily aggregated forecast to be displayed on the
    M5Stack accordion UI.
    """
    try:
        # Fetch the service instance attached to the main Flask app
        ws = current_app.weather_service
        
        # Get the aggregated 5-day list
        forecast_data = ws.get_forecast()
        
        if not forecast_data:
            return jsonify({
                "status": "error",
                "message": "Forecast returned empty."
            }), 500

        return jsonify({
            "status": "success",
            "forecast": forecast_data
        })

    except Exception as exc:
        import traceback
        traceback.print_exc()
        return jsonify({
            "status": "error",
            "message": f"Internal error: {exc}"
        }), 500