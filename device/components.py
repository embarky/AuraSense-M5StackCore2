# components.py — Shared UI constants and helpers (UIFlow2).
#
# Status bar layout (320px wide, 20px tall):
#
#   [22:45]    [● REC 3s]    [WiFi]  [■]
#    time      recording     text   flask dot (filled rect)

import M5
from M5 import *

# ── Screen layout ─────────────────────────────────────────────────────────────
SCREEN_W  = 320
SCREEN_H  = 240
STATUS_H  = 20
CONTENT_Y = STATUS_H
CONTENT_H = SCREEN_H - STATUS_H   # 220px

# ── Colour palette ────────────────────────────────────────────────────────────
C_BG     = 0x000000
C_PANEL  = 0x111111
C_BORDER = 0x333333
C_TEXT   = 0xFFFFFF
C_MUTED  = 0x666666
C_GREEN  = 0x00CC00
C_RED    = 0xFF2222
C_BLUE   = 0x00CFFF
C_YELLOW = 0xFFFF00
C_ORANGE = 0xFF8800
C_CYAN   = 0x00FFFF

# ── Page order ────────────────────────────────────────────────────────────────
PAGES = ["Settings", "Home", "Forecast"]

# ── Status bar fixed x positions ──────────────────────────────────────────────
_X_FLASK = 306   # 10x10 filled rect (flask status dot)
_X_WIFI  = 265   # "WiFi" text (4 chars)
_X_REC   = 160   # "REC 3s" text (shown only when recording)


# ── Core text helper ──────────────────────────────────────────────────────────

def draw_text(text, x: int, y: int, color: int = C_TEXT,
              bg: int = C_BG, size: int = 1) -> None:
    M5.Display.setTextSize(size)
    M5.Display.setTextColor(color, bg)
    M5.Display.drawString(str(text), x, y)


# ── Status bar ────────────────────────────────────────────────────────────────

def draw_status_bar(time_str: str = "",
                    wifi: bool = True,
                    flask_ok: bool = False,
                    rec_sec: int = 0) -> None:
    M5.Display.fillRect(0, 0, SCREEN_W, STATUS_H, C_PANEL)

    # Time (left)
    draw_text(time_str, 5, 4, C_MUTED, C_PANEL, 1)

    # REC indicator (centre-right, only when recording)
    M5.Display.fillRect(_X_REC, 0, _X_WIFI - _X_REC - 4, STATUS_H, C_PANEL)
    if rec_sec > 0:
        draw_text("REC {}s".format(rec_sec), _X_REC + 12, 4, C_RED, C_PANEL, 1)
        # Small red filled square as "●" substitute
        M5.Display.fillRect(_X_REC, 6, 8, 8, C_RED)

    # WiFi text (colored)
    draw_text("WiFi", _X_WIFI, 4,
              C_GREEN if wifi else C_MUTED, C_PANEL, 1)

    # Flask status dot — 10×10 filled rect (reliable across all fonts)
    dot_color = C_GREEN if flask_ok else C_RED
    M5.Display.fillRect(_X_FLASK, 5, 10, 10, dot_color)


def update_rec_indicator(rec_sec: int) -> None:
    """Update only the REC area without redrawing the whole status bar."""
    M5.Display.fillRect(_X_REC, 0, _X_WIFI - _X_REC - 4, STATUS_H, C_PANEL)
    if rec_sec > 0:
        M5.Display.fillRect(_X_REC, 6, 8, 8, C_RED)
        draw_text("REC {}s".format(rec_sec), _X_REC + 12, 4, C_RED, C_PANEL, 1)


# ── Swipe detector ────────────────────────────────────────────────────────────

class SwipeDetector:
    """
    Detect horizontal swipe gestures.
    Tracks start position on first touch, compares on release.
    Returns "left", "right", or None.
    """
    SWIPE_MIN_X = 50   # minimum horizontal travel px
    SWIPE_MAX_Y = 50   # maximum vertical drift px

    def __init__(self):
        self._touching  = False
        self._start_x   = 0
        self._start_y   = 0
        self._cur_x     = 0
        self._cur_y     = 0

    def update(self) -> str | None:
        M5.update()
        count = M5.Touch.getCount()

        if count > 0:
            try:
                tx = M5.Touch.getX()
                ty = M5.Touch.getY()
                if not self._touching:
                    # First frame of touch — record start
                    self._touching = True
                    self._start_x  = tx
                    self._start_y  = ty
                # Update current position every frame
                self._cur_x = tx
                self._cur_y = ty
            except Exception:
                pass
            return None

        else:
            if self._touching:
                # Touch just released — evaluate gesture
                self._touching = False
                dx = self._cur_x - self._start_x
                dy = self._cur_y - self._start_y
                if abs(dx) >= self.SWIPE_MIN_X and abs(dy) <= self.SWIPE_MAX_Y:
                    return "left" if dx < 0 else "right"
            return None


# ── BtnC zone (bottom-right touch area on Core2) ─────────────────────────────
# Core2 virtual buttons sit in the bottom strip (y >= 220).
# BtnC is the rightmost third: x >= 214.

def is_btnc_pressed() -> bool:
    """Return True if the BtnC touch zone is currently pressed."""
    M5.update()
    if M5.Touch.getCount() > 0:
        try:
            return M5.Touch.getX() >= 214 and M5.Touch.getY() >= 220
        except Exception:
            pass
    return False


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