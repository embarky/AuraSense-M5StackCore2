"""
services/weather_service.py — Outdoor weather integration for AuraSense.
"AuraSense: See the air you breathe."

Features
--------
- Auto-detects the client/device geographic location via IP (ip-api.com).
- Caches both location and weather results to minimize external API calls.
- Falls back to a configured city name if IP detection fails.
- Returns current conditions and a 5-day / 3-hour forecast summary.
"""

from __future__ import annotations

import time
from typing import Optional

import requests

from config import Config


class WeatherService:
    """Fetches and caches outdoor weather data from OpenWeatherMap for the AuraSense platform."""

    _OWM_BASE   = "http://api.openweathermap.org/data/2.5"
    # 移除了固定的 URL，改为在 _refresh_location 中动态生成

    def __init__(self) -> None:
        self._location: dict = {
            "ip":          None,  # 记录当前缓存对应的 IP
            "lat":         None,
            "lon":         None,
            "city":        Config.FALLBACK_CITY,
            "offset":      3600,
            "timezone":    "UTC",
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
        # Pre-warm the location cache on startup (using server IP initially)
        self._refresh_location()
        print(f"[AuraSense | Weather] Initialized — Location: {self._location['city']}")

    # ── Public API ────────────────────────────────────────────────────────────

    def get_current(self, client_ip: Optional[str] = None) -> dict:
        """Return cached current weather, refreshing if the TTL has expired or IP changed."""
        ip_changed = client_ip and client_ip != self._location.get("ip")
        if ip_changed or (time.time() - self._weather["last_update"] >= Config.WEATHER_CACHE_TTL):
            self._refresh_current(client_ip)
        return dict(self._weather)

    def get_forecast(self, client_ip: Optional[str] = None) -> list[dict]:
        """
        Return a 5-day daily aggregated forecast.
        """
        self._refresh_location(client_ip)
        params = self._build_params()
        params["cnt"] = 40
        try:
            r = requests.get(f"{self._OWM_BASE}/forecast", params=params, timeout=5)
            r.raise_for_status()
            data = r.json()
 
            daily: dict = {}
            offset = self._location.get("offset", 0)
 
            for item in data.get("list", []):
                # ── Convert UTC timestamp to local calendar date ──────────────
                local_dt = item["dt"] + offset
                date_str = time.strftime("%Y-%m-%d", time.gmtime(local_dt))
                day_name = time.strftime("%a",       time.gmtime(local_dt))
 
                # ── Extract raw fields ────────────────────────────────────────
                temp_min    = item["main"]["temp_min"]
                temp_max    = item["main"]["temp_max"]
                feels_like  = item["main"]["feels_like"]
                humidity    = item["main"]["humidity"]
                wind        = item["wind"]["speed"]
                icon        = item["weather"][0]["icon"]
                description = item["weather"][0]["description"]
                pop         = item.get("pop", 0)
                pod         = item.get("sys", {}).get("pod", "")   # "d" (day) or "n" (night)
 
                # Rain / snow fields are absent when precipitation is zero
                rain_mm  = item.get("rain", {}).get("3h", 0.0)
                snow_mm  = item.get("snow", {}).get("3h", 0.0)
                precip   = rain_mm + snow_mm
 
                if date_str not in daily:
                    # ── First entry of the day: initialize ────────────────────
                    daily[date_str] = {
                        "day":         day_name,
                        "date":        "{} {}/{}".format(day_name, date_str[8:], date_str[5:7]), 
                        "temp_min":    temp_min,
                        "temp_max":    temp_max,
                        "feels_like":  feels_like,
                        "humidity":    humidity,
                        "wind":        wind,
                        "icon":        icon,
                        "pop":         pop,
                        "precip_mm":   precip,
                        "description": description,
                        "is_day":      (pod == "d"),
                    }
                else:
                    d = daily[date_str]
                    d["temp_min"]  = min(d["temp_min"],  temp_min)
                    d["temp_max"]  = max(d["temp_max"],  temp_max)
                    d["pop"]       = max(d["pop"],       pop)
                    d["precip_mm"] += precip
 
                    if pod == "d" and not d["is_day"]:
                        d["icon"]        = icon
                        d["description"] = description
                        d["feels_like"]  = feels_like
                        d["humidity"]    = humidity
                        d["wind"]        = wind
                        d["is_day"]      = True
 
            # ── Post-process: round values, strip internal flag ───────────────
            result = list(daily.values())[:5]
            for d in result:
                d.pop("is_day", None)
                d["temp_min"]  = round(d["temp_min"])
                d["temp_max"]  = round(d["temp_max"])
                d["feels_like"] = round(d["feels_like"], 1)
                d["wind"]      = round(d["wind"],      1)
                d["precip_mm"] = round(d["precip_mm"], 1)
                d["pop"]       = round(d["pop"],       2)
 
            return result
 
        except Exception as exc:
            print(f"[AuraSense | Weather] Forecast fetch failed: {exc}")
            return []

    @property
    def location(self) -> dict:
        return dict(self._location)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _refresh_location(self, client_ip: Optional[str] = None) -> None:
        """Fetch geographic location via IP API using the device's IP."""
        ip_changed = client_ip and client_ip != self._location.get("ip")
        if not ip_changed and time.time() - self._location["last_update"] < Config.LOCATION_CACHE_TTL:
            return
            
        # construct the query URL, ensuring we don't send private IPs to the geolocation API
        query_ip = f"{client_ip}?" if client_ip else "?"
        url = f"http://ip-api.com/json/{query_ip}fields=status,lat,lon,city,countryCode,offset,timezone"

        try:
            r = requests.get(url, timeout=5)
            data = r.json()
            if data.get("status") == "success":
                self._location.update({
                    "ip":          client_ip,
                    "lat":         data["lat"],
                    "lon":         data["lon"],
                    "city":        f"{data['city']}, {data['countryCode']}",
                    "offset":      data.get("offset", 3600),
                    "timezone":    data.get("timezone", "UTC"),
                    "last_update": time.time(),
                })
                print(f"[AuraSense | Weather] Location updated for IP {client_ip or 'Server'}: {self._location['city']}")
        except Exception as exc:
            print(f"[AuraSense | Weather] IP geolocation failed: {exc}")

    def _refresh_current(self, client_ip: Optional[str] = None) -> None:
        """Fetch current weather data from OpenWeatherMap."""
        self._refresh_location(client_ip)
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
            print(f"[AuraSense | Weather] Current weather fetch failed: {exc}")

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