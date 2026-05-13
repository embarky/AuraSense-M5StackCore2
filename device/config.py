# config.py — Copy to config.py and fill in your values. Never commit config.py.

WIFI_SSID     = "lmy"
WIFI_PASSWORD = "aaaaaaaa"

SERVER_HOST = "10.76.107.153"
SERVER_PORT = 5001
VOICE_URL   = "http://{}:{}/voice".format(SERVER_HOST, SERVER_PORT)
SENSOR_URL  = "http://{}:{}/api/sensor_data".format(SERVER_HOST, SERVER_PORT)
WEATHER_URL = "http://{}:{}/api/forecast".format(SERVER_HOST, SERVER_PORT)

REC_RATE        = 16000
SPK_VOLUME      = 120
MIC_GAIN        = 5
MAX_REC_SECONDS = 30
HOLD_TO_REC_MS  = 300

UPLOAD_INTERVAL = 5