"""
config.py — Centralized configuration for the AuraSense backend.
"AuraSense: See the air you breathe."

Sensitive values (API keys, etc.) are stored in config.json (gitignored).
Copy config.example.json to config.json and fill in your specific values.

The config file is resolved relative to this file's location,
ensuring the application can be launched from any working directory.
"""

import json
import os

# ── Locate and load config.json ───────────────────────────────────────────────

_BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_BASE_DIR, "config.json")

try:
    with open(_CONFIG_PATH) as f:
        _cfg = json.load(f)
    print(f"[AuraSense | Config] Successfully loaded from {_CONFIG_PATH}")
except FileNotFoundError:
    raise RuntimeError(
        f"[AuraSense | Error] Configuration file not found: {_CONFIG_PATH}\n"
        "Please copy config.example.json to config.json and populate your values."
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
    
    # Updated default dataset name to reflect the new AuraSense branding
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
        print(f"[AuraSense | Config] GCP credentials bound to: {_cred_path}")
    else:
        print(f"[AuraSense | Warning] GCP credentials file not found at: {_cred_path}")