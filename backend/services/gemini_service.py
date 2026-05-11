"""
services/gemini_service.py — Gemini AI integration.

Responsibilities
----------------
- Accept raw WAV audio bytes and return (transcript, reply) using
  Gemini's native audio understanding (no Whisper required).
- Maintain a rolling multi-turn conversation history so follow-up
  questions work naturally.
- Inject home-sensor context when the user's question is about the
  indoor environment (temperature, humidity, air quality, …).
"""

from __future__ import annotations

import re
from typing import Optional

from google import genai
from google.genai import types

from config import Config


# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are an intelligent home voice assistant with full capability.
You have access to real-time sensor data and historical records from the user's home.

STRICT RULES:
1. First output line MUST be: HEARD: [verbatim transcription of what the user said]
2. Reply in the EXACT same language the user spoke. Never switch languages.
3. MAX 1 sentence. Under 20 words. One key fact only. No dates, no unit conversions.
4. No filler words. No Markdown. No bullet points.
5. Start every reply with a language tag: [en] [fr] [zh] [de] [ja] [ko] …
6. Use Google Search automatically for real-time external information (weather, news …).
7. If a [HOME DATA] block is provided, use it to answer questions about the home."""

# Keywords that trigger sensor-context injection.
_SENSOR_KEYWORDS = {
    "temperature", "humidity", "air quality", "co2", "tvoc", "eco2",
    "yesterday", "last hour", "home", "indoor", "sensor", "reading",
    "温度", "湿度", "空气质量", "昨天", "室内",
    "température", "humidité", "qualité de l'air", "hier",
}


class GeminiService:
    """Stateful wrapper around the Gemini API for the voice-assistant feature."""

    def __init__(self) -> None:
        self._client = genai.Client(api_key=Config.GEMINI_API_KEY)
        self._history: list[types.Content] = []
        print(f"[GeminiService] Initialised — model: {Config.GEMINI_MODEL}")

    # ── Public API ────────────────────────────────────────────────────────────

    def send_audio(
        self,
        wav_data: bytes,
        sensor_context: Optional[str] = None,
    ) -> tuple[str, str]:
        """
        Send WAV audio to Gemini and return (transcript, reply).

        Parameters
        ----------
        wav_data:        Raw WAV file bytes recorded by the Core2.
        sensor_context:  Optional pre-formatted string of recent sensor readings
                         to inject when the question is about the home.
        """
        audio_part = types.Part(
            inline_data=types.Blob(mime_type="audio/wav", data=wav_data)
        )

        # Build a temporary user message with the audio (not stored in history).
        current_message = types.Content(role="user", parts=[audio_part])

        response = self._client.models.generate_content(
            model=Config.GEMINI_MODEL,
            contents=self._history + [current_message],
            config=types.GenerateContentConfig(
                system_instruction=self._build_system_prompt(sensor_context),
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )

        raw         = response.text.strip()
        transcript  = self._extract_heard(raw)
        reply       = self._extract_reply(raw)

        print(f"[GeminiService] HEARD: {transcript}")
        print(f"[GeminiService] REPLY: {reply}")

        # Store TEXT versions in history (storing audio would waste tokens).
        if transcript:
            self._history.append(
                types.Content(role="user",  parts=[types.Part(text=transcript)])
            )
        self._history.append(
            types.Content(role="model", parts=[types.Part(text=reply)])
        )

        self._trim_history()
        return transcript, reply

    def reset_history(self) -> None:
        """Clear the conversation history (called by the /reset endpoint)."""
        self._history.clear()
        print("[GeminiService] Conversation history cleared.")

    @property
    def history_turns(self) -> int:
        """Number of complete conversation turns currently in memory."""
        return len(self._history) // 2

    def needs_sensor_context(self, transcript: str) -> bool:
        """Return True if the transcript seems to ask about home-sensor data."""
        lower = transcript.lower()
        return any(kw in lower for kw in _SENSOR_KEYWORDS)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _build_system_prompt(self, sensor_context: Optional[str]) -> str:
        if not sensor_context:
            return _SYSTEM_PROMPT
        return f"{_SYSTEM_PROMPT}\n\n[HOME DATA]\n{sensor_context}"

    @staticmethod
    def _extract_heard(raw: str) -> str:
        for line in raw.splitlines():
            if line.startswith("HEARD:"):
                return line[6:].strip()
        return ""

    @staticmethod
    def _extract_reply(raw: str) -> str:
        lines = [l for l in raw.splitlines() if l.strip() and not l.startswith("HEARD:")]
        return "\n".join(lines).strip() or raw.strip()

    def _trim_history(self) -> None:
        max_messages = Config.MAX_CONVERSATION_TURNS * 2
        if len(self._history) > max_messages:
            self._history = self._history[-max_messages:]