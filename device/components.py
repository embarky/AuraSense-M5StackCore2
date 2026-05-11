# components.py — Reusable UI components shared across all pages.
#
# Provides: status bar, metric cards, alert banner, nav bar.
# All drawing is done directly on M5.Display.

import M5
from M5 import *

# ── Colour palette ────────────────────────────────────────────────────────────

C_BG       = 0x0D1117
C_CARD     = 0x161B22
C_BORDER   = 0x21262D
C_TEXT     = 0xE6EDF3
C_MUTED    = 0x8B949E
C_YELLOW   = 0xFFFF00
C_GREEN    = 0x3FB950
C_RED      = 0xFF4444
C_BLUE     = 0x58A6FF
C_ORANGE   = 0xFFA500
C_PURPLE   = 0xBC8CFF

SCREEN_W   = 320
SCREEN_H   = 240
NAV_H      = 30         # height of bottom navigation bar
STATUS_H   = 20         # height of top status bar
CONTENT_Y  = STATUS_H  # content starts below status bar
CONTENT_H  = SCREEN_H - STATUS_H - NAV_H


# ── Status bar ────────────────────────────────────────────────────────────────

def draw_status_bar(time_str: str = "", wifi: bool = True) -> None:
    """
    Top bar (y=0..STATUS_H): time on left, WiFi indicator on right.
    """
    M5.Display.fillRect(0, 0, SCREEN_W, STATUS_H, C_BG)
    M5.Display.setTextSize(1)

    if time_str:
        M5.Display.setTextColor(C_MUTED, C_BG)
        M5.Display.drawString(time_str, 5, 6)

    # WiFi dot
    dot_color = C_GREEN if wifi else C_RED
    M5.Display.fillCircle(SCREEN_W - 8, STATUS_H // 2, 4, dot_color)


# ── Navigation bar ────────────────────────────────────────────────────────────

_NAV_PAGES = ["Home", "Forecast", "Settings"]

def draw_nav_bar(active: str) -> None:
    """
    Bottom navigation bar with three page tabs.
    active: one of "Home", "Forecast", "Settings"
    """
    y   = SCREEN_H - NAV_H
    w   = SCREEN_W // len(_NAV_PAGES)

    M5.Display.fillRect(0, y, SCREEN_W, NAV_H, C_CARD)
    M5.Display.drawFastHLine(0, y, SCREEN_W, C_BORDER)

    for i, label in enumerate(_NAV_PAGES):
        x       = i * w
        is_act  = (label == active)
        fg      = C_BLUE if is_act else C_MUTED
        M5.Display.setTextColor(fg, C_CARD)
        M5.Display.setTextSize(1)
        tw = len(label) * 6
        M5.Display.drawString(label, x + (w - tw) // 2, y + 10)
        if is_act:
            M5.Display.drawFastHLine(x + 4, y + 1, w - 8, C_BLUE)


def nav_tap_page(touch_x: int, touch_y: int) -> str | None:
    """
    Given a touch coordinate, return which nav page was tapped, or None.
    """
    if touch_y < SCREEN_H - NAV_H:
        return None
    w   = SCREEN_W // len(_NAV_PAGES)
    idx = touch_x // w
    if 0 <= idx < len(_NAV_PAGES):
        return _NAV_PAGES[idx]
    return None


# ── Metric card ───────────────────────────────────────────────────────────────

def draw_metric(x: int, y: int, w: int, h: int,
                label: str, value: str, unit: str = "",
                color: int = C_TEXT) -> None:
    """
    Draw a labelled metric box with value and optional unit.
    """
    M5.Display.fillRoundRect(x, y, w, h, 4, C_CARD)
    M5.Display.drawRoundRect(x, y, w, h, 4, C_BORDER)

    # Label
    M5.Display.setTextColor(C_MUTED, C_CARD)
    M5.Display.setTextSize(1)
    M5.Display.drawString(label, x + 5, y + 5)

    # Value
    M5.Display.setTextColor(color, C_CARD)
    M5.Display.setTextSize(2)
    val_str = value + " " + unit if unit else value
    M5.Display.drawString(val_str, x + 5, y + h // 2 - 4)


def draw_badge(x: int, y: int, label: str, color: int = C_GREEN) -> None:
    """Small coloured status badge (e.g. 'Good', 'Comfortable')."""
    w = len(label) * 6 + 10
    M5.Display.fillRoundRect(x, y, w, 14, 3, color)
    M5.Display.setTextColor(C_BG, color)
    M5.Display.setTextSize(1)
    M5.Display.drawString(label, x + 5, y + 3)


# ── Alert banner ──────────────────────────────────────────────────────────────

def draw_alert(message: str) -> None:
    """
    Full-width orange alert banner just above the nav bar.
    Use for: humidity < 40%, air quality poor, etc.
    """
    y = SCREEN_H - NAV_H - 18
    M5.Display.fillRect(0, y, SCREEN_W, 16, C_ORANGE)
    M5.Display.setTextColor(C_BG, C_ORANGE)
    M5.Display.setTextSize(1)
    M5.Display.drawString("⚠  " + message, 5, y + 4)


# ── Utility ───────────────────────────────────────────────────────────────────

def fmt_val(value, decimals: int = 1) -> str:
    """Format a numeric value, returning 'N/A' if None."""
    if value is None:
        return "N/A"
    if decimals == 0:
        return str(int(value))
    return "{:.{}f}".format(value, decimals)


def air_quality_color(level: str) -> int:
    """Return a colour matching the air quality classification."""
    return {
        "Excellent": C_GREEN,
        "Good":      C_GREEN,
        "Moderate":  C_YELLOW,
        "Poor":      C_ORANGE,
        "Hazardous": C_RED,
    }.get(level, C_MUTED)


def comfort_color(level: str) -> int:
    return {
        "Comfortable": C_GREEN,
        "Acceptable":  C_BLUE,
        "Too Dry":     C_ORANGE,
        "Too Humid":   C_ORANGE,
        "Too Cold":    C_BLUE,
        "Too Warm":    C_RED,
    }.get(level, C_MUTED)