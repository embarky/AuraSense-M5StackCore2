"""
Shared fixtures for backend tests.

The backend reads its configuration at import time, so the environment is
fixed here before any backend module is imported: no config.json, offline
mock providers, SQLite storage and a known API key.
"""

import io
import os
import sys
import wave
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND))

os.environ.update(
    AURASENSE_CONFIG="/nonexistent/config.json",
    AURASENSE_API_KEY="test-key",
    STORAGE_BACKEND="sqlite",
    AI_PROVIDER="mock",
    WEATHER_PROVIDER="mock",
    TTS_PROVIDER="mock",
    LOG_LEVEL="WARNING",
)
for var in ("GEMINI_API_KEY", "OPENWEATHER_API_KEY", "GCP_PROJECT"):
    os.environ.pop(var, None)

API_KEY = "test-key"
AUTH = {"X-API-Key": API_KEY}


@pytest.fixture
def app(tmp_path, monkeypatch):
    """A fresh backend in demo mode with its own SQLite file."""
    from config import Config
    from routes import sensors
    from security import limiter

    monkeypatch.setattr(Config, "SQLITE_PATH", str(tmp_path / "test.db"))
    limiter.reset()
    with sensors._state_lock:
        sensors._state.clear()
        sensors._state["ai_advice"] = "AuraSense is initializing..."
    monkeypatch.setattr(sensors, "_last_ai_time", 0.0)

    from app import create_app
    application = create_app()
    application.testing = True
    yield application
    limiter.reset()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def wav_bytes():
    """0.1 s of 16 kHz mono 16-bit silence, as the device records it."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\0\0" * 1600)
    return buf.getvalue()
