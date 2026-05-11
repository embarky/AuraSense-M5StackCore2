"""
services/weather_service.py — Outdoor weather via OpenWeatherMap.

Features
--------
- Auto-detects the server's geographic location via IP (ip-api.com).
- Caches both location and weather results to minimise external API calls.
- Falls back to a configured city name if IP detection fails.
- Returns current conditions and a 5-day / 3-hour forecast.
"""

from __future__ import annotations

import time
from typing import Optional

import requests

from config import Config


class WeatherService:
    """Fetches and caches outdoor weather data from OpenWeatherMap."""

    _OWM_BASE   = "http://api.openweathermap.org/data/2.5"
    _IP_API_URL = "http://ip-api.com/json/?fields=status,lat,lon,city,countryCode,offset,timezone"

    def __init__(self) -> None:
        self._location: dict = {
            "lat":        None,
            "lon":        None,
            "city":       Config.FALLBACK_CITY,
            "offset":     3600,
            "timezone":   "UTC",
            "last_update": 0,
        }
        self._weather: dict = {
            "temp":        None,
            "feels_like":  None,
            "humidity":    None,
            "description": None,
            "icon":        None,
            "last_update": 0,
        }
        # Pre-warm location cache on startup.
        self._refresh_location()
        print(f"[WeatherService] Initialised — location: {self._location['city']}")

    # ── Public API ────────────────────────────────────────────────────────────

    def get_current(self) -> dict:
        """Return cached current weather, refreshing if TTL has expired."""
        if time.time() - self._weather["last_update"] >= Config.WEATHER_CACHE_TTL:
            self._refresh_current()
        return dict(self._weather)

    def get_forecast(self) -> list[dict]:
        """
        Return the next 5-day / 3-hour forecast (40 data points).
        Results are NOT cached individually — call sparingly.
        """
        self._refresh_location()
        params = self._build_params()
        params["cnt"] = 40
        try:
            r = requests.get(f"{self._OWM_BASE}/forecast", params=params, timeout=5)
            r.raise_for_status()
            data = r.json()
            return [
                {
                    "dt":          item["dt"],
                    "temp":        item["main"]["temp"],
                    "description": item["weather"][0]["description"],
                    "icon":        item["weather"][0]["icon"],
                    "pop":         item.get("pop", 0),        # precipitation probability
                }
                for item in data.get("list", [])
            ]
        except Exception as exc:
            print(f"[WeatherService] Forecast fetch failed: {exc}")
            return []

    @property
    def location(self) -> dict:
        return dict(self._location)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _refresh_location(self) -> None:
        if time.time() - self._location["last_update"] < Config.LOCATION_CACHE_TTL:
            return
        try:
            r = requests.get(self._IP_API_URL, timeout=5)
            data = r.json()
            if data.get("status") == "success":
                self._location.update({
                    "lat":        data["lat"],
                    "lon":        data["lon"],
                    "city":       f"{data['city']}, {data['countryCode']}",
                    "offset":     data.get("offset", 3600),
                    "timezone":   data.get("timezone", "UTC"),
                    "last_update": time.time(),
                })
                print(f"[WeatherService] Location updated: {self._location['city']}")
        except Exception as exc:
            print(f"[WeatherService] IP geolocation failed: {exc}")

    def _refresh_current(self) -> None:
        self._refresh_location()
        try:
            r = requests.get(
                f"{self._OWM_BASE}/weather",
                params=self._build_params(),
                timeout=5,
            )
            r.raise_for_status()
            data = r.json()
            self._weather.update({
                "temp":        data["main"]["temp"],
                "feels_like":  data["main"]["feels_like"],
                "humidity":    data["main"]["humidity"],
                "description": data["weather"][0]["description"],
                "icon":        data["weather"][0]["icon"],
                "last_update": time.time(),
            })
        except Exception as exc:
            print(f"[WeatherService] Current weather fetch failed: {exc}")

    def _build_params(self) -> dict:
        """Build the OWM query parameters, preferring lat/lon over city name."""
        params = {
            "appid": Config.OPENWEATHER_API_KEY,
            "units": "metric",
        }
        if self._location["lat"] is not None:
            params["lat"] = self._location["lat"]
            params["lon"] = self._location["lon"]
        else:
            params["q"] = self._location["city"]
        return params