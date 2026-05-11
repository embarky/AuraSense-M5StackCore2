"""
services/tts_service.py — Text-to-Speech via Microsoft edge-tts.

Converts Gemini's text reply into a 16 kHz mono 16-bit WAV file ready
for streaming back to the Core2 device.  edge-tts is free, requires no
API key, and works identically on macOS and Linux (server).
"""

from __future__ import annotations

import asyncio
import io
import re

import edge_tts
from pydub import AudioSegment


# ── Voice map (language code → neural voice name) ────────────────────────────

VOICE_MAP: dict[str, str] = {
    "zh": "zh-CN-XiaoxiaoNeural",
    "en": "en-US-JennyNeural",
    "fr": "fr-FR-DeniseNeural",
    "de": "de-DE-KatjaNeural",
    "ja": "ja-JP-NanamiNeural",
    "ko": "ko-KR-SunHiNeural",
    "es": "es-ES-ElviraNeural",
    "it": "it-IT-ElsaNeural",
    "ru": "ru-RU-SvetlanaNeural",
    "pt": "pt-BR-FranciscaNeural",
    "ar": "ar-SA-ZariyahNeural",
}

# Output audio spec (must match Core2 playback expectations).
_OUTPUT_RATE       = 16_000   # Hz
_OUTPUT_CHANNELS   = 1        # mono
_OUTPUT_SAMPLE_WIDTH = 2      # 16-bit


class TTSService:
    """Converts a Gemini reply string (with language tag) into WAV bytes."""

    def text_to_wav(self, raw_text: str) -> bytes:
        """
        Parse the language tag from *raw_text*, synthesise speech, and return
        a 16 kHz mono 16-bit WAV as bytes.

        Expected input format: "[en] The weather will be sunny tomorrow."
        """
        lang, clean_text = self._parse_reply(raw_text)
        voice            = VOICE_MAP.get(lang, VOICE_MAP["en"])

        print(f"[TTSService] lang={lang}  voice={voice}  chars={len(clean_text)}")
        print(f"[TTSService] text={clean_text[:80]}")

        mp3_bytes = asyncio.run(self._synthesise_mp3(clean_text, voice))

        audio = AudioSegment.from_mp3(io.BytesIO(mp3_bytes))
        audio = (
            audio
            .set_frame_rate(_OUTPUT_RATE)
            .set_channels(_OUTPUT_CHANNELS)
            .set_sample_width(_OUTPUT_SAMPLE_WIDTH)
            .fade_in(50)
            .fade_out(150)
        )

        buf = io.BytesIO()
        audio.export(buf, format="wav")
        wav_bytes = buf.getvalue()
        print(f"[TTSService] Output: {len(wav_bytes):,} bytes WAV")
        return wav_bytes

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _parse_reply(raw: str) -> tuple[str, str]:
        """Extract the [lang] tag and return (lang_code, clean_text)."""
        match = re.match(r"^\[([a-z]{2})\]\s*(.+)", raw.strip(), re.DOTALL)
        if match:
            return match.group(1), match.group(2).strip()

        # Fallback: detect language from Unicode block.
        for ch in raw:
            cp = ord(ch)
            if 0x4E00 <= cp <= 0x9FFF:  return "zh", raw.strip()
            if 0xAC00 <= cp <= 0xD7A3:  return "ko", raw.strip()
            if 0x3040 <= cp <= 0x30FF:  return "ja", raw.strip()
        return "en", raw.strip()

    @staticmethod
    async def _synthesise_mp3(text: str, voice: str) -> bytes:
        """Stream MP3 bytes from the edge-tts API (async)."""
        communicate = edge_tts.Communicate(text, voice)
        buf = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf += chunk["data"]
        return buf