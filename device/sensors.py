# sensors.py — Sensor drivers (UIFlow2, confirmed pin assignments).
#
# Hardware (confirmed by I2C scan):
#   ENV3 Unit → PORT.C  SCL=G13  SDA=G14
#     SHT30   addr 0x44 — temperature & humidity  } both via ENVUnit
#     QMP6988 addr 0x70 — pressure                } hardware.I2C(1)
#   SGP30   → PORT.A  SCL=G33  SDA=G32  (SoftI2C)
#     addr 0x58 — eCO2 & TVOC
#   PIR     → PORT.B  GPIO G36

import math
import time
from machine import SoftI2C, Pin
from hardware import I2C
from unit import ENVUnit


# ── SHT30 — Temperature & Humidity ───────────────────────────────────────────

class SHT30:
    ADDR = 0x44
    CMD  = bytes([0x2C, 0x06])   # single-shot, high repeatability

    def __init__(self, i2c):
        self._i2c = i2c

    def read(self):
        """Return (temperature °C, humidity %) or (None, None) on error."""
        try:
            self._i2c.writeto(self.ADDR, self.CMD)
            time.sleep_ms(50)
            d    = self._i2c.readfrom(self.ADDR, 6)
            temp = round(-45 + 175 * ((d[0] << 8 | d[1]) / 65535.0), 1)
            hum  = round(100 * (d[3] << 8 | d[4]) / 65535.0, 1)
            return temp, hum
        except Exception as e:
            print("[SHT30]", e)
            return None, None


# ── QMP6988 — Atmospheric Pressure via ENVUnit ───────────────────────────────

class QMP6988:
    """
    QMP6988 + SHT30 via ENVUnit official driver on hardware.I2C(1).
    SoftI2C and hardware.I2C cannot share the same bus — ENVUnit takes over PORT.C.
    Tested working: I2C(1, scl=13, sda=14) + ENVUnit(i2c, type=3).
    """
    def __init__(self):
        i2c = I2C(0, scl=13, sda=14, freq=10000)
        time.sleep_ms(200)
        self._env = ENVUnit(i2c=i2c, type=3)
        print("[QMP6988] ENVUnit OK")

    def read(self):
        """Return pressure in hPa, or None on error."""
        try:
            return round(self._env.read_pressure(), 1)
        except Exception as e:
            print("[QMP6988]", e)
            return None

    def read_th(self):
        """Return (temperature °C, humidity %) from ENVUnit, or (None, None)."""
        try:
            temp = round(self._env.read_temperature(), 1)
            hum  = round(self._env.read_humidity(), 1)
            return temp, hum
        except Exception as e:
            print("[QMP6988] TH:", e)
            return None, None


# ── SGP30 — eCO2 & TVOC ──────────────────────────────────────────────────────

class SGP30:
    ADDR = 0x58

    def __init__(self, i2c):
        self._i2c = i2c
        try:
            self._i2c.writeto(self.ADDR, b'\x20\x03')
            time.sleep_ms(10)
        except Exception as e:
            print("[SGP30] init:", e)

    def read(self):
        """Return (eco2 ppm, tvoc ppb). Returns (400, 0) on error."""
        try:
            self._i2c.writeto(self.ADDR, b'\x20\x08')
            time.sleep_ms(20)
            d    = self._i2c.readfrom(self.ADDR, 6)
            eco2 = max(400, (d[0] << 8) | d[1])
            tvoc = (d[3] << 8) | d[4]
            return eco2, tvoc
        except Exception as e:
            print("[SGP30]", e)
            return 400, 0


# ── PIR — Motion Sensor ───────────────────────────────────────────────────────

class PIR:
    def __init__(self, pin: int = 36):
        self._pin = Pin(pin, Pin.IN)

    def read(self) -> bool:
        try:
            return bool(self._pin.value())
        except Exception:
            return False


# ── Derived metric calculations ───────────────────────────────────────────────

def calc_dew_point(t: float, h: float) -> float:
    """Magnus formula dew point (°C). Accurate ±0.35°C for 0–60°C."""
    a, b  = 17.625, 243.04
    alpha = math.log(h / 100.0) + a * t / (b + t)
    return round(b * alpha / (a - alpha), 1)


def calc_abs_humidity(t: float, h: float) -> float:
    """Absolute humidity in g/m³."""
    return round(
        6.112 * math.exp(17.67 * t / (t + 243.5)) * h * 216.7 / (273.15 + t), 1
    )


def calc_comfort(t: float, h: float) -> str:
    """Human comfort classification from temperature and humidity."""
    if h < 30:                          return "Too Dry"
    if h > 70:                          return "Too Humid"
    if t < 18:                          return "Too Cold"
    if t > 28:                          return "Too Warm"
    if 18 <= t <= 24 and 30 <= h <= 60: return "Comfortable"
    return "Acceptable"


def calc_aqi_level(eco2: int) -> str:
    """Air quality classification from eCO2 concentration (ppm)."""
    if eco2 < 600:   return "Excellent"
    if eco2 < 1000:  return "Good"
    if eco2 < 2000:  return "Moderate"
    if eco2 < 5000:  return "Poor"
    return "Hazardous"


# ── SensorHub — unified interface ─────────────────────────────────────────────

class SensorHub:
    """
    Reads all sensors and returns a flat dict with raw + derived values.
    Instantiate once at startup, call read_all() in the main loop.
    PORT.C exclusively uses hardware.I2C via ENVUnit (no SoftI2C on same bus).
    """

    def __init__(self):
        # PORT.A: SCL=G33, SDA=G32 for SGP30 only
        i2c_a = SoftI2C(scl=Pin(33), sda=Pin(32), freq=100000)

        # PORT.C: exclusively via ENVUnit (handles both SHT30 + QMP6988)
        self._qmp = self._try_init(lambda: QMP6988(),      "QMP6988")
        self._sgp = self._try_init(lambda: SGP30(i2c_a),  "SGP30")
        self._pir = self._try_init(lambda: PIR(36),        "PIR")
        print("[SensorHub] Ready")

    @staticmethod
    def _try_init(factory, name):
        try:
            obj = factory()
            print("[SensorHub]", name, "OK")
            return obj
        except Exception as e:
            print("[SensorHub]", name, "FAILED:", e)
            return None

    def read_all(self) -> dict:
        """
        Returns a dict with:
          Raw      : temperature, humidity, pressure, eco2, tvoc, motion
          Derived  : dew_point, absolute_humidity, comfort_level, air_quality_level
          Removed  : feels_like (heat index only valid >27°C, irrelevant indoors)
        """
        # ── Raw readings ──────────────────────────────────────
        temp = hum = pressure = None

        if self._qmp:
            temp, hum = self._qmp.read_th()
            pressure  = self._qmp.read()

        eco2 = tvoc = None
        if self._sgp:
            eco2, tvoc = self._sgp.read()

        motion = self._pir.read() if self._pir else False

        data = {
            "temperature": temp,
            "humidity":    hum,
            "pressure":    pressure,
            "eco2":        eco2,
            "tvoc":        tvoc,
            "motion":      motion,
        }

        # ── Derived metrics ───────────────────────────────────
        if temp is not None and hum is not None and hum > 0:
            data["dew_point"]         = calc_dew_point(temp, hum)
            data["absolute_humidity"] = calc_abs_humidity(temp, hum)
            data["comfort_level"]     = calc_comfort(temp, hum)
        else:
            data["dew_point"]         = None
            data["absolute_humidity"] = None
            data["comfort_level"]     = "N/A"

        data["air_quality_level"] = (
            calc_aqi_level(eco2) if eco2 is not None else "N/A"
        )

        return data