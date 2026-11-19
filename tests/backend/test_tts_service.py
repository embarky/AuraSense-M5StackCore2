"""The real TTS service must import and process audio on every supported Python.

Python 3.13 removed the audioop module that pydub depends on; audioop-lts
restores it (see backend/requirements.txt). No network or ffmpeg is needed here.
"""

import io
import wave

from pydub import AudioSegment
from services.tts_service import VOICE_MAP, TTSService


def test_language_tag_is_parsed():
    assert TTSService._parse_reply("[fr] Bonjour.") == ("fr", "Bonjour.")
    assert TTSService._parse_reply("你好") == ("zh", "你好")
    assert TTSService._parse_reply("Hello") == ("en", "Hello")
    assert "en" in VOICE_MAP


def test_resampling_to_device_format():
    """The same pydub conversion text_to_wav applies to the synthesised speech."""
    src = AudioSegment.silent(duration=300, frame_rate=24000).set_channels(2)
    out = src.set_frame_rate(16000).set_channels(1).set_sample_width(2).fade_in(50).fade_out(150)
    buf = io.BytesIO()
    out.export(buf, format="wav")
    with wave.open(io.BytesIO(buf.getvalue())) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)
