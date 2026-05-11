"""
services/ai_advice_service.py — Context-aware environmental health advice.

Uses Gemini to generate short, actionable advice based on the current
indoor sensor readings combined with the outdoor weather conditions.
The output is displayed on the Streamlit dashboard and can be announced
by the Core2 device when presence is detected.
"""

from __future__ import annotations

from google import genai
from google.genai import types

from config import Config


_ADVICE_PROMPT = """You are a home environment health advisor.
Given the indoor sensor readings and outdoor conditions below, provide one short,
actionable recommendation (max 20 words) in English.

Focus on: air quality, humidity comfort, temperature, ventilation needs.
Do NOT use Markdown. Be direct and specific."""


class AIAdviceService:
    """Generates health advice from sensor data using Gemini."""

    def __init__(self) -> None:
        self._client = genai.Client(api_key=Config.GEMINI_API_KEY)
        print("[AIAdviceService] Initialised.")

    def generate_advice(
        self,
        indoor_temp:  float | None,
        indoor_hum:   float | None,
        eco2:         int   | None,
        tvoc:         int   | None,
        outdoor_temp: float | None,
        outdoor_desc: str   | None,
    ) -> str:
        """
        Generate a short health recommendation.

        Returns a plain-text string, or a fallback message on error.
        """
        context = self._build_context(
            indoor_temp, indoor_hum, eco2, tvoc, outdoor_temp, outdoor_desc
        )
        prompt = f"{_ADVICE_PROMPT}\n\n{context}"

        try:
            response = self._client.models.generate_content(
                model=Config.GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    # No search tool needed — advice is based on provided data.
                ),
            )
            advice = response.text.strip()
            print(f"[AIAdviceService] Generated: {advice}")
            return advice
        except Exception as exc:
            print(f"[AIAdviceService] ERROR: {exc}")
            return "Unable to generate advice at this time."

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _build_context(
        indoor_temp:  float | None,
        indoor_hum:   float | None,
        eco2:         int   | None,
        tvoc:         int   | None,
        outdoor_temp: float | None,
        outdoor_desc: str   | None,
    ) -> str:
        def fmt(value, unit=""):
            return f"{value}{unit}" if value is not None else "N/A"

        lines = [
            "Indoor conditions:",
            f"  Temperature : {fmt(indoor_temp, ' °C')}",
            f"  Humidity    : {fmt(indoor_hum, ' %')}",
            f"  eCO₂        : {fmt(eco2, ' ppm')}",
            f"  TVOC        : {fmt(tvoc, ' ppb')}",
            "Outdoor conditions:",
            f"  Temperature : {fmt(outdoor_temp, ' °C')}",
            f"  Conditions  : {outdoor_desc or 'N/A'}",
        ]
        return "\n".join(lines)