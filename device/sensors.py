# sensors.py — Sensor drivers (UIFlow2, confirmed pin assignments).
#
# Confirmed by I2C scan:
#   ENV3 (SHT30 + BMP280) → PORT.C  SCL=G13  SDA=G14  (SoftI2C, 10kHz)
#   SGP30 air quality      → PORT.A  SCL=G33  SDA=G32  (hardware I2C)
#   PIR motion sensor      → PORT.B  signal=G36
#
# Note: PORT.C SCL/SDA are swapped vs schematic label —
#       use G13=SCL, G14=SDA as confirmed by scan returning [68, 112].
#
# Addresses found:
#   0x44 (68)  = SHT30  temperature & humidity
#   0x70 (112) = BMP280 pressure  (non-standard address on this unit)
#   0x58 (88)  = SGP30  eCO2 & TVOC

import math
import time
from machine import SoftI2C, I2C, Pin


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


# ── BMP280 — Atmospheric Pressure ────────────────────────────────────────────

class BMP280:
    ADDR = 0x70   # confirmed 0x70 (112) from scan

    def __init__(self, i2c):
        self._i2c = i2c
        self._cal = self._load_cal()

    def _load_cal(self):
        """Read factory calibration coefficients from registers 0x88..0x9F."""
        try:
            d  = self._i2c.readfrom_mem(self.ADDR, 0x88, 24)

            def s(v):
                return v - 65536 if v > 32767 else v

            T1 = d[0]  | d[1]  << 8
            T2 = s(d[2]  | d[3]  << 8)
            T3 = s(d[4]  | d[5]  << 8)
            P1 = d[6]  | d[7]  << 8
            P2 = s(d[8]  | d[9]  << 8)
            P3 = s(d[10] | d[11] << 8)
            P4 = s(d[12] | d[13] << 8)
            P5 = s(d[14] | d[15] << 8)
            P6 = s(d[16] | d[17] << 8)
            P7 = s(d[18] | d[19] << 8)
            P8 = s(d[20] | d[21] << 8)
            P9 = s(d[22] | d[23] << 8)
            return T1, T2, T3, P1, P2, P3, P4, P5, P6, P7, P8, P9
        except Exception as e:
            print("[BMP280] cal:", e)
            return (0,) * 12

    def read(self):
        """Return pressure in hPa, or None on error."""
        try:
            self._i2c.writeto_mem(self.ADDR, 0xF4, bytes([0x27]))
            time.sleep_ms(10)
            d     = self._i2c.readfrom_mem(self.ADDR, 0xF7, 6)
            raw_p = (d[0] << 12) | (d[1] << 4) | (d[2] >> 4)
            raw_t = (d[3] << 12) | (d[4] << 4) | (d[5] >> 4)

            T1, T2, T3, P1, P2, P3, P4, P5, P6, P7, P8, P9 = self._cal
            v1 = (raw_t / 16384 - T1 / 1024) * T2
            v2 = (raw_t / 131072 - T1 / 8388608) ** 2 * T3
            tf = v1 + v2

            v1 = tf / 2 - 64000
            v2 = v1 * v1 * P6 / 32768 + v1 * P5 * 2
            v2 = v2 / 4 + P4 * 65536
            v1 = (P3 * v1 * v1 / 524288 + P2 * v1) / 524288
            v1 = (1 + v1 / 32768) * P1
            if v1 == 0:
                return None
            p  = (1048576 - raw_p - v2 / 4096) * 6250 / v1
            p += (P9 * p * p / 2147483648 + p * P8 / 32768 + P7) / 16
            return round(p / 100, 1)
        except Exception as e:
            print("[BMP280]", e)
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
    """Magnus formula dew point (°C)."""
    a, b  = 17.625, 243.04
    alpha = math.log(h / 100.0) + a * t / (b + t)
    return round(b * alpha / (a - alpha), 1)


def calc_abs_humidity(t: float, h: float) -> float:
    """Absolute humidity in g/m³."""
    return round(
        6.112 * math.exp(17.67 * t / (t + 243.5)) * h * 216.7 / (273.15 + t), 1
    )


def calc_feels_like(t: float, h: float) -> float:
    """Simplified heat index (°C). Returns actual temp below 27°C."""
    if t < 27 or h < 40:
        return t
    return round(
        -8.78469475556
        + 1.61139411    * t
        + 2.33854883889 * h
        - 0.14611605    * t * h
        - 0.012308094   * t ** 2
        - 0.016424828   * h ** 2
        + 0.002211732   * t ** 2 * h
        + 0.00072546    * t * h ** 2
        - 0.000003582   * t ** 2 * h ** 2,
        1,
    )


def calc_comfort(t: float, h: float) -> str:
    if h < 30:                          return "Too Dry"
    if h > 70:                          return "Too Humid"
    if t < 18:                          return "Too Cold"
    if t > 28:                          return "Too Warm"
    if 18 <= t <= 24 and 30 <= h <= 60: return "Comfortable"
    return "Acceptable"


def calc_aqi_level(eco2: int) -> str:
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
        # PORT.C: SCL=G13, SDA=G14 (confirmed by scan — labels are swapped)
        # Use SoftI2C at 10 kHz because G13/G14 are UART pins
        i2c_c = SoftI2C(scl=Pin(13), sda=Pin(14), freq=10000)

        # PORT.A: SCL=G33, SDA=G32 (confirmed, standard hardware I2C)
        i2c_a = I2C(1, scl=Pin(33), sda=Pin(32), freq=100000)

        self._sht = self._try_init(lambda: SHT30(i2c_c),  "SHT30")
        self._bmp = self._try_init(lambda: BMP280(i2c_c), "BMP280")
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
          Raw     : temperature, humidity, pressure, eco2, tvoc, motion
          Derived : dew_point, absolute_humidity, feels_like,
                    comfort_level, air_quality_level
        """
        # ── Raw readings ──────────────────────────────────────
        temp = hum = pressure = None
        if self._sht:
            temp, hum = self._sht.read()
        if self._bmp:
            pressure = self._bmp.read()

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
            data["feels_like"]        = calc_feels_like(temp, hum)
            data["comfort_level"]     = calc_comfort(temp, hum)
        else:
            data["dew_point"]         = None
            data["absolute_humidity"] = None
            data["feels_like"]        = None
            data["comfort_level"]     = "N/A"

        data["air_quality_level"] = (
            calc_aqi_level(eco2) if eco2 is not None else "N/A"
        )

        return data