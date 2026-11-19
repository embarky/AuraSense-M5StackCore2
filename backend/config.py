"""
config.py — Centralized configuration for the AuraSense backend.
"AuraSense: See the air you breathe."

Sensitive values (API keys, etc.) are stored in config.json (gitignored).
Copy config-example.json to config.json and fill in your specific values.
The device/dashboard API key can also be supplied through the
AURASENSE_API_KEY environment variable, which takes precedence.

The config file is resolved relative to this file's location,
ensuring the application can be launched from any working directory.
"""

import json
import logging
import os

# ── Logging (configured here because config is the first module imported) ────

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
)
log = logging.getLogger("aurasense.config")

# ── Locate and load config.json ───────────────────────────────────────────────

_BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_BASE_DIR, "config.json")

try:
    with open(_CONFIG_PATH) as f:
        _cfg = json.load(f)
    log.info("Configuration loaded from %s", _CONFIG_PATH)
except FileNotFoundError:
    raise RuntimeError(
        f"[AuraSense | Error] Configuration file not found: {_CONFIG_PATH}\n"
        "Please copy config-example.json to config.json and populate your values."
    )


# ── Config class ──────────────────────────────────────────────────────────────

class Config:
    # ── Gemini (Google AI) ────────────────────────────────────
    GEMINI_API_KEY: str = _cfg["gemini_api_key"]
    GEMINI_MODEL:   str = _cfg.get("gemini_model", "gemini-2.5-flash")

    # Maximum conversation turns kept in the voice-assistant history buffer.
    MAX_CONVERSATION_TURNS: int = _cfg.get("max_conversation_turns", 10)

    # ── Google Cloud / BigQuery ───────────────────────────────
    GCP_PROJECT:          str = _cfg.get("gcp_project", "")
    GCP_CREDENTIALS_FILE: str = _cfg.get("gcp_credentials_file", "")
    
    BQ_DATASET:           str = _cfg.get("bq_dataset", "aurasense")
    BQ_TABLE:             str = _cfg.get("bq_table",   "sensor_readings")

    # ── OpenWeatherMap ────────────────────────────────────────
    OPENWEATHER_API_KEY: str = _cfg["openweather_api_key"]
    FALLBACK_CITY:       str = _cfg.get("fallback_city", "Lausanne,CH")

    # ── Cache TTLs (Time-To-Live in seconds) ──────────────────
    WEATHER_CACHE_TTL:  int = _cfg.get("weather_cache_ttl",  600)
    LOCATION_CACHE_TTL: int = _cfg.get("location_cache_ttl", 3600)

    # ── AI Health Advice ──────────────────────────────────────
    # Minimum seconds between consecutive AI advice generations (Quota guard)
    AI_COOLDOWN_SECONDS: int = _cfg.get("ai_cooldown_seconds", 600)

    # ── API authentication ───────────────────────────────────
    # Shared secret that the device and dashboard send in the X-API-Key header.
    # Empty means "open dev mode" (a warning is logged at startup).
    API_KEY: str = os.getenv("AURASENSE_API_KEY") or _cfg.get("api_key", "")

    # ── Flask Server ──────────────────────────────────────────
    DEBUG: bool = _cfg.get("debug", False)
    PORT:  int  = _cfg.get("port",  5001)


# ── Register GCP Service Account Credentials ──────────────────────────────────
# Tells the Google SDK where to find the service account key file.
# This is primarily needed for local development. On a deployed Google Cloud 
# environment (Cloud Run, App Engine), ADC (Application Default Credentials) 
# handles this automatically.

if Config.GCP_CREDENTIALS_FILE:
    _cred_path = os.path.join(_BASE_DIR, Config.GCP_CREDENTIALS_FILE)
    if os.path.exists(_cred_path):
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = _cred_path
        log.info("GCP credentials bound to %s", _cred_path)
    else:
        log.warning("GCP credentials file not found at %s", _cred_path)