# config.py — Copy this file to config.py and fill in your values.
# config.py is gitignored and must never be committed.

# ── Network ───────────────────────────────────────────────────
WIFI_SSID     = ""
WIFI_PASSWORD = ""

# ── Backend server ────────────────────────────────────────────
SERVER_HOST  = "192.168.1.xxx"
SERVER_PORT  = 5001
VOICE_URL    = "http://{}:{}/voice".format(SERVER_HOST, SERVER_PORT)
SENSOR_URL   = "http://{}:{}/api/sensor_data".format(SERVER_HOST, SERVER_PORT)

# ── Sensor I2C ports (Core2 PORT.A = SDA:G32 SCL:G33) ────────
I2C_SDA = 32
I2C_SCL = 33
I2C_FREQ = 100000

# ENV3 sensor I2C addresses
SHT30_ADDR  = 0x44    # Temperature & humidity
BMP280_ADDR = 0x76    # Pressure

# Air quality sensor I2C address
SGP30_ADDR  = 0x58    # eCO2 & TVOC

# PIR motion sensor GPIO pin (PORT.B)
PIR_PIN = 36

# ── Audio ─────────────────────────────────────────────────────
REC_RATE        = 16000
SPK_VOLUME      = 120
MIC_GAIN        = 5
MAX_REC_SECONDS = 30
HOLD_TO_REC_MS  = 300

# ── Sensor upload interval (seconds) ─────────────────────────
UPLOAD_INTERVAL = 60