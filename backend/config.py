"""
config.py — Centralized configuration for the AuraSense backend.
"AuraSense: See the air you breathe."

Settings are read, in order of precedence, from:

1. environment variables (UPPER_CASE names below), then
2. ``config.json`` next to this file (lower_case keys; optional), then
3. built-in defaults.

With no configuration at all the backend starts in **demo mode**: SQLite
storage and offline mock services for AI, weather and text-to-speech, so it
runs without any API key, cloud account or internet connection. Each external
service switches to the real provider when its provider setting says so (see
``.env.example`` and ``docker-compose.gcp.yml``).
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

# ── Load optional config.json ─────────────────────────────────────────────────

_BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.getenv("AURASENSE_CONFIG", os.path.join(_BASE_DIR, "config.json"))

_cfg: dict = {}
if os.path.isfile(_CONFIG_PATH):
    with open(_CONFIG_PATH) as f:
        _cfg = json.load(f)
    log.info("Configuration loaded from %s", _CONFIG_PATH)
else:
    log.info("No config.json found; using environment variables and defaults")


def _get(key: str, default=None):
    """Environment variable (KEY) wins over config.json (key) over default."""
    env = os.getenv(key.upper())
    if env is not None and env != "":
        return env
    return _cfg.get(key, default)


def _get_int(key: str, default: int) -> int:
    return int(_get(key, default))


def _get_bool(key: str, default: bool) -> bool:
    value = _get(key, default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


# ── Config class ──────────────────────────────────────────────────────────────

_GEMINI_KEY      = _get("gemini_api_key", "")
_OPENWEATHER_KEY = _get("openweather_api_key", "")


class Config:
    # ── Providers: "mock" runs offline; the others call external services ─────
    # Defaults follow the available credentials, so an existing config.json
    # with real keys keeps using the real services, and an empty setup runs
    # fully offline. Set a provider explicitly to override.
    STORAGE_BACKEND:  str = _get("storage_backend",  "bigquery" if _get("gcp_project") else "sqlite")
    AI_PROVIDER:      str = _get("ai_provider",      "gemini" if _GEMINI_KEY else "mock")
    WEATHER_PROVIDER: str = _get("weather_provider", "openweather" if _OPENWEATHER_KEY else "mock")
    TTS_PROVIDER:     str = _get("tts_provider",     "edge" if _GEMINI_KEY else "mock")

    # ── Gemini (Google AI) ────────────────────────────────────
    GEMINI_API_KEY: str = _GEMINI_KEY
    GEMINI_MODEL:   str = _get("gemini_model", "gemini-2.5-flash")
    MAX_CONVERSATION_TURNS: int = _get_int("max_conversation_turns", 10)

    # ── Storage ───────────────────────────────────────────────
    SQLITE_PATH:          str = _get("sqlite_path", os.path.join(_BASE_DIR, "data", "aurasense.db"))
    GCP_PROJECT:          str = _get("gcp_project", "")
    GCP_CREDENTIALS_FILE: str = _get("gcp_credentials_file", "")
    BQ_DATASET:           str = _get("bq_dataset", "iot_data")
    BQ_TABLE:             str = _get("bq_table",   "sensor_logs")

    # ── Weather ───────────────────────────────────────────────
    OPENWEATHER_API_KEY: str = _OPENWEATHER_KEY
    FALLBACK_CITY:       str = _get("fallback_city", "Lausanne,CH")
    WEATHER_CACHE_TTL:   int = _get_int("weather_cache_ttl",  600)
    LOCATION_CACHE_TTL:  int = _get_int("location_cache_ttl", 3600)

    # ── AI health advice: minimum seconds between generations (quota guard) ──
    AI_COOLDOWN_SECONDS: int = _get_int("ai_cooldown_seconds", 600)

    # ── API authentication ───────────────────────────────────
    # Shared secret that the device and dashboard send in the X-API-Key header.
    # Empty means "open dev mode" (a warning is logged at startup).
    API_KEY: str = _get("aurasense_api_key", "") or _cfg.get("api_key", "")

    # ── Flask server ──────────────────────────────────────────
    DEBUG: bool = _get_bool("debug", False)
    PORT:  int  = _get_int("port",  5001)


# ── Validate provider choices early, with a clear message ─────────────────────

_REQUIRED_KEYS = {
    ("AI_PROVIDER", "gemini"):           ("GEMINI_API_KEY", Config.GEMINI_API_KEY),
    ("WEATHER_PROVIDER", "openweather"): ("OPENWEATHER_API_KEY", Config.OPENWEATHER_API_KEY),
}
for (setting, provider), (key_name, key_value) in _REQUIRED_KEYS.items():
    if getattr(Config, setting) == provider and not key_value:
        raise RuntimeError(f"{setting}={provider} requires {key_name} to be set.")


# ── Register GCP service-account credentials (BigQuery only) ──────────────────
# On Google Cloud runtimes, Application Default Credentials handle this.

if Config.STORAGE_BACKEND == "bigquery" and Config.GCP_CREDENTIALS_FILE:
    _cred_path = os.path.join(_BASE_DIR, Config.GCP_CREDENTIALS_FILE)
    if os.path.exists(_cred_path):
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = _cred_path
        log.info("GCP credentials bound to %s", _cred_path)
    else:
        log.warning("GCP credentials file not found at %s", _cred_path)
