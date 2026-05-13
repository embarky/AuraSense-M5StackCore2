# pages/home.py — Smart Space home dashboard (UIFlow2).

import M5
from M5 import *

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
_GRID_Y   = _STRIP_Y + _STRIP_H + 1

# Asymmetric grid: Give more vertical space to the bottom cells 
# so units with descending letters (like 'p' in ppm/ppb) are not cut off.
_GRID_H_TOP = 68  
_GRID_H_BOT = SCREEN_H - _GRID_Y - _GRID_H_TOP 

_HUM_DRY  = 30
_HUM_WET  = 60

class HomePage:

    def __init__(self):
        self._data    = {}
        self._outdoor = {}
        self._time    = "--:--"
        self._date    = ""
        self._wifi    = False
        self._flask   = False

        # Anti-flicker engine: Cache the previous state of the UI
        self._c_data    = {}
        self._c_outdoor = {}
        self._c_time    = ""
        self._c_date    = ""
        self._c_wifi    = None
        self._c_flask   = None
        self._force_all = True  # Force full redraw on first enter

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

        # Dirty data detection: Only issue drawing commands for sections that actually changed
        draw_time = self._force_all or (self._time != self._c_time) or (self._date != self._c_date)
        draw_face = self._force_all or (self._wifi != self._c_wifi) or (self._flask != self._c_flask) or self._dict_changed(self._data, self._c_data)
        draw_out  = self._force_all or self._dict_changed(self._outdoor, self._c_outdoor)
        draw_grid = self._force_all or self._dict_changed(self._data, self._c_data)

        if draw_time:
            self._draw_time_block()
            self._c_time = self._time
            self._c_date = self._date

        if draw_face:
            self._draw_status_face()
            self._c_wifi  = self._wifi
            self._c_flask = self._flask

        if draw_out:
            self._draw_outdoor_strip()
            self._c_outdoor = {k: v for k, v in self._outdoor.items()}

        if draw_grid:
            self._draw_grid()
            self._c_data = {k: v for k, v in self._data.items()}

        self._force_all = False

    def _dict_changed(self, d1: dict, d2: dict) -> bool:
        """Fast dictionary comparison for partial UI updates."""
        if len(d1) != len(d2): return True
        for k, v in d1.items():
            if d2.get(k) != v: return True
        return False

    # ── Status face ───────────────────────────────────────────────────────────
    def _draw_status_face(self) -> None:
        wx  = SCREEN_W - 25
        wy  = 10
        
        # Erase the face area locally to prevent pixel artifacts
        M5.Display.fillRect(wx - 2, wy - 2, 20, 20, C_BG)
        
        # Left eye = WiFi, Right eye = Flask backend
        wifi_col  = C_GREEN if self._wifi  else C_RED
        flask_col = C_GREEN if self._flask else C_RED

        status_col = C_GREEN
        if not (self._wifi and self._flask):
            # Muted grey line indicates disconnected state
            status_col = C_MUTED 
        else:
            # Color indicates overall indoor air quality health
            eco2 = self._data.get("eco2", 0) or 0
            tvoc = self._data.get("tvoc", 0) or 0
            if eco2 > 1000 or tvoc > 300: status_col = C_RED
            elif eco2 > 800 or tvoc > 150: status_col = C_YELLOW

        # Draw the mouth as a simple, clean, horizontal straight line (2px thick)
        M5.Display.fillRect(wx + 2, wy + 11, 12, 2, status_col)

        # Draw the eyes on top
        M5.Display.fillCircle(wx + 3,  wy + 3, 2, wifi_col)
        M5.Display.fillCircle(wx + 13, wy + 3, 2, flask_col)

    # ── Time block ────────────────────────────────────────────────────────────
    def _draw_time_block(self) -> None:
        M5.Display.fillRect(0, 0, SCREEN_W - 30, _STRIP_Y - 1, C_BG)

        # Lock time coordinate based on exact physical centering test
        time_x = 96 
        try:
            Widgets.Label(self._time, time_x, _TIME_Y, 1.0, C_TEXT, C_BG, Widgets.FONTS.DejaVu72)
        except Exception:
            M5.Display.drawCenterString(self._time, SCREEN_W//2 + 15, _TIME_Y + 10, 3)

        if self._date:
            # Date offset locked relative to physical screen center
            date_x = (SCREEN_W // 2) - (len(self._date) * 4) + 10
            draw_text(self._date, date_x, _TIME_Y + 51, C_MUTED, C_BG, 1)

    # ── Outdoor strip ─────────────────────────────────────────────────────────
    def _draw_outdoor_strip(self) -> None:
        M5.Display.fillRect(0, _STRIP_Y, SCREEN_W, _STRIP_H, 0x111111)
        M5.Display.drawLine(0, _STRIP_Y, SCREEN_W, _STRIP_Y, C_BORDER)
        
        ty = _STRIP_Y + 3
        out_t = self._outdoor.get("outdoor_temp")
        
        if out_t is not None:
            _d = self._outdoor.get("outdoor_desc") or ""
            out_desc = (_d[0].upper() + _d[1:]) if _d else ""
            t_str = "{}C".format(round(out_t))
            loc = str(self._outdoor.get("location") or "")[:10]

            # Dynamic width calculation for absolute physical centering
            w1 = len(out_desc) * 7
            w2 = len(t_str) * 7
            w3 = len(loc) * 7
            gap = 18 
            
            total_w = w1 + gap + w2 + gap + w3
            start_x = max(0, (SCREEN_W - total_w) // 2) 

            draw_text(out_desc, start_x, ty, C_YELLOW, 0x111111, 1)
            draw_text(t_str, start_x + w1 + gap, ty, C_TEXT, 0x111111, 1)
            draw_text(loc, start_x + w1 + gap + w2 + gap, ty, C_MUTED, 0x111111, 1)
        else:
            txt = "Outdoor Data Offline"
            draw_text(txt, 100, ty, C_MUTED, 0x111111, 1)

    # ── 4-cell indoor grid ────────────────────────────────────────────────────
    def _draw_grid(self) -> None:
        d = self._data
        M5.Display.drawLine(_COL, _GRID_Y, _COL, SCREEN_H, C_BORDER)
        M5.Display.drawLine(0, _GRID_Y + _GRID_H_TOP, SCREEN_W, _GRID_Y + _GRID_H_TOP, C_BORDER)

        self._draw_cell_temp(d, 0, _GRID_Y, _GRID_H_TOP)
        self._draw_cell_hum(d, _COL, _GRID_Y, _GRID_H_TOP)
        self._draw_cell_eco2(d, 0, _GRID_Y + _GRID_H_TOP, _GRID_H_BOT)
        self._draw_cell_tvoc(d, _COL, _GRID_Y + _GRID_H_TOP, _GRID_H_BOT)

    def _draw_cell_temp(self, d: dict, x: int, y: int, h: int) -> None:
        M5.Display.fillRect(x + 1, y + 1, _COL - 2, h - 2, C_BG)
        temp = d.get("temperature")
        comfort = d.get("comfort_level", "")
        
        draw_text("INDOOR", x + 8, y + 4, C_MUTED, C_BG, 1)
        
        t_str = fmt(temp, 1) + "C" if temp is not None else "--"
        try:
            Widgets.Label(t_str, x + 8, y + 16, 1.0, C_TEXT, C_BG, Widgets.FONTS.DejaVu40)
        except Exception:
            draw_text(t_str, x + 8, y + 20, C_TEXT, C_BG, 2)
        
        draw_text(comfort, x + 8, y + h - 15, comfort_color(comfort), C_BG, 1)

    def _draw_cell_hum(self, d: dict, x: int, y: int, h: int) -> None:
        M5.Display.fillRect(x + 1, y + 1, _COL - 2, h - 2, C_BG)
        hum = d.get("humidity")
        draw_text("HUMIDITY", x + 8, y + 4, C_MUTED, C_BG, 1)
        
        h_str = fmt(hum, 0) + "%" if hum is not None else "--"
        try:
            Widgets.Label(h_str, x + 8, y + 16, 1.0, C_TEXT, C_BG, Widgets.FONTS.DejaVu40)
        except Exception:
            draw_text(h_str, x + 8, y + 20, C_TEXT, C_BG, 2)

        bar_x = x + 8
        bar_y = y + h - 10
        bar_w = _COL - 16
        dry_w = bar_w * _HUM_DRY // 100
        ok_w  = bar_w * (_HUM_WET - _HUM_DRY) // 100
        wet_w = bar_w - dry_w - ok_w

        M5.Display.fillRect(bar_x,                bar_y, dry_w, 4, C_ORANGE)
        M5.Display.fillRect(bar_x + dry_w,        bar_y, ok_w,  4, C_GREEN)
        M5.Display.fillRect(bar_x + dry_w + ok_w, bar_y, wet_w, 4, 0x1e40af)

        if hum is not None:
            cursor_x = bar_x + min(bar_w - 2, int(bar_w * hum / 100))
            M5.Display.fillRect(cursor_x, bar_y - 2, 2, 8, C_TEXT)

    def _draw_cell_eco2(self, d: dict, x: int, y: int, h: int) -> None:
        M5.Display.fillRect(x + 1, y + 1, _COL - 2, h - 2, C_BG)
        eco2 = d.get("eco2")
        level = d.get("air_quality_level", "")
        col = air_color(level) if level else C_TEXT
        
        draw_text("eCO2 (ppm)", x + 8, y + 4, C_MUTED, C_BG, 1)

        e_str = fmt(eco2, 0) if eco2 is not None else "--"
        try:
            # Shifted down slightly to accommodate the DejaVu40 font size
            Widgets.Label(e_str, x + 8, y + 18, 1.0, col, C_BG, Widgets.FONTS.DejaVu40)
        except Exception:
            draw_text(e_str, x + 8, y + 22, col, C_BG, 2)

        draw_text(level, x + 8, y + h - 16, col, C_BG, 1)

    def _draw_cell_tvoc(self, d: dict, x: int, y: int, h: int) -> None:
        M5.Display.fillRect(x + 1, y + 1, _COL - 2, h - 2, C_BG)
        tvoc = d.get("tvoc")
        if tvoc is None: t_col, t_level = C_MUTED, ""
        elif tvoc < 150: t_col, t_level = C_GREEN, "Low"
        elif tvoc < 300: t_col, t_level = C_YELLOW, "Moderate"
        else:            t_col, t_level = C_RED, "High"

        draw_text("TVOC (ppb)", x + 8, y + 4, C_MUTED, C_BG, 1)
        
        t_str = fmt(tvoc, 0) if tvoc is not None else "--"
        try:
            Widgets.Label(t_str, x + 8, y + 18, 1.0, C_TEXT, C_BG, Widgets.FONTS.DejaVu40)
        except Exception:
            draw_text(t_str, x + 8, y + 22, C_TEXT, C_BG, 2)

        draw_text(t_level, x + 8, y + h - 16, t_col, C_BG, 1)

    def set_date(self, date_str: str) -> None:
        self._date = date_str.upper()