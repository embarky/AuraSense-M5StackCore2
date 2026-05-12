# pages/home.py — Sensor dashboard (UIFlow2).
#
# Screen layout (320 x 240):
#   y=  0- 20  Status bar (managed by main.py)
#   y= 20-228  Content: two columns of sensor data
#   y=228-240  Alert banner (humidity / CO2 threshold)
#
# Data displayed:
#   Raw        : temperature, humidity, pressure, eCO2, TVOC, motion
#   Calculated : dew point, absolute humidity, comfort level, AQI level
#   Outdoor    : temperature + description (from backend)
#
# feels_like removed — heat index formula only applies above 27°C,
# irrelevant for typical indoor conditions.

import M5
from M5 import *

from components import (
    SCREEN_W, SCREEN_H, STATUS_H,
    C_BG, C_BORDER, C_TEXT, C_MUTED,
    C_GREEN, C_RED, C_ORANGE, C_YELLOW, C_CYAN, C_BLUE,
    draw_status_bar, draw_text, fmt,
    air_color, comfort_color,
)

# Alert thresholds (match backend alert logic)
_HUM_LOW  = 40      # % — too dry
_HUM_HIGH = 70      # % — too humid
_CO2_WARN = 2000    # ppm — poor air quality

# Content area starts just below status bar
_Y0 = STATUS_H + 2

# Column split
_COL_R = 158        # right column x start
_DIV   = 157        # divider x


class HomePage:

    def __init__(self):
        self._data    = {}
        self._outdoor = {}
        self._time    = "--:--"
        self._wifi    = False
        self._flask   = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_enter(self) -> None:
        """Full redraw when navigating to this page."""
        M5.Display.fillScreen(C_BG)
        draw_status_bar(self._time, self._wifi, self._flask)
        self._draw_structure()
        self._draw_data()

    def update(self, sensor_data: dict, outdoor: dict,
               time_str: str, wifi_ok: bool, flask_ok: bool) -> None:
        """Refresh data area only — called every DRAW_INTERVAL."""
        self._data    = sensor_data
        self._outdoor = outdoor
        self._time    = time_str
        self._wifi    = wifi_ok
        self._flask   = flask_ok
        draw_status_bar(time_str, wifi_ok, flask_ok)
        self._draw_data()
        self._draw_alert()

    # ── Static structure (dividers + labels) ──────────────────────────────────

    def _draw_structure(self) -> None:
        """Drawn once on enter — dividers and section labels don't change."""

        # Vertical centre divider
        M5.Display.drawLine(_DIV, STATUS_H, _DIV, SCREEN_H - 12, C_BORDER)

        # Left column horizontal dividers
        M5.Display.drawLine(0,    _Y0 + 72, _DIV, _Y0 + 72, C_BORDER)  # indoor / calc
        M5.Display.drawLine(0,    _Y0 + 122, _DIV, _Y0 + 122, C_BORDER) # calc / outdoor

        # Right column horizontal dividers
        M5.Display.drawLine(_COL_R, _Y0 + 88,  SCREEN_W, _Y0 + 88,  C_BORDER)  # aqi / comfort
        M5.Display.drawLine(_COL_R, _Y0 + 138, SCREEN_W, _Y0 + 138, C_BORDER)  # comfort / motion

        # Section labels
        draw_text("INDOOR",      5,        _Y0,        C_MUTED, C_BG, 1)
        draw_text("CALCULATED",  5,        _Y0 + 76,   C_MUTED, C_BG, 1)
        draw_text("OUTDOOR",     5,        _Y0 + 126,  C_MUTED, C_BG, 1)
        draw_text("AIR QUALITY", _COL_R+4, _Y0,        C_MUTED, C_BG, 1)
        draw_text("COMFORT",     _COL_R+4, _Y0 + 92,   C_MUTED, C_BG, 1)
        draw_text("MOTION",      _COL_R+4, _Y0 + 142,  C_MUTED, C_BG, 1)

    # ── Data (refreshed every DRAW_INTERVAL) ──────────────────────────────────

    def _draw_data(self) -> None:
        self._draw_left()
        self._draw_right()

    def _draw_left(self) -> None:
        d = self._data

        # ── INDOOR ────────────────────────────────────────────────────────────
        # Temperature — large, prominent
        M5.Display.fillRect(0, _Y0 + 12, _DIV, 28, C_BG)
        draw_text(fmt(d.get("temperature"), 1, " C"),
                  4, _Y0 + 14, C_CYAN, C_BG, 2)

        # Humidity + Pressure
        M5.Display.fillRect(0, _Y0 + 42, _DIV, 28, C_BG)
        draw_text("Hum   " + fmt(d.get("humidity"), 1, " %"),
                  4, _Y0 + 44, C_TEXT, C_BG, 1)
        draw_text("Press " + fmt(d.get("pressure"), 0, " hPa"),
                  4, _Y0 + 58, C_TEXT, C_BG, 1)

        # ── CALCULATED ────────────────────────────────────────────────────────
        # Dew point + absolute humidity — meaningful derived values
        M5.Display.fillRect(0, _Y0 + 88, _DIV, 32, C_BG)
        draw_text("Dew    " + fmt(d.get("dew_point"), 1, " C"),
                  4, _Y0 + 90, C_TEXT, C_BG, 1)
        draw_text("AbsHum " + fmt(d.get("absolute_humidity"), 1, " g/m3"),
                  4, _Y0 + 104, C_TEXT, C_BG, 1)

        # ── OUTDOOR ───────────────────────────────────────────────────────────
        M5.Display.fillRect(0, _Y0 + 138, _DIV, 48, C_BG)
        out_t = fmt(self._outdoor.get("outdoor_temp"), 1)
        out_d = str(self._outdoor.get("outdoor_desc", "N/A"))[:14]
        draw_text(out_t + " C",  4, _Y0 + 140, C_TEXT,  C_BG, 1)
        draw_text(out_d,         4, _Y0 + 154, C_MUTED, C_BG, 1)

    def _draw_right(self) -> None:
        d   = self._data
        x   = _COL_R + 4

        # ── AIR QUALITY ───────────────────────────────────────────────────────
        eco2  = d.get("eco2")
        tvoc  = d.get("tvoc")
        level = d.get("air_quality_level", "N/A")
        col   = air_color(level)

        # eCO2 — large value
        M5.Display.fillRect(_COL_R, _Y0 + 12, SCREEN_W - _COL_R, 30, C_BG)
        draw_text(fmt(eco2, 0), x, _Y0 + 14, col, C_BG, 2)
        draw_text("ppm eCO2", x, _Y0 + 36, C_MUTED, C_BG, 1)

        # TVOC
        M5.Display.fillRect(_COL_R, _Y0 + 50, SCREEN_W - _COL_R, 14, C_BG)
        draw_text(fmt(tvoc, 0) + " ppb TVOC", x, _Y0 + 52, C_TEXT, C_BG, 1)

        # AQI colour bar
        bar_w = SCREEN_W - _COL_R - 8
        M5.Display.fillRect(x, _Y0 + 66, bar_w, 6, C_BORDER)
        if eco2:
            fill = min(bar_w, max(3, bar_w * min(eco2, 5000) // 5000))
            M5.Display.fillRect(x, _Y0 + 66, fill, 6, col)

        # AQI label
        M5.Display.fillRect(_COL_R, _Y0 + 74, SCREEN_W - _COL_R, 12, C_BG)
        draw_text(level, x, _Y0 + 75, col, C_BG, 1)

        # ── COMFORT ───────────────────────────────────────────────────────────
        comfort = d.get("comfort_level", "N/A")
        M5.Display.fillRect(_COL_R, _Y0 + 100, SCREEN_W - _COL_R, 36, C_BG)
        draw_text(comfort, x, _Y0 + 102, comfort_color(comfort), C_BG, 1)
        draw_text("Dew " + fmt(d.get("dew_point"), 1, "C"),
                  x, _Y0 + 118, C_MUTED, C_BG, 1)

        # ── MOTION ────────────────────────────────────────────────────────────
        motion = d.get("motion", False)
        m_col  = C_RED if motion else C_GREEN
        M5.Display.fillRect(_COL_R, _Y0 + 150, SCREEN_W - _COL_R, 28, C_BG)
        M5.Display.fillRect(x, _Y0 + 155, 8, 8, m_col)
        draw_text("DETECTED" if motion else "CLEAR",
                  x + 14, _Y0 + 154, m_col, C_BG, 1)

    # ── Alert banner ──────────────────────────────────────────────────────────

    def _draw_alert(self) -> None:
        """Orange strip at bottom if any threshold is exceeded."""
        d   = self._data
        hum = d.get("humidity")
        co2 = d.get("eco2")

        msg = None
        if hum is not None and hum < _HUM_LOW:
            msg = "Low humidity {:.0f}%  consider a humidifier".format(hum)
        elif hum is not None and hum > _HUM_HIGH:
            msg = "High humidity {:.0f}%  ventilate the room".format(hum)
        elif co2 is not None and co2 > _CO2_WARN:
            msg = "Poor air quality {}ppm  open a window".format(co2)

        ay = SCREEN_H - 12
        if msg:
            M5.Display.fillRect(0, ay, SCREEN_W, 12, C_ORANGE)
            draw_text(msg[:52], 4, ay + 2, C_BG, C_ORANGE, 1)
        else:
            M5.Display.fillRect(0, ay, SCREEN_W, 12, C_BG)