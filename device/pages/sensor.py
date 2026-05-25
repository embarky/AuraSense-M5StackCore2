# pages/sensor.py — Sensor diagnostic readings for AuraSense.
# "AuraSense: See the air you breathe."

import M5
from M5 import *

from components import (
    SCREEN_W, SCREEN_H, STATUS_H,
    C_BG, C_BORDER, C_TEXT, C_MUTED, C_CYAN,
    C_GREEN, C_RED, C_ORANGE, C_BLUE,
    draw_status_bar, draw_text, fmt,
    air_color, comfort_color,
)

# ── Layout Configuration ──────────────────────────────────────────────────────
_COL_L  = 0      # Left column X coordinate
_COL_R  = 160    # Right column X coordinate 
_COL_W  = 160    # Width of each column
_LH     = 18     # Restore to normal line height for font size 1
_SH     = 16     # Section Header height
_Y0     = STATUS_H + 24  # Push everything down to leave space for the top title
_LBL    = 6      # X offset for labels
_VAL    = 66     # X offset for values 
_VAL_W  = 94     # Width of the value clearing rectangle


class SensorPage:

    def __init__(self):
        self._data  = {}
        self._time  = "--:--"
        self._wifi  = False
        self._flask = False
        self._drawn = False   # Tracks if the static structure is already drawn

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_enter(self) -> None:
        M5.Display.fillScreen(C_BG)
        draw_status_bar(self._time, self._wifi, self._flask)
        self._draw_structure()
        self._draw_values()
        self._drawn = True

    def update(self, sensor_data: dict, outdoor: dict,
               time_str: str, wifi_ok: bool, flask_ok: bool) -> None:
        self._data  = sensor_data
        self._time  = time_str
        self._wifi  = wifi_ok
        self._flask = flask_ok
        
        draw_status_bar(time_str, wifi_ok, flask_ok)
        
        if not self._drawn:
            self._draw_structure()
            self._drawn = True
            
        self._draw_values()

    # ── Static Structure (labels + dividers, drawn once) ──────────────────────

    def _draw_structure(self) -> None:
        # --- Page Header ---
        draw_text("AuraSense DIAGNOSTICS", _LBL, STATUS_H + 4, C_ORANGE, C_BG, 1)
        M5.Display.drawLine(0, STATUS_H + 18, SCREEN_W, STATUS_H + 18, C_BORDER)

        y = _Y0

        # --- Left Column ---
        self._section_title("SHT30", _COL_L, y);      y_sht = y + _SH
        self._label("Temp",   _COL_L, y_sht)          
        self._label("Hum",    _COL_L, y_sht + _LH)

        y_bmp = y_sht + _LH * 2 + 4
        self._section_title("QMP6988", _COL_L, y_bmp) # Adjusted header based on active driver
        self._label("Press",  _COL_L, y_bmp + _SH)

        # --- Right Column ---
        y = _Y0
        self._section_title("SGP30", _COL_R, y);      y_sgp = y + _SH
        self._label("eCO2",   _COL_R, y_sgp)
        self._label("TVOC",   _COL_R, y_sgp + _LH)

        y_pir = y_sgp + _LH * 2 + 4
        self._section_title("PIR",   _COL_R, y_pir)
        self._label("Motion", _COL_R, y_pir + _SH)

        # --- Calculated Section ---
        y_calc = _Y0 + _SH + _LH * 2 + 4 + _SH + _LH + 8
        
        # Horizontal divider
        M5.Display.drawLine(0, y_calc, SCREEN_W, y_calc, C_BORDER)
        y_calc += 6
        self._section_title("CALCULATED", _COL_L, y_calc, C_BLUE)
        y_calc += _SH + 4
        
        self._label("Dew Pt",  _COL_L, y_calc)
        self._label("Abs Hum", _COL_R, y_calc)
        self._label("Comfort", _COL_L, y_calc + _LH)
        self._label("Air Q.",  _COL_R, y_calc + _LH)

        # Vertical divider (top section only)
        M5.Display.drawLine(158, _Y0, 158, 
                            _Y0 + _SH + _LH * 2 + 4 + _SH + _LH + 2, 
                            C_BORDER)

        # Store y_calc for value drawing loop
        self._y_calc = y_calc 

    def _section_title(self, text: str, col_x: int, y: int, color=C_ORANGE) -> None:
        draw_text(text, col_x + _LBL, y, color, C_BG, 1)

    def _label(self, text: str, col_x: int, y: int) -> None:
        draw_text(text, col_x + _LBL, y, C_MUTED, C_BG, 1)

    # ── Values (cleared and redrawn every update) ─────────────────────────────

    def _draw_values(self) -> None:
        d = self._data

        y_sht = _Y0 + _SH
        y_bmp = y_sht + _LH * 2 + 4 + _SH
        y_sgp = _Y0 + _SH
        y_pir = y_sgp + _LH * 2 + 4 + _SH

        # SHT30
        self._val(fmt(d.get("temperature"), 1, "C"), C_CYAN,  _COL_L, y_sht)
        self._val(fmt(d.get("humidity"),    1, "%"), C_TEXT,  _COL_L, y_sht + _LH)

        # QMP6988 (Pressure)
        if d.get("pressure") is not None:
            self._val(fmt(d.get("pressure"), 0, "hPa"), C_TEXT, _COL_L, y_bmp)

        # SGP30
        aqi_col = air_color(d.get("air_quality_level", "N/A"))
        self._val(fmt(d.get("eco2"), 0, "ppm"), aqi_col, _COL_R, y_sgp)
        self._val(fmt(d.get("tvoc"), 0, "ppb"), C_TEXT,  _COL_R, y_sgp + _LH)

        # PIR
        motion = d.get("motion", False)
        self._val("ALERT!" if motion else "Clear",
                  C_RED if motion else C_GREEN, _COL_R, y_pir)

        # Calculated
        y = self._y_calc
        self._val(fmt(d.get("dew_point"),         1, "C"),    C_TEXT, _COL_L, y)
        self._val(fmt(d.get("absolute_humidity"), 1, "g/m3"), C_TEXT, _COL_R, y)

        comfort = d.get("comfort_level", "")
        if comfort and comfort != "N/A":
            self._val(comfort, comfort_color(comfort), _COL_L, y + _LH)

        aqi = d.get("air_quality_level", "")
        if aqi and aqi != "N/A":
            self._val(aqi, air_color(aqi), _COL_R, y + _LH)

    def _val(self, text: str, color: int, col_x: int, y: int) -> None:
        M5.Display.fillRect(col_x + _VAL, y, _VAL_W, _LH, C_BG)
        draw_text(text, col_x + _VAL, y, color, C_BG, 1)