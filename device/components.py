# components.py — Shared UI constants and helpers (UIFlow2).

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

# ── Page Order (Removed "Settings" from navigation cycle) ─────────────────────
PAGES = ["Home", "Sensors", "Weather"]  

# ── Status bar fixed x positions ──────────────────────────────────────────────
_X_FLASK = 306   # Flask status dot
_X_WIFI  = 272   # "WiFi" text
_X_REC   = 205   # "REC" indicator


def draw_text(text, x: int, y: int, color: int = C_TEXT,
              bg: int = C_BG, size: int = 1) -> None:
    M5.Display.setTextSize(size)
    M5.Display.setTextColor(color, bg)
    M5.Display.drawString(str(text), x, y)


def draw_status_bar(time_str: str = "",
                    wifi: bool = True,
                    flask_ok: bool = False,
                    rec_sec: int = 0) -> None:
    M5.Display.fillRect(0, 0, SCREEN_W, STATUS_H, C_PANEL)
    draw_text(time_str, 5, 4, C_MUTED, C_PANEL, 1)
    
    if rec_sec > 0:
        draw_text("REC {}s".format(rec_sec), _X_REC + 12, 4, C_RED, C_PANEL, 1)
        M5.Display.fillRect(_X_REC, 6, 8, 8, C_RED)

    draw_text("WiFi", _X_WIFI, 4, C_GREEN if wifi else C_MUTED, C_PANEL, 1)
    dot_color = C_GREEN if flask_ok else C_RED
    M5.Display.fillCircle(_X_FLASK + 5, 10, 2, dot_color)


def update_rec_indicator(rec_sec: int) -> None:
    M5.Display.fillRect(_X_REC, 0, _X_WIFI - _X_REC - 4, STATUS_H, C_PANEL)
    if rec_sec > 0:
        M5.Display.fillRect(_X_REC, 6, 8, 8, C_RED)
        draw_text("REC {}s".format(rec_sec), _X_REC + 12, 4, C_RED, C_PANEL, 1)


def is_btnc_pressed() -> bool:
    """Returns True if BtnC is currently held."""
    return M5.BtnC.isPressed()

def fmt(value, decimals: int = 1, unit: str = "") -> str:
    if value is None: return "N/A"
    s = "{:.{}f}".format(value, decimals) if decimals else str(int(value))
    return s + unit if unit else s

def air_color(level: str) -> int:
    return {"Excellent": C_GREEN, "Good": C_GREEN, "Moderate": C_YELLOW, 
            "Poor": C_ORANGE, "Hazardous": C_RED}.get(level, C_MUTED)

def comfort_color(level: str) -> int:
    return {"Comfortable": C_GREEN, "Acceptable": C_CYAN, "Too Dry": C_ORANGE, 
            "Too Humid": C_ORANGE, "Too Cold": C_CYAN, "Too Warm": C_RED}.get(level, C_MUTED)

def weather_icon(owm_icon_code):
    """
    M5Stack does not support Emoji by default; they must be mapped to standard ASCII English phrases.
    """
    if not owm_icon_code:
        return "--"
        
    mapping = {
        "01d": "Sunny",   "01n": "Clear",
        "02d": "P.Cloud", "02n": "P.Cloud",
        "03d": "Cloudy",  "03n": "Cloudy",
        "04d": "Overcast","04n": "Overcast",
        "09d": "Shower",  "09n": "Shower",
        "10d": "Rain",    "10n": "Rain",
        "11d": "Storm",   "11n": "Storm",
        "13d": "Snow",    "13n": "Snow",
        "50d": "Mist",    "50n": "Mist"
    }
    return mapping.get(owm_icon_code, "Unk")