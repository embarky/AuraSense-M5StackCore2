# pages/home.py — Main sensor dashboard.
#
# Full content area: y=20 to y=240 (220px), no nav bar.
# Navigation is handled by swipe in main.py.

import M5
from M5 import *

from components import (
    SCREEN_W, SCREEN_H, STATUS_H, CONTENT_Y,
    C_BG, C_BORDER, C_TEXT, C_MUTED,
    C_GREEN, C_RED, C_ORANGE, C_YELLOW, C_CYAN,
    draw_status_bar, draw_text, fmt,
    air_color, comfort_color,
)

_HUM_LOW  = 40
_HUM_HIGH = 70
_CO2_WARN = 2000

# Content starts just below status bar
_Y0 = STATUS_H + 2


class HomePage:

    def __init__(self):
        self._data    = {}
        self._outdoor = {}
        self._time    = "--:--"
        self._wifi    = False
        self._flask   = False

    def on_enter(self) -> None:
        M5.Display.fillScreen(C_BG)
        draw_status_bar(self._time, self._wifi, self._flask)
        self._draw_dividers()
        self._draw_data()

    def update(self, sensor_data: dict, outdoor: dict,
               time_str: str, wifi_ok: bool, flask_ok: bool) -> None:
        self._data    = sensor_data
        self._outdoor = outdoor
        self._time    = time_str
        self._wifi    = wifi_ok
        self._flask   = flask_ok
        draw_status_bar(time_str, wifi_ok, flask_ok)
        self._draw_data()
        self._draw_alert()

    # ── Structure (drawn once on enter) ──────────────────────────────────────

    def _draw_dividers(self) -> None:
        # Vertical centre divider
        M5.Display.drawLine(157, STATUS_H, 157, SCREEN_H, C_BORDER)
        # Horizontal dividers — left column
        for y in (_Y0 + 74, _Y0 + 130):
            M5.Display.drawLine(0, y, 156, y, C_BORDER)
        # Horizontal dividers — right column
        M5.Display.drawLine(158, _Y0 + 90, SCREEN_W, _Y0 + 90, C_BORDER)
        M5.Display.drawLine(158, _Y0 + 140, SCREEN_W, _Y0 + 140, C_BORDER)
        # Section labels (static)
        draw_text("INDOOR",      5,   _Y0,        C_MUTED, C_BG, 1)
        draw_text("CALCULATED",  5,   _Y0 + 78,   C_MUTED, C_BG, 1)
        draw_text("OUTDOOR",     5,   _Y0 + 134,  C_MUTED, C_BG, 1)
        draw_text("AIR QUALITY", 162, _Y0,        C_MUTED, C_BG, 1)
        draw_text("COMFORT",     162, _Y0 + 94,   C_MUTED, C_BG, 1)
        draw_text("MOTION",      162, _Y0 + 144,  C_MUTED, C_BG, 1)

    # ── Data (refreshed every DRAW_INTERVAL) ─────────────────────────────────

    def _draw_data(self) -> None:
        d = self._data
        self._draw_left(d)
        self._draw_right(d)

    def _draw_left(self, d: dict) -> None:
        # ── INDOOR ──
        # Temperature (large)
        M5.Display.fillRect(0, _Y0 + 12, 156, 30, C_BG)
        draw_text(fmt(d.get("temperature"), 1, "C"),
                  5, _Y0 + 14, C_CYAN, C_BG, 2)

        M5.Display.fillRect(0, _Y0 + 44, 156, 28, C_BG)
        draw_text("Hum  " + fmt(d.get("humidity"),  1, "%"),
                  5, _Y0 + 46, C_TEXT, C_BG, 1)
        draw_text("Pres " + fmt(d.get("pressure"), 0, "hPa"),
                  5, _Y0 + 60, C_TEXT, C_BG, 1)

        # ── CALCULATED ──
        M5.Display.fillRect(0, _Y0 + 90, 156, 38, C_BG)
        draw_text("Dew    " + fmt(d.get("dew_point"),         1, "C"),
                  5, _Y0 + 92,  C_TEXT, C_BG, 1)
        draw_text("AbsHum " + fmt(d.get("absolute_humidity"), 1, "g"),
                  5, _Y0 + 106, C_TEXT, C_BG, 1)
        draw_text("Feels  " + fmt(d.get("feels_like"),        1, "C"),
                  5, _Y0 + 120, C_TEXT, C_BG, 1)

        # ── OUTDOOR ──
        M5.Display.fillRect(0, _Y0 + 146, 156, 30, C_BG)
        out_t = fmt(self._outdoor.get("outdoor_temp"))
        out_d = str(self._outdoor.get("outdoor_desc", "--"))[:13]
        draw_text(out_t + "C", 5, _Y0 + 148, C_TEXT, C_BG, 1)
        draw_text(out_d,       5, _Y0 + 162, C_MUTED, C_BG, 1)

    def _draw_right(self, d: dict) -> None:
        eco2  = d.get("eco2")
        tvoc  = d.get("tvoc")
        level = d.get("air_quality_level", "N/A")
        col   = air_color(level)

        # ── AIR QUALITY ──
        # eCO2 value (large)
        M5.Display.fillRect(158, _Y0 + 12, SCREEN_W - 158, 30, C_BG)
        draw_text(fmt(eco2, 0), 162, _Y0 + 14, col, C_BG, 2)
        draw_text("ppm eCO2", 162, _Y0 + 36, C_MUTED, C_BG, 1)

        M5.Display.fillRect(158, _Y0 + 50, SCREEN_W - 158, 38, C_BG)
        draw_text(fmt(tvoc, 0) + " ppb TVOC", 162, _Y0 + 52, C_TEXT, C_BG, 1)

        # AQI bar
        M5.Display.fillRect(162, _Y0 + 66, 148, 7, C_BORDER)
        if eco2:
            bar = min(148, max(3, 148 * min(eco2, 5000) // 5000))
            M5.Display.fillRect(162, _Y0 + 66, bar, 7, col)
        draw_text(level, 162, _Y0 + 76, col, C_BG, 1)

        # ── COMFORT ──
        comfort = d.get("comfort_level", "N/A")
        M5.Display.fillRect(158, _Y0 + 102, SCREEN_W - 158, 36, C_BG)
        draw_text(comfort, 162, _Y0 + 108, comfort_color(comfort), C_BG, 1)
        draw_text("AbsHum " + fmt(d.get("absolute_humidity"), 1, "g/m3"),
                  162, _Y0 + 122, C_MUTED, C_BG, 1)

        # ── MOTION ──
        motion = d.get("motion", False)
        m_col  = C_RED if motion else C_GREEN
        M5.Display.fillRect(158, _Y0 + 148, SCREEN_W - 158, 30, C_BG)
        M5.Display.fillRect(162, _Y0 + 152, 8, 8, m_col)
        draw_text("DETECTED" if motion else "CLEAR",
                  176, _Y0 + 151, m_col, C_BG, 1)

    def _draw_alert(self) -> None:
        d   = self._data
        hum = d.get("humidity")
        co2 = d.get("eco2")
        msg = None
        if hum is not None and hum < _HUM_LOW:
            msg = "Humidity {:.0f}%  use humidifier".format(hum)
        elif hum is not None and hum > _HUM_HIGH:
            msg = "Humidity {:.0f}%  ventilate".format(hum)
        elif co2 is not None and co2 > _CO2_WARN:
            msg = "CO2 {}ppm  open window".format(co2)

        ay = SCREEN_H - 14
        if msg:
            M5.Display.fillRect(0, ay, SCREEN_W, 12, C_ORANGE)
            draw_text(msg[:50], 4, ay + 2, C_BG, C_ORANGE, 1)
        else:
            M5.Display.fillRect(0, ay, SCREEN_W, 12, C_BG)