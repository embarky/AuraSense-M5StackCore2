# config.example.py — AuraSense hardware configuration template.
# "AuraSense: See the air you breathe."
#
# Copy this file to config.py (same folder) and fill in your values.
# config.py is gitignored: never commit real WiFi credentials or API keys.

WIFI_SSID     = ""
WIFI_PASSWORD = ""

# Backend server (use HTTPS behind a reverse proxy for any public deployment)
SERVER_HOST = "192.168.1.xxx"
SERVER_PORT = 5001
VOICE_URL   = "http://{}:{}/voice".format(SERVER_HOST, SERVER_PORT)
SENSOR_URL  = "http://{}:{}/api/sensor_data".format(SERVER_HOST, SERVER_PORT)
WEATHER_URL = "http://{}:{}/api/forecast".format(SERVER_HOST, SERVER_PORT)

# Must match AURASENSE_API_KEY on the backend (sent as the X-API-Key header)
API_KEY   = ""
# Identifies this device; the backend keeps one conversation history per device
DEVICE_ID = "core2-01"

# Fallback offset from UTC in seconds, used until the backend reports the
# real DST-aware offset (3600 = CET winter time, 7200 = CEST summer time)
UTC_OFFSET_S = 3600

REC_RATE        = 16000
SPK_VOLUME      = 120
MIC_GAIN        = 5
MAX_REC_SECONDS = 30
HOLD_TO_REC_MS  = 300

UPLOAD_INTERVAL = 5
