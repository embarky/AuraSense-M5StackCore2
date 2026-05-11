# sensors.py — All sensor drivers and derived metric calculations.
#
# Hardware (connected to Core2 PORT.A via I2C):
#   ENVIII Unit  : SHT30  (temp & humidity)  + BMP280 (pressure)
#   Air Quality  : SGP30  (eCO2 & TVOC)
#   Motion       : PIR    (GPIO, PORT.B)
#
# Derived metrics calculated from raw readings:
#   dew_point        — temperature at which air becomes saturated (°C)
#   absolute_humidity — actual water content of air (g/m³)
#   feels_like       — heat index / wind-chill adjusted temperature (°C)
#   comfort_level    — human-readable comfort classification
#   air_quality_level — classification based on eCO2 thresholds

import math
import time
from machine import I2C, Pin

import config


# ── SHT30 — Temperature & Humidity ───────────────────────────────────────────

class SHT30:
    """Driver for the SHT30 sensor (ENV3 Unit)."""

    CMD_MEASURE = bytes([0x2C, 0x06])   # Single-shot, high repeatability

    def __init__(self, i2c: I2C, addr: int = config.SHT30_ADDR) -> None:
        self._i2c = i2c
        self._addr = addr

    def read(self) -> tuple:
        """Return (temperature °C, humidity %) or (None, None) on error."""
        try:
            self._i2c.writeto(self._addr, self.CMD_MEASURE)
            time.sleep_ms(50)
            data = self._i2c.readfrom(self._addr, 6)
            raw_t = (data[0] << 8) | data[1]
            raw_h = (data[3] << 8) | data[4]
            temp  = round(-45 + 175 * raw_t / 65535, 1)
            hum   = round(100 * raw_h / 65535, 1)
            return temp, hum
        except Exception as e:
            print("[SHT30] Read error:", e)
            return None, None


# ── BMP280 — Atmospheric Pressure ────────────────────────────────────────────

class BMP280:
    """Minimal BMP280 driver — returns pressure in hPa."""

    def __init__(self, i2c: I2C, addr: int = config.BMP280_ADDR) -> None:
        self._i2c = i2c
        self._addr = addr
        self._cal  = self._load_calibration()

    def _load_calibration(self) -> tuple:
        """Read factory calibration coefficients (registers 0x88..0x9F)."""
        try:
            d = self._i2c.readfrom_mem(self._addr, 0x88, 24)
            T1 = d[0]  | (d[1]  << 8)
            T2 = d[2]  | (d[3]  << 8); T2 = T2 - 65536 if T2 > 32767 else T2
            T3 = d[4]  | (d[5]  << 8); T3 = T3 - 65536 if T3 > 32767 else T3
            P1 = d[6]  | (d[7]  << 8)
            P2 = d[8]  | (d[9]  << 8); P2 = P2 - 65536 if P2 > 32767 else P2
            P3 = d[10] | (d[11] << 8); P3 = P3 - 65536 if P3 > 32767 else P3
            P4 = d[12] | (d[13] << 8); P4 = P4 - 65536 if P4 > 32767 else P4
            P5 = d[14] | (d[15] << 8); P5 = P5 - 65536 if P5 > 32767 else P5
            P6 = d[16] | (d[17] << 8); P6 = P6 - 65536 if P6 > 32767 else P6
            P7 = d[18] | (d[19] << 8); P7 = P7 - 65536 if P7 > 32767 else P7
            P8 = d[20] | (d[21] << 8); P8 = P8 - 65536 if P8 > 32767 else P8
            P9 = d[22] | (d[23] << 8); P9 = P9 - 65536 if P9 > 32767 else P9
            return T1, T2, T3, P1, P2, P3, P4, P5, P6, P7, P8, P9
        except Exception as e:
            print("[BMP280] Calibration error:", e)
            return (0,) * 12

    def read(self) -> float | None:
        """Return pressure in hPa, or None on error."""
        try:
            # Force measurement: normal mode, oversampling x1
            self._i2c.writeto_mem(self._addr, 0xF4, bytes([0x27]))
            time.sleep_ms(10)
            d = self._i2c.readfrom_mem(self._addr, 0xF7, 6)
            raw_p = (d[0] << 12) | (d[1] << 4) | (d[2] >> 4)
            raw_t = (d[3] << 12) | (d[4] << 4) | (d[5] >> 4)

            T1, T2, T3, P1, P2, P3, P4, P5, P6, P7, P8, P9 = self._cal

            # Temperature compensation (required for pressure calculation)
            v1 = (raw_t / 16384 - T1 / 1024) * T2
            v2 = (raw_t / 131072 - T1 / 8388608) ** 2 * T3
            t_fine = v1 + v2

            # Pressure compensation
            v1 = t_fine / 2 - 64000
            v2 = v1 * v1 * P6 / 32768
            v2 = v2 + v1 * P5 * 2
            v2 = v2 / 4 + P4 * 65536
            v1 = (P3 * v1 * v1 / 524288 + P2 * v1) / 524288
            v1 = (1 + v1 / 32768) * P1
            if v1 == 0:
                return None
            p = 1048576 - raw_p
            p = (p - v2 / 4096) * 6250 / v1
            v1 = P9 * p * p / 2147483648
            v2 = p * P8 / 32768
            p = p + (v1 + v2 + P7) / 16
            return round(p / 100, 1)   # Pa → hPa
        except Exception as e:
            print("[BMP280] Read error:", e)
            return None


# ── SGP30 — eCO2 & TVOC ──────────────────────────────────────────────────────

class SGP30:
    """Driver for the SGP30 air quality sensor."""

    def __init__(self, i2c: I2C, addr: int = config.SGP30_ADDR) -> None:
        self._i2c = i2c
        self._addr = addr
        # Init air quality measurement
        try:
            self._i2c.writeto(self._addr, bytes([0x20, 0x03]))
            time.sleep_ms(10)
        except Exception as e:
            print("[SGP30] Init error:", e)

    def read(self) -> tuple:
        """Return (eCO2 ppm, TVOC ppb) or (None, None) on error."""
        try:
            self._i2c.writeto(self._addr, bytes([0x20, 0x08]))
            time.sleep_ms(12)
            data = self._i2c.readfrom(self._addr, 6)
            eco2 = (data[0] << 8) | data[1]
            tvoc = (data[3] << 8) | data[4]
            return eco2, tvoc
        except Exception as e:
            print("[SGP30] Read error:", e)
            return None, None


# ── PIR — Motion Sensor ───────────────────────────────────────────────────────

class PIR:
    """GPIO-based PIR motion sensor."""

    def __init__(self, pin: int = config.PIR_PIN) -> None:
        self._pin         = Pin(pin, Pin.IN)
        self.last_motion  = 0   # timestamp of last detected motion

    def read(self) -> bool:
        """Return True if motion is currently detected."""
        detected = bool(self._pin.value())
        if detected:
            self.last_motion = time.time()
        return detected


# ── Derived metrics ───────────────────────────────────────────────────────────

def calc_dew_point(temp: float, humidity: float) -> float:
    """
    Magnus formula dew point (°C).
    Accurate to ±0.35°C for 0–60°C range.
    """
    a, b = 17.625, 243.04
    alpha = math.log(humidity / 100) + (a * temp) / (b + temp)
    return round((b * alpha) / (a - alpha), 1)


def calc_absolute_humidity(temp: float, humidity: float) -> float:
    """
    Absolute humidity in g/m³.
    AH = 6.112 * exp(17.67 * T / (T + 243.5)) * RH * 216.7 / (273.15 + T)
    """
    ah = (6.112 * math.exp(17.67 * temp / (temp + 243.5))
          * humidity * 216.7 / (273.15 + temp))
    return round(ah, 2)


def calc_feels_like(temp: float, humidity: float) -> float:
    """
    Simplified heat index (°C). Only meaningful above 27°C.
    Below that, returns actual temperature.
    """
    if temp < 27 or humidity < 40:
        return temp
    hi = (-8.78469475556
          + 1.61139411    * temp
          + 2.33854883889 * humidity
          - 0.14611605    * temp * humidity
          - 0.012308094   * temp ** 2
          - 0.016424828   * humidity ** 2
          + 0.002211732   * temp ** 2 * humidity
          + 0.00072546    * temp * humidity ** 2
          - 0.000003582   * temp ** 2 * humidity ** 2)
    return round(hi, 1)


def calc_comfort_level(temp: float, humidity: float) -> str:
    """
    Classify indoor comfort based on temperature and humidity.
    Returns a short human-readable label.
    """
    if humidity < 30:
        return "Too Dry"
    if humidity > 70:
        return "Too Humid"
    if temp < 18:
        return "Too Cold"
    if temp > 28:
        return "Too Warm"
    if 18 <= temp <= 24 and 30 <= humidity <= 60:
        return "Comfortable"
    return "Acceptable"


def calc_air_quality_level(eco2: int) -> str:
    """
    Classify air quality from eCO2 concentration (ppm).
    Thresholds based on ASHRAE / WHO guidelines.
    """
    if eco2 < 400:   return "Excellent"
    if eco2 < 1000:  return "Good"
    if eco2 < 2000:  return "Moderate"
    if eco2 < 5000:  return "Poor"
    return "Hazardous"


# ── SensorHub — unified interface ─────────────────────────────────────────────

class SensorHub:
    """
    Reads all sensors and returns a single flat dict with raw + derived values.
    Instantiate once in main.py and call read_all() in the main loop.
    """

    def __init__(self) -> None:
        i2c       = I2C(1, scl=Pin(config.I2C_SCL),
                           sda=Pin(config.I2C_SDA),
                           freq=config.I2C_FREQ)
        self._sht = SHT30(i2c)
        self._bmp = BMP280(i2c)
        self._sgp = SGP30(i2c)
        self._pir = PIR()
        print("[SensorHub] Initialised")

    def read_all(self) -> dict:
        """
        Returns a dict containing:
          Raw    : temperature, humidity, pressure, eco2, tvoc, motion
          Derived: dew_point, absolute_humidity, feels_like,
                   comfort_level, air_quality_level
        """
        temp, hum  = self._sht.read()
        pressure   = self._bmp.read()
        eco2, tvoc = self._sgp.read()
        motion     = self._pir.read()

        data: dict = {
            # ── Raw readings ──────────────────────────────────
            "temperature":  temp,
            "humidity":     hum,
            "pressure":     pressure,
            "eco2":         eco2,
            "tvoc":         tvoc,
            "motion":       motion,
        }

        # ── Derived metrics (only when raw data is available) ─
        if temp is not None and hum is not None:
            data["dew_point"]         = calc_dew_point(temp, hum)
            data["absolute_humidity"] = calc_absolute_humidity(temp, hum)
            data["feels_like"]        = calc_feels_like(temp, hum)
            data["comfort_level"]     = calc_comfort_level(temp, hum)
        else:
            data["dew_point"]         = None
            data["absolute_humidity"] = None
            data["feels_like"]        = None
            data["comfort_level"]     = "N/A"

        if eco2 is not None:
            data["air_quality_level"] = calc_air_quality_level(eco2)
        else:
            data["air_quality_level"] = "N/A"

        return data