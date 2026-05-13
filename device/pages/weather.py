# pages/weather.py — Split Dashboard UI for 5-day forecast (Ultra-Fast Response).

import M5
from M5 import *
import time

from components import (
    SCREEN_W, SCREEN_H, CONTENT_Y, CONTENT_H, STATUS_H,
    C_BG, C_TEXT, C_MUTED, C_GREEN, C_RED, C_BLUE,
    C_YELLOW, C_ORANGE, C_PANEL, C_BORDER,
    draw_status_bar, draw_text, weather_icon,
)

# ── Layout Constants ──────────────────────────────────────────────────────────
_RIGHT_X = 125
_ROW_H   = 44

class WeatherPage:

    def __init__(self):
        self._selected_idx = 0
        self._cached       = []
        self._needs_redraw = True
        self._last_touch   = 0
        self._is_offline   = False  # Remembers network state for instant redraws

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_enter(self) -> None:
        M5.Display.fillScreen(C_BG)
        self._needs_redraw = True

    def on_exit(self) -> None:
        pass

    # ── Called every DRAW_INTERVAL from main.py ───────────────────────────────

    def update(self, forecast: list, time_str: str = "",
               wifi_ok: bool = False, flask_ok: bool = False) -> None:

        draw_status_bar(time_str, wifi_ok, flask_ok)
        self._is_offline = not (wifi_ok and flask_ok)

        if forecast and not self._cached:
            self._needs_redraw = True
            self._selected_idx = 0
            
        if forecast:
            self._cached = forecast

        if self._needs_redraw:
            self._force_draw_all()

    def _force_draw_all(self):
        """Core rendering engine: Extracted to allow instant redraws on touch, bypassing the 2-second loop delay."""
        M5.Display.fillRect(0, CONTENT_Y, SCREEN_W, CONTENT_H, C_BG)
        if not self._cached:
            draw_text("Waiting for backend...", 78, 126, C_MUTED, C_BG, 1)
        else:
            self._draw_left_panel(self._is_offline)
            self._draw_right_list()
        self._needs_redraw = False

    # ── Touch Polling (Ultra-Fast Response) ───────────────────────────────────

    def poll_touch(self) -> None:
        """Called every main loop iteration (20ms) for responsive touch detection."""
        if M5.Touch.getCount() > 0:
            t = time.ticks_ms()
            # Ultra-fast debounce: 150ms provides a snappy response
            if time.ticks_diff(t, self._last_touch) > 150: 
                self._last_touch = t
                tx = M5.Touch.getX()
                ty = M5.Touch.getY()
                
                if CONTENT_Y < ty < SCREEN_H - 10:
                    if self._handle_tap(tx, ty):
                        # 1. Instant haptic feedback
                        try:
                            M5.Power.setVibration(60)
                            time.sleep_ms(20)
                            M5.Power.setVibration(0)
                        except Exception:
                            pass
                        
                        # 2. Force immediate redraw instead of waiting for the next cycle
                        self._force_draw_all()

    def _handle_tap(self, tx: int, ty: int) -> bool:
        if tx >= _RIGHT_X:
            idx = (ty - CONTENT_Y) // _ROW_H
            if 0 <= idx < len(self._cached):
                if self._selected_idx != idx:
                    self._selected_idx = idx
                    return True  # State changed, trigger redraw
        return False

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw_left_panel(self, offline: bool) -> None:
        if self._selected_idx >= len(self._cached): return
        day = self._cached[self._selected_idx]
        
        M5.Display.drawLine(_RIGHT_X, CONTENT_Y, _RIGHT_X, SCREEN_H, C_BORDER)

        # Clean title formatting, trims extra spaces to avoid redundant display
        label = day.get("date", "---").replace("/", ".")

        desc = str(day.get("description", ""))
        if len(desc) > 0: desc = desc[0].upper() + desc[1:]
        
        t_min = day.get("temp_min", "--")
        t_max = day.get("temp_max", "--")
        hum   = day.get("humidity", "--")
        wind  = day.get("wind", "--")
        precip = day.get("precip_mm", 0)
        pop_raw = day.get("pop", 0)
        pop = int(pop_raw * 100) if isinstance(pop_raw, float) and pop_raw <= 1 else int(pop_raw)

        x = 8
        y = CONTENT_Y + 8
        draw_text(label, x, y, C_BLUE, C_BG, 1)
        
        y += 20
        draw_text(weather_icon(day.get("icon", "")), x, y, C_YELLOW, C_BG, 1)
        
        y += 20
        draw_text(f"{t_min}~{t_max} C", x, y, C_TEXT, C_BG, 1)
        
        y += 24
        draw_text(desc, x, y, C_TEXT, C_BG, 1)

        y += 20
        draw_text(f"Hum:  {hum}%", x, y, C_MUTED, C_BG, 1)
        
        y += 18
        draw_text(f"Wind: {wind}m/s", x, y, C_MUTED, C_BG, 1)
        
        y += 18
        draw_text(f"Rain: {precip}mm", x, y, C_MUTED, C_BG, 1)
        
        y += 18
        draw_text(f"PoP:  {pop}%", x, y, C_MUTED, C_BG, 1)

        if offline:
            draw_text("[Offline]", x, SCREEN_H - 14, C_RED, C_BG, 1)


    def _draw_right_list(self) -> None:
        for i, day in enumerate(self._cached):
            if i >= 5: break
            
            y = CONTENT_Y + i * _ROW_H
            is_sel = (i == self._selected_idx)
            bg = C_PANEL if is_sel else C_BG

            if is_sel:
                M5.Display.fillRect(_RIGHT_X + 1, y, SCREEN_W - _RIGHT_X - 1, _ROW_H, bg)
                M5.Display.fillRect(_RIGHT_X + 1, y, 4, _ROW_H, C_BLUE)

            cy = y + 15

            draw_text(day.get("day", ""), _RIGHT_X + 12, cy, C_TEXT, bg, 1)
            draw_text(weather_icon(day.get("icon", "")), _RIGHT_X + 55, cy, C_YELLOW if is_sel else C_MUTED, bg, 1)
            
            t_min = day.get("temp_min", "--")
            t_max = day.get("temp_max", "--")
            draw_text(f"{t_min}~{t_max}C", _RIGHT_X + 130, cy, C_TEXT, bg, 1)

            if i < 4:
                M5.Display.drawLine(_RIGHT_X, y + _ROW_H - 1, SCREEN_W, y + _ROW_H - 1, C_BORDER)