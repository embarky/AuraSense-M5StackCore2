"""
services/gemini_service.py — Gemini AI integration for AuraSense.
"AuraSense: See the air you breathe."

Manages conversation history, voice assistant interactions, ambient 
announcements, and critical anomaly alerts using Google's GenAI SDK.
"""

from __future__ import annotations

import re
from typing import Optional

from google import genai
from google.genai import types

from config import Config


_SYSTEM_PROMPT = """You are "AuraSense", an intelligent, premium home climate and air quality assistant.
You have access to real-time sensor telemetry and historical records from the user's space.

STRICT RULES:
1. First output line MUST be: HEARD: [verbatim transcription of what the user said]
2. Reply in the EXACT same language the user spoke. Never switch languages.
3. MAX 1 sentence. Under 20 words. One key fact only. No dates, no unit conversions.
4. No filler words. No Markdown. No bullet points.
5. Start every reply with a language tag: [en] [fr] [zh] [de] [ja] [ko] …
6. Use Google Search automatically for real-time external information (weather, news, etc.).
7. If a [HOME DATA] block is provided, use it to answer questions about the home environment."""

_ANNOUNCE_PROMPT = """You are the voice of AuraSense, a smart home ambient assistant.
Give a brief, elegant spoken update. Speak naturally, like a calm, premium voice assistant.
Two to three sentences maximum. No markdown, no bullet points. Just plain spoken language.
Focus on indoor air quality, temperature comfort, and outdoor weather context."""

_SENSOR_KEYWORDS = {
    "temperature", "humidity", "air quality", "co2", "tvoc", "eco2",
    "yesterday", "last hour", "home", "indoor", "sensor", "reading",
    "温度", "湿度", "空气质量", "昨天", "室内",
    "température", "humidité", "qualité de l'air", "hier",
}


class GeminiService:
    """Handles all interactions with the Gemini LLM for the AuraSense platform."""

    def __init__(self) -> None:
        self._client = genai.Client(api_key=Config.GEMINI_API_KEY)
        self._history: list[types.Content] = []
        print(f"[AuraSense | Gemini] Initialized — Model: {Config.GEMINI_MODEL}")

    # ── Voice Assistant ───────────────────────────────────────────────────────

    def send_audio(
        self,
        wav_data: bytes,
        sensor_context: Optional[str] = None,
    ) -> tuple[str, str]:
        """
        Processes an incoming audio stream, transcribes it, and generates an 
        intelligent contextual response.
        """
        audio_part = types.Part(
            inline_data=types.Blob(mime_type="audio/wav", data=wav_data)
        )
        current_message = types.Content(role="user", parts=[audio_part])

        response = self._client.models.generate_content(
            model=Config.GEMINI_MODEL,
            contents=self._history + [current_message],
            config=types.GenerateContentConfig(
                system_instruction=self._build_system_prompt(sensor_context),
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )

        raw        = response.text.strip()
        transcript = self._extract_heard(raw)
        reply      = self._extract_reply(raw)

        print(f"[AuraSense | Gemini] HEARD: {transcript}")
        print(f"[AuraSense | Gemini] REPLY: {reply}")

        # Maintain conversational memory
        if transcript:
            self._history.append(
                types.Content(role="user", parts=[types.Part(text=transcript)])
            )
        self._history.append(
            types.Content(role="model", parts=[types.Part(text=reply)])
        )

        self._trim_history()
        return transcript, reply

    # ── Announcement Generation ───────────────────────────────────────────────

    def generate_announcement(
        self,
        sensor_data: dict,
        outdoor: dict,
        forecast: list,
    ) -> str:
        """
        Generate a spoken ambient announcement based on current sensor data,
        outdoor weather, and forecast. Called by the /speak route.
        Returns plain text ready for TTS.
        """
        context = self._build_announce_context(sensor_data, outdoor, forecast)

        prompt = (
            "Based on the following AuraSense telemetry, give a brief spoken update "
            "in English. One or two sentences only.\n\n"
            + context
        )

        try:
            response = self._client.models.generate_content(
                model=Config.GEMINI_MODEL,
                contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
                config=types.GenerateContentConfig(
                    system_instruction=_ANNOUNCE_PROMPT,
                ),
            )
            text = response.text.strip()
            print(f"[AuraSense | Gemini] Announcement: {text}")
            return text
        except Exception as exc:
            print(f"[AuraSense | Gemini] Announcement ERROR: {exc}")
            return ""

    def generate_anomaly_alert(
        self,
        sensor_data: dict,
        anomaly_type: str,
    ) -> str:
        """
        Generate an urgent, actionable spoken alert when a severe sensor anomaly is detected.
        anomaly_type: 'co2_danger' | 'co2_warning' | 'humidity_low' | 'humidity_high'
        Returns plain text ready for TTS.
        """
        eco2 = sensor_data.get("eco2", 0) or 0
        tvoc = sensor_data.get("tvoc", 0) or 0
        hum  = sensor_data.get("humidity", 0) or 0
        temp = sensor_data.get("temperature", 0) or 0

        descriptions = {
            "co2_danger":    f"CO2 is critically high at {eco2} ppm",
            "tvoc_danger":   f"TVOC is dangerously high at {tvoc} ppb",
            "humidity_low":  f"Humidity is critically low at {hum}%",
            "humidity_high": f"Humidity is critically high at {hum}%",
        }

        # Support combined anomaly keys (e.g., "co2_danger+tvoc_danger")
        parts = [descriptions.get(k, k) for k in anomaly_type.split("+")]
        situation = ". ".join(parts) + ". Immediate ventilation recommended."

        prompt = (
            f"AuraSense environmental alert: {situation}\n"
            f"Current readings: temperature {temp}°C, humidity {hum}%, "
            f"CO2 {eco2} ppm, TVOC {tvoc} ppb.\n"
            "Give a brief, calm, highly actionable spoken alert. One sentence only."
        )

        try:
            response = self._client.models.generate_content(
                model=Config.GEMINI_MODEL,
                contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
                config=types.GenerateContentConfig(
                    system_instruction=_ANNOUNCE_PROMPT,
                ),
            )
            text = response.text.strip()
            print(f"[AuraSense | Gemini] Alert Generated: {text}")
            return text
        except Exception as exc:
            print(f"[AuraSense | Gemini] Alert ERROR: {exc}")
            return situation  # Graceful fallback to raw description

    # ── Helpers ───────────────────────────────────────────────────────────────

    def reset_history(self) -> None:
        """Clears the conversational context buffer."""
        self._history.clear()
        print("[AuraSense | Gemini] Conversation history cleared.")

    @property
    def history_turns(self) -> int:
        return len(self._history) // 2

    def needs_sensor_context(self, transcript: str) -> bool:
        """Determine if the user's query requires current home telemetry."""
        lower = transcript.lower()
        return any(kw in lower for kw in _SENSOR_KEYWORDS)

    def _build_system_prompt(self, sensor_context: Optional[str]) -> str:
        if not sensor_context:
            return _SYSTEM_PROMPT
        return f"{_SYSTEM_PROMPT}\n\n[HOME DATA]\n{sensor_context}"

    def _build_announce_context(
        self, sensor_data: dict, outdoor: dict, forecast: list
    ) -> str:
        lines = []

        temp = sensor_data.get("temperature")
        hum  = sensor_data.get("humidity")
        eco2 = sensor_data.get("eco2")
        tvoc = sensor_data.get("tvoc")
        comfort = sensor_data.get("comfort_level", "")

        if temp is not None:
            lines.append(f"Indoor temperature: {temp}°C ({comfort})")
        if hum is not None:
            lines.append(f"Indoor humidity: {hum}%")
        if eco2 is not None:
            lines.append(f"CO2: {eco2} ppm")
        if tvoc is not None:
            lines.append(f"TVOC: {tvoc} ppb")

        out_temp = outdoor.get("outdoor_temp")
        out_desc = outdoor.get("outdoor_desc", "")
        if out_temp is not None:
            lines.append(f"Outdoor: {round(out_temp)}°C, {out_desc}")

        # Check if rain is expected today
        if forecast:
            today = forecast[0]
            pop = today.get("pop", 0)
            pop_pct = int(pop * 100) if isinstance(pop, float) and pop <= 1 else int(pop)
            if pop_pct >= 50:
                lines.append(f"Rain expected today: {pop_pct}% chance, {today.get('precip_mm', 0)}mm")

        return "\n".join(lines)

    @staticmethod
    def _extract_heard(raw: str) -> str:
        """Extracts the verbatim transcription from the model's structured output."""
        for line in raw.splitlines():
            if line.startswith("HEARD:"):
                return line[6:].strip()
        return ""

    @staticmethod
    def _extract_reply(raw: str) -> str:
        """Extracts the actual response intended for the TTS engine."""
        lines = [l for l in raw.splitlines() if l.strip() and not l.startswith("HEARD:")]
        return "\n".join(lines).strip() or raw.strip()

    def _trim_history(self) -> None:
        """Prevents the context window from growing indefinitely."""
        max_messages = Config.MAX_CONVERSATION_TURNS * 2
        if len(self._history) > max_messages:
            self._history = self._history[-max_messages:]