"""
routes/weather.py — Weather API endpoints for AuraSense.
"AuraSense: See the air you breathe."

GET /api/forecast    Returns a 5-day daily aggregated weather forecast.
"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

weather_bp = Blueprint("weather", __name__)


@weather_bp.route("/api/forecast", methods=["GET"])
def forecast():
    """
    Provides the 5-day aggregated weather forecast for the edge device UI.
    Pipeline: Core2 → GET Request → WeatherService (OWM) → JSON Forecast → Core2.
    """
    try:
        # Fetch the service instance attached to the main Flask app
        ws = current_app.weather_service
        
        # ── Extract real client IP (handles reverse proxies like Nginx) ──
        client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        if client_ip:
            client_ip = client_ip.split(',')[0].strip()
        
        # Pass the client IP to fetch the localized forecast for the device
        forecast_data = ws.get_forecast(client_ip)
        
        if not forecast_data:
            print("[AuraSense | Weather API] WARNING: Forecast data returned empty.")
            return jsonify({
                "status": "error",
                "message": "Forecast returned empty."
            }), 500

        return jsonify({
            "status": "success",
            "forecast": forecast_data
        }), 200

    except Exception as exc:
        import traceback
        print(f"[AuraSense | Weather API] ERROR: {exc}")
        traceback.print_exc()
        return jsonify({
            "status": "error",
            "message": f"Internal error: {exc}"
        }), 500