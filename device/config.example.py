# config.py — Copy to config.py and fill in your values. Never commit config.py.

WIFI_SSID     = ""
WIFI_PASSWORD = ""

SERVER_HOST = "192.168.1.xxx"
SERVER_PORT = 5001
VOICE_URL   = "http://{}:{}/voice".format(SERVER_HOST, SERVER_PORT)
SENSOR_URL  = "http://{}:{}/api/sensor_data".format(SERVER_HOST, SERVER_PORT)

REC_RATE        = 16000
SPK_VOLUME      = 120
MIC_GAIN        = 5
MAX_REC_SECONDS = 30
HOLD_TO_REC_MS  = 300

UPLOAD_INTERVAL = 5