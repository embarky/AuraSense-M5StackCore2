# sensors.py — Sensor drivers (UIFlow2, confirmed pin assignments).
#
# Hardware (confirmed by I2C scan):
#   ENV3 Unit → PORT.C  SCL=G13  SDA=G14  (SoftI2C, 10kHz)
#     SHT30   addr 0x44 — temperature & humidity
#     QMP6988 addr 0x70 — pressure (M5Stack uses QMP6988, not BMP280)
#   SGP30   → PORT.A  SCL=G33  SDA=G32  (SoftI2C)
#     addr 0x58 — eCO2 & TVOC
#   PIR     → PORT.B  GPIO G36

import math
import time
from machine import SoftI2C, Pin


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


# ── QMP6988 — Atmospheric Pressure ───────────────────────────────────────────

class QMP6988:
    """
    QMP6988 barometric pressure sensor.
    M5Stack ENV3 Unit uses QMP6988 (addr 0x70), not BMP280 (0x76/0x77).
    Implements the compensation formula from the QMP6988 datasheet.
    """
    ADDR = 0x70

    def __init__(self, i2c):
        self._i2c = i2c
        # Soft reset
        self._i2c.writeto_mem(self.ADDR, 0xE0, bytes([0xE6]))
        time.sleep_ms(20)
        # Normal mode: temperature ×1, pressure ×8
        self._i2c.writeto_mem(self.ADDR, 0xF3, bytes([0x6D]))
        time.sleep_ms(25)
        # Load OTP calibration coefficients
        self._cal = self._load_cal()

    def _load_cal(self):
        """Read 25 bytes of OTP calibration data from 0xA0."""
        try:
            d = self._i2c.readfrom_mem(self.ADDR, 0xA0, 25)

            def s20(d, i):
                """Extract 20-bit signed int from 3 bytes at index i."""
                v = (d[i] << 12) | (d[i + 1] << 4) | (d[i + 2] >> 4)
                if v >= (1 << 19):
                    v -= (1 << 20)
                return v

            # Calibration coefficients with datasheet scaling factors
            b00  = s20(d,  0) * 3.0
            bt1  = s20(d,  2) * 1.0e-2
            bt2  = s20(d,  4) * 1.0e-4
            bp01 = s20(d,  6) * 1.0e-2
            b11  = s20(d,  8) * 1.0e-4
            bp2  = s20(d, 10) * 1.0e-6
            b12  = s20(d, 12) * 1.0e-8
            b21  = s20(d, 14) * 1.0e-10
            bp3  = s20(d, 16) * 1.0e-12
            print("[QMP6988] Calibration loaded")
            return b00, bt1, bt2, bp01, b11, bp2, b12, b21, bp3
        except Exception as e:
            print("[QMP6988] cal:", e)
            return None

    def read(self):
        """Return pressure in hPa, or None on error."""
        if self._cal is None:
            return None
        try:
            # Read 6 bytes: pressure (F7-F9) + temperature (FA-FC)
            d = self._i2c.readfrom_mem(self.ADDR, 0xF7, 6)

            # Extract 20-bit signed raw values
            raw_p = ((d[0] << 16) | (d[1] << 8) | d[2]) >> 4
            raw_t = ((d[3] << 16) | (d[4] << 8) | d[5]) >> 4
            if raw_p >= (1 << 19): raw_p -= (1 << 20)
            if raw_t >= (1 << 19): raw_t -= (1 << 20)

            b00, bt1, bt2, bp01, b11, bp2, b12, b21, bp3 = self._cal
            dp = float(raw_p)
            dt = float(raw_t)

            # Pressure compensation formula (QMP6988 datasheet section 4.3)
            p = (b00
                 + bp01 * dp
                 + b11  * dp * dt
                 + bp2  * dp * dp
                 + b12  * dp * dt * dt
                 + b21  * dp * dp * dt
                 + bp3  * dp * dp * dp)

            return round(p / 100.0, 1)   # Pa → hPa
        except Exception as e:
            print("[QMP6988]", e)
            return None


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
    """

    def __init__(self):
        # PORT.C: SCL=G13, SDA=G14 (labels swapped vs schematic, confirmed by scan)
        i2c_c = SoftI2C(scl=Pin(13), sda=Pin(14), freq=10000)

        # PORT.A: SCL=G33, SDA=G32
        i2c_a = SoftI2C(scl=Pin(33), sda=Pin(32), freq=100000)

        self._sht = self._try_init(lambda: SHT30(i2c_c),    "SHT30")
        self._qmp = self._try_init(lambda: QMP6988(i2c_c),  "QMP6988")
        self._sgp = self._try_init(lambda: SGP30(i2c_a),    "SGP30")
        self._pir = self._try_init(lambda: PIR(36),          "PIR")
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

        if self._sht:
            temp, hum = self._sht.read()

        if self._qmp:
            pressure = self._qmp.read()

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