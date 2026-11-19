"""
services/mock_services.py — Offline stand-ins for the external services.
"AuraSense: See the air you breathe."

Used when a provider is set to "mock" (the default without API keys). They
have the same interface as the real services, need no network, and give
deterministic, plausible output so the full system can be demonstrated and
tested without Gemini, OpenWeatherMap or Edge TTS:

* MockAdviceService  — rule-based advice from the same thresholds as the device
* MockGeminiService  — rule-based voice replies, announcements and alerts
* MockTTSService     — a short two-tone chime WAV (16 kHz mono 16-bit)
* MockWeatherService — a fixed location with a smooth synthetic forecast
"""

from __future__ import annotations

import io
import logging
import math
import struct
import threading
import time
import wave
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import Config

log = logging.getLogger(__name__)

# Thresholds shared with the device LED logic and the dashboard
ECO2_WARN, ECO2_DANGER = 800, 1500
TVOC_WARN, TVOC_DANGER = 220, 660
HUM_LOW_WARN, HUM_HIGH_WARN = 30, 65


def rule_based_advice(indoor_temp=None, indoor_hum=None, eco2=None, tvoc=None,
                      outdoor_temp=None, outdoor_desc=None) -> str:
    """One short, actionable recommendation based on fixed comfort thresholds."""
    if eco2 is not None and eco2 > ECO2_DANGER:
        return f"CO2 is very high ({eco2} ppm): open a window now for 5-10 minutes."
    if tvoc is not None and tvoc > TVOC_DANGER:
        return f"TVOC is very high ({tvoc} ppb): ventilate and check for cooking or cleaning fumes."
    if eco2 is not None and eco2 > ECO2_WARN:
        if outdoor_temp is not None and outdoor_temp < 5:
            return f"CO2 is rising ({eco2} ppm): air the room briefly; it is {round(outdoor_temp)} °C outside."
        return f"CO2 is rising ({eco2} ppm): open a window for a few minutes."
    if indoor_hum is not None and indoor_hum < HUM_LOW_WARN:
        return f"Air is dry ({indoor_hum}%): consider a humidifier or drying laundry indoors."
    if indoor_hum is not None and indoor_hum > HUM_HIGH_WARN:
        return f"Humidity is high ({indoor_hum}%): ventilate to prevent condensation and mould."
    if indoor_temp is not None and indoor_temp > 26:
        return f"It is warm inside ({indoor_temp} °C): ventilate or lower the heating."
    if indoor_temp is not None and indoor_temp < 18:
        return f"It is cool inside ({indoor_temp} °C): close windows and raise the heating."
    return "Air quality and comfort are good. No action needed."


class MockAdviceService:
    def generate_advice(self, **kwargs) -> str:
        return rule_based_advice(**kwargs)


class MockGeminiService:
    """Offline replacement for GeminiService (same public methods)."""

    def __init__(self) -> None:
        self._histories: dict[str, list[str]] = defaultdict(list)
        self._lock = threading.Lock()
        log.info("Mock AI assistant active (no Gemini calls)")

    def send_audio(self, wav_data: bytes, sensor_context: Optional[str] = None,
                   session_id: str = "default") -> tuple[str, str]:
        transcript = "(demo mode: speech recognition is disabled)"
        summary = (sensor_context or "").splitlines()
        detail = summary[1].strip() if len(summary) > 1 else "no recent data yet"
        reply = f"[en] Demo mode. Latest home data: {detail}."
        with self._lock:
            history = self._histories[session_id] + [transcript, reply]
            self._histories[session_id] = history[-Config.MAX_CONVERSATION_TURNS * 2:]
        return transcript, reply

    def generate_announcement(self, sensor_data: dict, outdoor: dict, forecast: list) -> str:
        temp, hum, eco2 = (sensor_data.get(k) for k in ("temperature", "humidity", "eco2"))
        out_temp = outdoor.get("outdoor_temp")
        parts = [f"It is {temp} degrees inside with {hum} percent humidity."]
        if out_temp is not None:
            parts.append(f"Outside it is {round(out_temp)} degrees.")
        parts.append(rule_based_advice(indoor_temp=temp, indoor_hum=hum, eco2=eco2))
        return " ".join(parts)

    def generate_anomaly_alert(self, sensor_data: dict, anomaly_type: str) -> str:
        return rule_based_advice(
            indoor_temp=sensor_data.get("temperature"),
            indoor_hum=sensor_data.get("humidity"),
            eco2=sensor_data.get("eco2"),
            tvoc=sensor_data.get("tvoc"),
        )

    def reset_history(self, session_id: Optional[str] = None) -> None:
        with self._lock:
            if session_id is None:
                self._histories.clear()
            else:
                self._histories.pop(session_id, None)

    @property
    def history_turns(self) -> int:
        with self._lock:
            return sum(len(h) for h in self._histories.values()) // 2


class MockTTSService:
    """Returns a short chime instead of synthesised speech."""

    RATE = 16_000

    def text_to_wav(self, raw_text: str) -> bytes:
        samples = []
        for freq, dur in ((880, 0.15), (660, 0.25)):
            n = int(self.RATE * dur)
            for i in range(n):
                fade = min(1.0, i / 400, (n - i) / 400)
                samples.append(int(9000 * fade * math.sin(2 * math.pi * freq * i / self.RATE)))
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.RATE)
            w.writeframes(struct.pack(f"<{len(samples)}h", *samples))
        return buf.getvalue()


class MockWeatherService:
    """Fixed location with a smooth, time-of-day dependent synthetic weather."""

    _ICONS = [("01d", "clear sky"), ("02d", "few clouds"), ("04d", "broken clouds"),
              ("10d", "light rain"), ("03d", "scattered clouds")]

    def __init__(self) -> None:
        self._location = {
            "ip": None, "lat": 46.52, "lon": 6.63,
            "city": Config.FALLBACK_CITY.replace(",", ", "),
            "timezone": "Europe/Zurich",
            "offset": self._zurich_offset(),
            "last_update": time.time(),
        }
        log.info("Mock weather active for %s", self._location["city"])

    @staticmethod
    def _zurich_offset() -> int:
        try:
            from zoneinfo import ZoneInfo
            return int(datetime.now(ZoneInfo("Europe/Zurich")).utcoffset().total_seconds())
        except Exception:
            return 3600

    @property
    def location(self) -> dict:
        self._location["offset"] = self._zurich_offset()
        return dict(self._location)

    def _temp_at(self, ts: float) -> float:
        hour = (ts / 3600 + self._location["offset"] / 3600) % 24
        day = ts / 86400
        return round(7 + 5 * math.sin((hour - 9) / 24 * 2 * math.pi) + 2 * math.sin(day), 1)

    def get_current(self, client_ip: Optional[str] = None) -> dict:
        now = time.time()
        icon, desc = self._ICONS[int(now // 86400) % len(self._ICONS)]
        temp = self._temp_at(now)
        return {"temp": temp, "feels_like": round(temp - 1.5, 1), "humidity": 72,
                "description": desc, "icon": icon, "last_update": now}

    def get_forecast(self, client_ip: Optional[str] = None) -> list[dict]:
        today = datetime.now(timezone.utc) + timedelta(seconds=self._location["offset"])
        days = []
        for i in range(5):
            d = today + timedelta(days=i)
            icon, desc = self._ICONS[(int(d.timestamp() // 86400)) % len(self._ICONS)]
            base = 7 + 2 * math.sin(d.timestamp() / 86400)
            days.append({
                "day": d.strftime("%a"),
                "date": d.strftime("%a %d/%m"),
                "temp_min": round(base - 4), "temp_max": round(base + 5),
                "feels_like": round(base, 1), "humidity": 70 + i,
                "wind": round(2.5 + i * 0.4, 1), "icon": icon,
                "pop": 0.6 if icon == "10d" else 0.1,
                "precip_mm": 3.2 if icon == "10d" else 0.0,
                "description": desc,
            })
        return days
