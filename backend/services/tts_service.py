"""
services/tts_service.py — Text-to-Speech engine for AuraSense.
"AuraSense: See the air you breathe."

Converts the Gemini AI's text replies into a 16 kHz mono 16-bit WAV file 
ready for seamless streaming back to the edge hardware. Utilizes Microsoft 
edge-tts for high-quality, zero-cost neural voice synthesis.
"""

from __future__ import annotations

import asyncio
import io
import re

import edge_tts
from pydub import AudioSegment


# ── Voice map (Language Code → Premium Neural Voice) ──────────────────────────

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

# Output audio specifications (Strictly matched to M5Stack Core2 hardware)
_OUTPUT_RATE         = 16_000   # Hz
_OUTPUT_CHANNELS     = 1        # Mono
_OUTPUT_SAMPLE_WIDTH = 2        # 16-bit


class TTSService:
    """Converts AuraSense AI text replies into hardware-ready WAV audio bytes."""

    def text_to_wav(self, raw_text: str) -> bytes:
        """
        Parses the language tag from the raw AI response, synthesizes the speech, 
        and formats it into a 16kHz WAV byte array.

        Expected input format: "[en] The weather will be sunny tomorrow."
        """
        lang, clean_text = self._parse_reply(raw_text)
        voice            = VOICE_MAP.get(lang, VOICE_MAP["en"])

        print(f"[AuraSense | TTS] Lang: {lang} | Voice: {voice} | Chars: {len(clean_text)}")
        print(f"[AuraSense | TTS] Text: {clean_text[:80]}...")

        # Await the async edge-tts network call
        mp3_bytes = asyncio.run(self._synthesize_mp3(clean_text, voice))

        # Convert and resample the MP3 stream into the strict WAV format
        audio = AudioSegment.from_mp3(io.BytesIO(mp3_bytes))
        audio = (
            audio
            .set_frame_rate(_OUTPUT_RATE)
            .set_channels(_OUTPUT_CHANNELS)
            .set_sample_width(_OUTPUT_SAMPLE_WIDTH)
            .fade_in(50)
            .fade_out(150)  # Gentle fade out to prevent speaker popping
        )

        buf = io.BytesIO()
        audio.export(buf, format="wav")
        wav_bytes = buf.getvalue()
        
        print(f"[AuraSense | TTS] Exported: {len(wav_bytes):,} bytes WAV")
        return wav_bytes

    # ── Private Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _parse_reply(raw: str) -> tuple[str, str]:
        """Extract the [lang] tag from the AI prompt and return (lang_code, clean_text)."""
        match = re.match(r"^\[([a-z]{2})\]\s*(.+)", raw.strip(), re.DOTALL)
        if match:
            return match.group(1), match.group(2).strip()

        # Fallback: Detect language dynamically based on Unicode character blocks
        for ch in raw:
            cp = ord(ch)
            if 0x4E00 <= cp <= 0x9FFF:  return "zh", raw.strip()
            if 0xAC00 <= cp <= 0xD7A3:  return "ko", raw.strip()
            if 0x3040 <= cp <= 0x30FF:  return "ja", raw.strip()
            
        return "en", raw.strip()

    @staticmethod
    async def _synthesize_mp3(text: str, voice: str) -> bytes:
        """Stream raw MP3 audio bytes directly from the Microsoft Edge TTS API."""
        communicate = edge_tts.Communicate(text, voice)
        buf = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf += chunk["data"]
        return buf