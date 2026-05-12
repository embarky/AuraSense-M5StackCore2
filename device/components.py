# components.py — Shared UI constants and helpers (UIFlow2).
#
# Status bar layout (320px wide, 20px tall):
#
#   [22:45]    [● REC 3s]    [WiFi]  [●]
#    time      recording     wifi   flask
#              (left of WiFi, only when recording)

import M5
from M5 import *

# ── Screen layout ─────────────────────────────────────────────────────────────
SCREEN_W  = 320
SCREEN_H  = 240
STATUS_H  = 20     # top status bar only — no nav bar, no mic strip
CONTENT_Y = STATUS_H
CONTENT_H = SCREEN_H - STATUS_H    # 220px full content

# ── Colour palette ────────────────────────────────────────────────────────────
C_BG     = 0x000000
C_PANEL  = 0x111111
C_BORDER = 0x333333
C_TEXT   = 0xFFFFFF
C_MUTED  = 0x666666
C_GREEN  = 0x00FF00
C_RED    = 0xFF2222
C_BLUE   = 0x00CFFF
C_YELLOW = 0xFFFF00
C_ORANGE = 0xFF8800
C_CYAN   = 0x00FFFF

# ── Page order for swipe navigation ──────────────────────────────────────────
PAGES = ["Settings", "Home", "Forecast"]   # swipe right→left


# ── Text helper ───────────────────────────────────────────────────────────────

def draw_text(text, x: int, y: int, color: int = C_TEXT,
              bg: int = C_BG, size: int = 1) -> None:
    M5.Display.setTextSize(size)
    M5.Display.setTextColor(color, bg)
    M5.Display.drawString(str(text), x, y)


# ── Status bar ────────────────────────────────────────────────────────────────
# Right side (fixed positions):
#   Flask dot  ●   at x=308
#   WiFi text      at x=270
#   REC indicator  at x=170  (only shown when rec_sec > 0)

_X_FLASK = 308
_X_WIFI  = 268
_X_REC   = 165    # left of WiFi

def draw_status_bar(time_str: str = "",
                    wifi: bool = True,
                    flask_ok: bool = True,
                    rec_sec: int = 0) -> None:
    M5.Display.fillRect(0, 0, SCREEN_W, STATUS_H, C_PANEL)

    # Time
    draw_text(time_str, 5, 4, C_MUTED, C_PANEL, 1)

    # Recording indicator (clears itself when rec_sec == 0)
    rec_area_w = _X_WIFI - _X_REC - 4
    M5.Display.fillRect(_X_REC, 0, rec_area_w, STATUS_H, C_PANEL)
    if rec_sec > 0:
        draw_text("● REC {}s".format(rec_sec), _X_REC, 4, C_RED, C_PANEL, 1)

    # WiFi text (colored)
    draw_text("WiFi", _X_WIFI, 4,
              C_GREEN if wifi else C_MUTED, C_PANEL, 1)

    # Flask dot
    draw_text("●", _X_FLASK, 4,
              C_GREEN if flask_ok else C_RED, C_PANEL, 1)


def update_rec_indicator(rec_sec: int) -> None:
    """Update only the REC area — avoids full status bar redraw."""
    rec_area_w = _X_WIFI - _X_REC - 4
    M5.Display.fillRect(_X_REC, 0, rec_area_w, STATUS_H, C_PANEL)
    if rec_sec > 0:
        draw_text("● REC {}s".format(rec_sec), _X_REC, 4, C_RED, C_PANEL, 1)


# ── Swipe detection ───────────────────────────────────────────────────────────

class SwipeDetector:
    """
    Detect horizontal swipe gestures on the touchscreen.
    Call update() every loop iteration. Returns "left", "right", or None.
    """
    SWIPE_MIN_X = 50    # minimum horizontal travel
    SWIPE_MAX_Y = 45    # maximum vertical drift

    def __init__(self):
        self._start  = None
        self._last   = None

    def update(self) -> str | None:
        M5.update()
        if M5.Touch.getCount() > 0:
            try:
                tx, ty = M5.Touch.getX(), M5.Touch.getY()
            except Exception:
                return None
            if self._start is None:
                self._start = (tx, ty)
            self._last = (tx, ty)
            return None
        else:
            if self._start is not None and self._last is not None:
                sx, sy = self._start
                ex, ey = self._last
                self._start = self._last = None
                dx = ex - sx
                dy = ey - sy
                if abs(dx) >= self.SWIPE_MIN_X and abs(dy) <= self.SWIPE_MAX_Y:
                    return "left" if dx < 0 else "right"
            self._start = self._last = None
            return None


# ── Utility ───────────────────────────────────────────────────────────────────

def fmt(value, decimals: int = 1, unit: str = "") -> str:
    if value is None:
        return "N/A"
    s = "{:.{}f}".format(value, decimals) if decimals else str(int(value))
    return s + unit if unit else s


def air_color(level: str) -> int:
    return {"Excellent": C_GREEN, "Good": C_GREEN,
            "Moderate":  C_YELLOW, "Poor": C_ORANGE,
            "Hazardous": C_RED}.get(level, C_MUTED)


def comfort_color(level: str) -> int:
    return {"Comfortable": C_GREEN, "Acceptable": C_CYAN,
            "Too Dry":     C_ORANGE, "Too Humid": C_ORANGE,
            "Too Cold":    C_CYAN,   "Too Warm":  C_RED}.get(level, C_MUTED)