# pages/home.py — AuraSense home dashboard (UIFlow2).
# "AuraSense: See the air you breathe."

import M5
from M5 import *
import time

# Native hardware module for M5Stack LED control
try:
    import hardware
    _HAS_HARDWARE = True
except ImportError:
    _HAS_HARDWARE = False

from components import (
    SCREEN_W, SCREEN_H,
    C_BG, C_BORDER, C_TEXT, C_MUTED,
    C_GREEN, C_RED, C_ORANGE, C_YELLOW,
    draw_text, fmt, air_color, comfort_color,
)

# ── Layout Constants ──────────────────────────────────────────────────────────
_COL      = SCREEN_W // 2   # Vertical divider X-coordinate (160)
_TIME_Y   = 5               # Top margin for the time block
_STRIP_Y  = 76              # Top Y-coordinate for the outdoor weather strip
_STRIP_H  = 16              # Height of the outdoor weather strip
_GRID_Y   = _STRIP_Y + _STRIP_H + 2  # Added 1px extra gap for cards

# Even grid heights to balance the spacing perfectly
_GRID_H_TOP = 73  
_GRID_H_BOT = SCREEN_H - _GRID_Y - _GRID_H_TOP # Also 73

_HUM_DRY  = 30
_HUM_WET  = 60

# Card UI Colors
C_CARD       = 0x151515  # Dark grey for normal card backgrounds
C_ALERT_BG   = 0x3A0000  # Dark red for danger card backgrounds
C_WARN_BG    = 0x3A2A00  # Dark yellow for warning card backgrounds

class HomePage:

    def __init__(self):
        self._data    = {}
        self._outdoor = {}
        self._time    = "--:--"
        self._date    = ""
        self._wifi    = False
        self._flask   = False

        # Anti-flicker engine
        self._c_data       = {}
        self._c_outdoor    = {}
        self._c_time       = ""
        self._c_date       = ""
        self._c_wifi       = None
        self._c_flask      = None
        
        # LED Animation State
        self._air_status_color = C_GREEN
        self._led_on           = False
        self._last_blink       = 0
        
        self._force_all = True
        
        # Initialize Hardware LEDs
        self.rgb = None
        if _HAS_HARDWARE:
            try:
                self.rgb = hardware.RGB(io=25, n=10, type="SK6812")
                self.rgb.fill_color(0x000000) # Start in silence
            except Exception:
                pass

    def on_enter(self) -> None:
        M5.Display.fillScreen(C_BG)
        self._force_all = True

    def update(self, sensor_data: dict, outdoor: dict,
               time_str: str, wifi_ok: bool, flask_ok: bool) -> None:
        self._data    = sensor_data or {}
        self._outdoor = outdoor or {}
        self._time    = time_str
        self._wifi    = wifi_ok
        self._flask   = flask_ok

        # 1. Update internal air status color (Determines blink color)
        eco2_val = self._data.get("eco2", 0) or 0
        tvoc_val = self._data.get("tvoc", 0) or 0
        
        if eco2_val > 1000 or tvoc_val > 300:
            self._air_status_color = C_RED
        elif eco2_val > 800 or tvoc_val > 150:
            self._air_status_color = C_YELLOW
        else:
            self._air_status_color = C_GREEN

        # 2. UI Refresh Logic (Dirty checking)
        draw_time = self._force_all or (self._time != self._c_time) or (self._date != self._c_date)
        draw_face = self._force_all or (self._wifi != self._c_wifi) or (self._flask != self._c_flask) or self._dict_changed(self._data, self._c_data)
        draw_out  = self._force_all or self._dict_changed(self._outdoor, self._c_outdoor)
        draw_grid = self._force_all or self._dict_changed(self._data, self._c_data)

        if draw_time:
            self._draw_time_block()
            self._c_time = self._time
            self._c_date = self._date

        if draw_face:
            self._draw_status_face(self._air_status_color)
            self._c_wifi  = self._wifi
            self._c_flask = self._flask

        if draw_out:
            self._draw_outdoor_strip()
            self._c_outdoor = {k: v for k, v in self._outdoor.items()}

        if draw_grid:
            self._draw_grid()
            self._c_data = {k: v for k, v in self._data.items()}

        self._force_all = False

    # ── LED Blink Engine ──────────────────────────────────────────────────────
    def poll_led(self) -> None:
        """Handles the 'Silence-on-Normal, Blink-on-Anomaly' logic."""
        if not self.rgb: return
        
        # Normal state -> Silence (LEDs Off)
        if self._air_status_color == C_GREEN:
            if self._led_on: 
                self.rgb.fill_color(0x000000)
                self._led_on = False
            return

        # Anomaly states -> Blink
        now = time.ticks_ms()
        # Red blinks faster (250ms cycle), Yellow blinks slower (500ms cycle)
        interval = 250 if self._air_status_color == C_RED else 500
        
        if time.ticks_diff(now, self._last_blink) > interval:
            self._last_blink = now
            self._led_on = not self._led_on
            
            if self._led_on:
                hex_col = 0xFF0000 if self._air_status_color == C_RED else 0xFFFF00
                self.rgb.fill_color(hex_col)
            else:
                self.rgb.fill_color(0x000000)

    def _dict_changed(self, d1: dict, d2: dict) -> bool:
        if len(d1) != len(d2): return True
        for k, v in d1.items():
            if d2.get(k) != v: return True
        return False

    # ── Status face ───────────────────────────────────────────────────────────
    def _draw_status_face(self, air_status_color: int) -> None:
        wx, wy = SCREEN_W - 25, 10
        M5.Display.fillRect(wx - 2, wy - 2, 20, 20, C_BG)
        
        wifi_col  = C_GREEN if self._wifi  else C_RED
        flask_col = C_GREEN if self._flask else C_RED
        status_col = C_MUTED if not (self._wifi and self._flask) else air_status_color

        M5.Display.fillRect(wx + 2, wy + 11, 12, 2, status_col)
        M5.Display.fillCircle(wx + 3,  wy + 3, 2, wifi_col)
        M5.Display.fillCircle(wx + 13, wy + 3, 2, flask_col)

    # ── Time block ────────────────────────────────────────────────────────────
    def _draw_time_block(self) -> None:
        M5.Display.fillRect(0, 0, SCREEN_W - 30, _STRIP_Y - 1, C_BG)
        
        # Absolute exact coordinate based on your testing
        time_x = 100
        try:
            Widgets.Label(self._time, time_x, _TIME_Y, 1.0, C_TEXT, C_BG, Widgets.FONTS.DejaVu72)
        except Exception:
            M5.Display.drawCenterString(self._time, SCREEN_W//2 + 15, _TIME_Y + 10, 3)

        if self._date:
            date_x = (SCREEN_W // 2) - (len(self._date) * 4) + 8
            draw_text(self._date, date_x, _TIME_Y + 51, C_MUTED, C_BG, 1)

    # ── Outdoor strip ─────────────────────────────────────────────────────────
    def _draw_outdoor_strip(self) -> None:
        M5.Display.fillRect(2, _STRIP_Y, SCREEN_W - 4, _STRIP_H, C_CARD)
        ty = _STRIP_Y + 3
        out_t = self._outdoor.get("outdoor_temp")
        
        if out_t is not None:
            _d = self._outdoor.get("outdoor_desc") or ""
            out_desc = (_d[0].upper() + _d[1:]) if _d else ""
            t_str = "{}C".format(round(out_t))
            
            loc = str(self._outdoor.get("location") or "Outdoor")[:24]
            
            w1, w2, w3, gap = len(out_desc)*6.2, len(t_str)*6.2, len(loc)*6.2, 12 
            start_x = max(0, int((SCREEN_W - (w1 + w2 + w3 + gap*2)) // 2)) 
            
            draw_text(out_desc, start_x, ty, C_YELLOW, C_CARD, 1)
            current_x = start_x + int(w1) + gap
            draw_text(t_str, current_x, ty, C_TEXT, C_CARD, 1)
            current_x = current_x + int(w2) + gap
            draw_text(loc, current_x, ty, C_MUTED, C_CARD, 1)
        else:
            txt = "Outdoor Data Offline"
            draw_text(txt, (SCREEN_W - (len(txt)*6))//2, ty, C_MUTED, C_CARD, 1)

    # ── Grid ──────────────────────────────────────────────────────────────────
    def _draw_grid(self) -> None:
        d = self._data
        M5.Display.fillRect(0, _GRID_Y, SCREEN_W, SCREEN_H - _GRID_Y, C_BG)
        
        self._draw_cell_temp(d, 0, _GRID_Y, _GRID_H_TOP)
        self._draw_cell_hum(d, _COL, _GRID_Y, _GRID_H_TOP)
        self._draw_cell_eco2(d, 0, _GRID_Y + _GRID_H_TOP, _GRID_H_BOT)
        self._draw_cell_tvoc(d, _COL, _GRID_Y + _GRID_H_TOP, _GRID_H_BOT)

    def _draw_cell_temp(self, d: dict, x: int, y: int, h: int) -> None:
        M5.Display.fillRect(x + 2, y + 2, _COL - 4, h - 4, C_CARD)
        temp = d.get("temperature")
        
        draw_text("INDOOR", x + 10, y + 4, C_MUTED, C_CARD, 1)
        
        t_str = fmt(temp, 1) if temp is not None else "--"
        t_str += "C" if temp is not None else ""
        
        try: Widgets.Label(t_str, x + 10, y + 18, 1.0, 0xFFFFFF, C_CARD, Widgets.FONTS.DejaVu40)
        except: draw_text(t_str, x + 10, y + 24, 0xFFFFFF, C_CARD, 2)
        
        comfort = d.get("comfort_level", "")
        draw_text(comfort, x + 10, y + h - 15, comfort_color(comfort), C_CARD, 1)

    def _draw_cell_hum(self, d: dict, x: int, y: int, h: int) -> None:
        M5.Display.fillRect(x + 2, y + 2, _COL - 4, h - 4, C_CARD)
        hum = d.get("humidity")
        
        draw_text("HUMIDITY", x + 10, y + 4, C_MUTED, C_CARD, 1)
        
        h_str = fmt(hum, 0) if hum is not None else "--"
        h_str += "%" if hum is not None else ""
        
        try: Widgets.Label(h_str, x + 10, y + 18, 1.0, 0xFFFFFF, C_CARD, Widgets.FONTS.DejaVu40)
        except: draw_text(h_str, x + 10, y + 24, 0xFFFFFF, C_CARD, 2)
        
        bar_x, bar_y, bar_w = x + 10, y + h - 10, _COL - 20
        M5.Display.fillRect(bar_x, bar_y, bar_w * _HUM_DRY // 100, 4, C_ORANGE)
        M5.Display.fillRect(bar_x + (bar_w * _HUM_DRY // 100), bar_y, bar_w * (_HUM_WET - _HUM_DRY) // 100, 4, C_GREEN)
        M5.Display.fillRect(bar_x + (bar_w * _HUM_WET // 100), bar_y, bar_w - (bar_w * _HUM_WET // 100), 4, 0x1e40af)
        if hum is not None:
            M5.Display.fillRect(bar_x + min(bar_w - 2, int(bar_w * hum / 100)), bar_y - 2, 2, 8, C_TEXT)

    def _draw_cell_eco2(self, d: dict, x: int, y: int, h: int) -> None:
        eco2 = d.get("eco2")
        val = eco2 if eco2 is not None else 0
        
        bg_col = C_ALERT_BG if val > 1000 else (C_WARN_BG if val > 800 else C_CARD)
        M5.Display.fillRect(x + 2, y + 2, _COL - 4, h - 4, bg_col)
        
        level = d.get("air_quality_level", "")
        col = 0xFFFFFF if val > 800 else (air_color(level) if level else C_TEXT)
        
        draw_text("eCO2 (ppm)", x + 10, y + 4, C_MUTED, bg_col, 1)

        e_str = fmt(eco2, 0) if eco2 is not None else "--"
        try: Widgets.Label(e_str, x + 10, y + 18, 1.0, col, bg_col, Widgets.FONTS.DejaVu40)
        except: draw_text(e_str, x + 10, y + 24, col, bg_col, 2)

        if eco2 is not None:
            draw_text(level, x + 10, y + h - 15, col, bg_col, 1)

    def _draw_cell_tvoc(self, d: dict, x: int, y: int, h: int) -> None:
        tvoc = d.get("tvoc")
        val = tvoc if tvoc is not None else 0
        
        bg_col = C_ALERT_BG if val > 300 else (C_WARN_BG if val > 150 else C_CARD)
        M5.Display.fillRect(x + 2, y + 2, _COL - 4, h - 4, bg_col)
        
        if tvoc is None: 
            t_col, t_level = C_MUTED, ""
        elif val < 150: 
            t_col, t_level = C_GREEN, "Low"
        elif val < 300: 
            t_col, t_level = C_YELLOW, "Moderate"
        else:            
            t_col, t_level = C_RED, "High"
        
        main_col = 0xFFFFFF if val > 150 else C_TEXT

        draw_text("TVOC (ppb)", x + 10, y + 4, C_MUTED, bg_col, 1)
        
        t_str = fmt(tvoc, 0) if tvoc is not None else "--"
        try: Widgets.Label(t_str, x + 10, y + 18, 1.0, main_col, bg_col, Widgets.FONTS.DejaVu40)
        except: draw_text(t_str, x + 10, y + 24, main_col, bg_col, 2)

        if tvoc is not None:
            status_col = 0xFFFFFF if val > 150 else t_col
            draw_text(t_level, x + 10, y + h - 15, status_col, bg_col, 1)

    def set_date(self, date_str: str) -> None:
        self._date = date_str.upper()