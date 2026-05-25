# pages/weather.py — 5-day weather forecast page for AuraSense.
# "AuraSense: See the air you breathe."
#
# Style: Matches home.py dark card aesthetic perfectly.
# Absolute centering using M5.Display.textWidth()

import M5
from M5 import *

from components import (
    SCREEN_W, SCREEN_H, STATUS_H,
    C_BG, C_TEXT, C_MUTED, C_BORDER,
    C_GREEN, C_RED, C_YELLOW, C_ORANGE,
    draw_status_bar, draw_text, fmt,
)

# ── Palette (Matches home.py) ─────────────────────────────────────────────────
C_CARD       = 0x151515  
_RAIN_COL    = 0x60a5fa
_SUB         = 0x64748b  
_DIM         = 0x475569  
_CLOUD       = 0x475569
_CLOUD2      = 0x6b7280
_CLOUD_DK    = 0x4b5563

# ── Layout ────────────────────────────────────────────────────────────────────
_HERO_Y  = STATUS_H          # 20
_HERO_H  = 84                
_STRIP_Y = _HERO_Y + _HERO_H # 104
_STRIP_H = 16                
_FORE_Y  = _STRIP_Y + _STRIP_H # 120
_FORE_H  = SCREEN_H - _FORE_Y  # 120
_COL_W   = SCREEN_W // 4     


class WeatherPage:

    def __init__(self):
        self._cached   = []
        self._location = ""
        self._needs_redraw = True

    def on_enter(self) -> None:
        M5.Display.fillScreen(C_BG)
        self._needs_redraw = True

    def on_exit(self) -> None:
        pass

    def update(self, forecast: list, time_str: str = "",
               wifi_ok: bool = False, flask_ok: bool = False,
               location: str = "") -> None:
        draw_status_bar(time_str, wifi_ok, flask_ok)

        if location:
            self._location = location

        if forecast and not self._cached:
            self._needs_redraw = True
        if forecast:
            self._cached = forecast

        if self._needs_redraw:
            self._render()

    def _render(self) -> None:
        M5.Display.fillRect(0, _HERO_Y, SCREEN_W, SCREEN_H - _HERO_Y, C_BG)

        if not self._cached:
            self._draw_centered("No forecast data", SCREEN_W // 2, 110, _SUB, C_BG)
            self._draw_centered("Waiting for backend...", SCREEN_W // 2, 130, _DIM, C_BG)
            self._needs_redraw = False
            return

        self._draw_hero(self._cached[0])
        self._draw_rain_strip(self._cached[0])
        self._draw_forecast(self._cached[1:5])
        self._needs_redraw = False

    # ── Core Typography Helpers ───────────────────────────────────────────────
    
    def _draw_centered(self, text: str, cx: int, y: int, col: int, bg: int) -> None:
        M5.Display.setTextSize(1)
        w = M5.Display.textWidth(str(text))
        draw_text(str(text), cx - w // 2, y, col, bg, 1)

    def _draw_right(self, text: str, rx: int, y: int, col: int, bg: int) -> None:
        M5.Display.setTextSize(1)
        w = M5.Display.textWidth(str(text))
        draw_text(str(text), rx - w, y, col, bg, 1)

    # ── Today Hero ────────────────────────────────────────────────────────────

    def _draw_hero(self, day: dict) -> None:
        M5.Display.fillRect(2, _HERO_Y + 2, SCREEN_W - 4, _HERO_H - 4, C_CARD)

        date = day.get("date", "")
        city = (self._location or "Outdoor")[:24]

        draw_text("TODAY  " + date, 10, _HERO_Y + 8, _SUB, C_CARD, 1)
        self._draw_right(city, SCREEN_W - 10, _HERO_Y + 8, _SUB, C_CARD)

        t_min = str(day.get("temp_min", "--"))
        t_max = str(day.get("temp_max", "--"))
        temp_str = "{} ~ {}C".format(t_min, t_max)
        
        try:
            Widgets.Label(temp_str, 10, _HERO_Y + 28, 1.0, C_TEXT, C_CARD, Widgets.FONTS.DejaVu40)
        except Exception:
            draw_text(temp_str, 10, _HERO_Y + 34, C_TEXT, C_CARD, 2)

        desc = (day.get("description") or "")
        desc_cap = (desc[0].upper() + desc[1:]) if desc else ""
        feels = day.get("feels_like", "")
        line = "{} | Feels {}C".format(desc_cap, feels) if feels else desc_cap
        draw_text(line[:32], 12, _HERO_Y + 68, C_YELLOW, C_CARD, 1)

        hum  = str(day.get("humidity", "--")) + "%"
        wind = str(day.get("wind", "--")) + " m/s"
        rx = SCREEN_W - 10

        self._draw_right("Humidity", rx, _HERO_Y + 26, _SUB, C_CARD)
        self._draw_right(hum,        rx, _HERO_Y + 42, C_TEXT, C_CARD)
        self._draw_right("Wind",     rx, _HERO_Y + 54, _SUB, C_CARD)
        self._draw_right(wind,       rx, _HERO_Y + 68, C_TEXT, C_CARD)

    # ── Rain Strip ────────────────────────────────────────────────────────────

    def _draw_rain_strip(self, day: dict) -> None:
        M5.Display.fillRect(2, _STRIP_Y, SCREEN_W - 4, _STRIP_H - 2, C_CARD)

        pop_raw = day.get("pop", 0)
        pop = int(pop_raw * 100) if isinstance(pop_raw, float) and pop_raw <= 1 else int(pop_raw)
        precip = day.get("precip_mm", 0)

        ty = _STRIP_Y + 0 
        draw_text("RAIN", 10, ty, _SUB, C_CARD, 1)

        rx = SCREEN_W - 10
        mm_str = "{}mm".format(precip)
        self._draw_right(mm_str, rx, ty, _SUB, C_CARD)
        
        M5.Display.setTextSize(1)
        w_mm = M5.Display.textWidth(mm_str)
        rx_pct = rx - w_mm - 6 
        self._draw_right("{}%".format(pop), rx_pct, ty, _RAIN_COL, C_CARD)

        w_100_max = M5.Display.textWidth("100%")
        bx = 46 
        bw = (rx_pct - w_100_max) - bx 
        bary = _STRIP_Y + 5 
        
        M5.Display.fillRect(bx, bary, bw, 4, _DIM)
        fw = max(0, min(bw, int(bw * pop / 100)))
        if fw > 0:
            M5.Display.fillRect(bx, bary, fw, 4, _RAIN_COL)

    # ── 4-Day Forecast Cards ──────────────────────────────────────────────────

    def _draw_forecast(self, days: list) -> None:
        for i, day in enumerate(days[:4]):
            x = i * _COL_W
            self._draw_col(day, x)

    def _draw_col(self, day: dict, x: int) -> None:
        M5.Display.fillRect(x + 2, _FORE_Y + 2, _COL_W - 4, _FORE_H - 4, C_CARD)
        
        y = _FORE_Y
        cx = x + (_COL_W // 2)

        day_name  = day.get("day", "---")
        date_str  = day.get("date", "")
        date_part = date_str[-5:] if len(date_str) >= 5 else date_str
        
        date_part = date_part.replace("/", "-").replace("-", ".")

        self._draw_centered(day_name, cx, y + 8, C_TEXT, C_CARD)
        self._draw_centered(date_part, cx, y + 20, _DIM, C_CARD)

        self._draw_icon(day.get("icon", ""), cx, y + 46)

        t_max = str(day.get("temp_max", "--")) + "°"
        t_min = str(day.get("temp_min", "--")) + "°"
        
        self._draw_centered(t_max, cx, y + 72, 0xFFFFFF, C_CARD)
        self._draw_centered(t_min, cx, y + 84, _DIM, C_CARD)

        pop_raw = day.get("pop", 0)
        pop = int(pop_raw * 100) if isinstance(pop_raw, float) and pop_raw <= 1 else int(pop_raw)
        
        bw = _COL_W - 16
        bx = cx - (bw // 2)
        M5.Display.fillRect(bx, y + 98, bw, 3, _DIM)
        fw = max(0, min(bw, bw * pop // 100))
        if fw > 0:
            M5.Display.fillRect(bx, y + 98, fw, 3, _RAIN_COL)
            
        self._draw_centered("{}%".format(pop), cx, y + 106, _RAIN_COL, C_CARD)

    # ── Icon drawing ──────────────────────────────────────────────────────────

    def _draw_icon(self, icon_code: str, cx: int, cy: int) -> None:
        code = icon_code[:2] if icon_code else "03"
        if   code == "01": self._sun(cx, cy)
        elif code == "02": self._partly_cloudy(cx, cy)
        elif code == "03": self._cloud(cx, cy, _CLOUD2)
        elif code == "04": self._overcast(cx, cy)
        elif code == "09": self._rain(cx, cy, heavy=True)
        elif code == "10": self._rain(cx, cy)
        elif code == "11": self._storm(cx, cy)
        elif code == "13": self._snow(cx, cy)
        elif code == "50": self._mist(cx, cy)
        else:              self._cloud(cx, cy, _CLOUD2)

    def _cloud(self, cx, cy, col):
        M5.Display.fillEllipse(cx,      cy - 2, 10, 7, col)
        M5.Display.fillEllipse(cx - 7,  cy + 2,  7, 5, col)
        M5.Display.fillEllipse(cx + 7,  cy + 3,  6, 4, col)

    def _sun(self, cx, cy):
        M5.Display.fillCircle(cx, cy, 9, C_YELLOW)
        for dx, dy in [(0,-13),(0,13),(-13,0),(13,0), (-9,-9),(9,-9),(-9,9),(9,9)]:
            M5.Display.fillCircle(cx + dx, cy + dy, 2, C_YELLOW)

    def _partly_cloudy(self, cx, cy):
        M5.Display.fillCircle(cx - 4, cy - 3, 7, C_YELLOW)
        self._cloud(cx + 2, cy + 2, _CLOUD)

    def _overcast(self, cx, cy):
        M5.Display.fillEllipse(cx,      cy - 5, 10, 6, _CLOUD2)
        M5.Display.fillEllipse(cx - 7,  cy - 1,  7, 5, _CLOUD2)
        M5.Display.fillEllipse(cx + 7,  cy,      6, 4, _CLOUD2)
        M5.Display.fillEllipse(cx,      cy + 3, 10, 6, _CLOUD_DK)
        M5.Display.fillEllipse(cx - 7,  cy + 7,  7, 5, _CLOUD_DK)
        M5.Display.fillEllipse(cx + 7,  cy + 8,  6, 4, _CLOUD_DK)

    def _rain(self, cx, cy, heavy=False):
        self._cloud(cx, cy - 5, _CLOUD)
        drops = 4 if heavy else 3
        sx = cx - (drops // 2) * 5
        for i in range(drops):
            dx = sx + i * 5
            M5.Display.drawLine(dx, cy + 4, dx - 2, cy + 11, _RAIN_COL)

    def _storm(self, cx, cy):
        self._cloud(cx, cy - 5, _CLOUD_DK)
        lx, ly = cx - 3, cy + 3
        M5.Display.drawLine(lx,     ly,     lx - 3, ly + 7, C_YELLOW)
        M5.Display.drawLine(lx - 3, ly + 7, lx + 1, ly + 7, C_YELLOW)
        M5.Display.drawLine(lx + 1, ly + 7, lx - 2, ly + 14, C_YELLOW)
        M5.Display.drawLine(cx + 6, cy + 4, cx + 4, cy + 11, _RAIN_COL)

    def _snow(self, cx, cy):
        self._cloud(cx, cy - 5, _CLOUD2)
        for dx, dy in [(-6,6),(0,8),(6,6),(-3,13),(3,13)]:
            M5.Display.fillCircle(cx + dx, cy + dy, 2, 0xe5e7eb)

    def _mist(self, cx, cy):
        for i, w in enumerate([28, 32, 26, 28]):
            yl = cy - 8 + i * 6
            col = _CLOUD2 if i % 2 == 0 else _DIM
            M5.Display.drawLine(cx - w//2, yl, cx + w//2, yl, col)