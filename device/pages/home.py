# pages/home.py — Main dashboard page.
#
# Layout (320 x 240):
#
#  ┌─────────────────────────────────────────────────────────────┐
#  │ 22:45              ●WiFi                        (status bar)│
#  ├────────────────────┬────────────────────────────────────────┤
#  │  🌡 INDOOR         │  💨 AIR QUALITY                        │
#  │  23.4°C            │  eCO2   450 ppm                        │
#  │  Humidity  45.2%   │  TVOC   120 ppb                        │
#  │  Pressure  1013hPa │  ████ Good                             │
#  ├────────────────────┼────────────────────────────────────────┤
#  │  🧮 CALCULATED     │  🏃 MOTION                             │
#  │  Dew pt   11.3°C   │  Detected  ●                           │
#  │  Abs hum  9.2g/m³  │                                        │
#  │  Feels    24.1°C   │  Comfortable                           │
#  ├────────────────────┴────────────────────────────────────────┤
#  │ ⚠ Alert banner (only shown when triggered)                  │
#  ├─────────────────────────────────────────────────────────────┤
#  │  [Home]          [Forecast]          [Settings]  (nav bar)  │
#  └─────────────────────────────────────────────────────────────┘

import M5
from M5 import *

from components import (
    C_BG, C_CARD, C_BORDER, C_TEXT, C_MUTED,
    C_GREEN, C_RED, C_BLUE, C_YELLOW, C_ORANGE, C_PURPLE,
    SCREEN_W, SCREEN_H, NAV_H, STATUS_H, CONTENT_Y,
    draw_status_bar, draw_nav_bar, nav_tap_page,
    draw_metric, draw_badge, draw_alert,
    fmt_val, air_quality_color, comfort_color,
)

# Alert thresholds (matches backend alert logic)
_HUMIDITY_LOW  = 40     # %
_HUMIDITY_HIGH = 70     # %
_ECO2_WARN     = 2000   # ppm


class HomePage:
    """
    Displays live sensor readings and derived environmental metrics.
    Handles navigation tap detection.
    """

    def __init__(self) -> None:
        self._data     = {}          # latest sensor dict from SensorHub
        self._outdoor  = {}          # outdoor data from backend response
        self._time_str = ""
        self._wifi_ok  = False

    # ── Public interface (called by main.py) ──────────────────────────────────

    def on_enter(self) -> None:
        """Called when navigating to this page. Full redraw."""
        self._draw_all()

    def update(self, sensor_data: dict, outdoor: dict,
               time_str: str, wifi_ok: bool) -> str | None:
        """
        Refresh the display with new data.

        Returns a page name string if a navigation tap was detected,
        otherwise returns None.
        """
        self._data     = sensor_data
        self._outdoor  = outdoor
        self._time_str = time_str
        self._wifi_ok  = wifi_ok
        self._draw_all()

        # Check for navigation tap
        M5.update()
        if M5.Touch.getCount() > 0:
            try:
                tx, ty = M5.Touch.getX(), M5.Touch.getY()
                return nav_tap_page(tx, ty)
            except Exception:
                pass
        return None

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw_all(self) -> None:
        M5.Display.fillRect(0, STATUS_H, SCREEN_W, SCREEN_H - STATUS_H - NAV_H, C_BG)
        draw_status_bar(self._time_str, self._wifi_ok)
        self._draw_indoor()
        self._draw_air_quality()
        self._draw_calculated()
        self._draw_motion()
        self._draw_alerts()
        draw_nav_bar("Home")

    def _draw_indoor(self) -> None:
        """Left column top: temperature, humidity, pressure."""
        d  = self._data
        x, y, w, h = 2, STATUS_H + 2, 155, 88

        M5.Display.fillRoundRect(x, y, w, h, 4, C_CARD)
        M5.Display.drawRoundRect(x, y, w, h, 4, C_BORDER)

        # Section title
        M5.Display.setTextColor(C_MUTED, C_CARD)
        M5.Display.setTextSize(1)
        M5.Display.drawString("INDOOR", x + 5, y + 5)

        # Temperature (large)
        M5.Display.setTextColor(C_BLUE, C_CARD)
        M5.Display.setTextSize(2)
        M5.Display.drawString(fmt_val(d.get("temperature")) + " C", x + 5, y + 18)

        # Humidity, pressure (small)
        M5.Display.setTextSize(1)
        M5.Display.setTextColor(C_TEXT, C_CARD)
        M5.Display.drawString(
            "Hum   " + fmt_val(d.get("humidity")) + " %", x + 5, y + 42)
        M5.Display.drawString(
            "Press " + fmt_val(d.get("pressure"), 0) + " hPa", x + 5, y + 55)

        # Outdoor (from backend)
        M5.Display.setTextColor(C_MUTED, C_CARD)
        out_temp = fmt_val(self._outdoor.get("outdoor_temp"))
        out_desc = str(self._outdoor.get("outdoor_desc", ""))[:12]
        M5.Display.drawString("Out " + out_temp + "C  " + out_desc, x + 5, y + 70)

    def _draw_air_quality(self) -> None:
        """Right column top: eCO2, TVOC, AQI badge."""
        d  = self._data
        x, y, w, h = 161, STATUS_H + 2, 157, 88

        M5.Display.fillRoundRect(x, y, w, h, 4, C_CARD)
        M5.Display.drawRoundRect(x, y, w, h, 4, C_BORDER)

        M5.Display.setTextColor(C_MUTED, C_CARD)
        M5.Display.setTextSize(1)
        M5.Display.drawString("AIR QUALITY", x + 5, y + 5)

        eco2  = d.get("eco2")
        tvoc  = d.get("tvoc")
        level = d.get("air_quality_level", "N/A")
        col   = air_quality_color(level)

        M5.Display.setTextColor(C_TEXT, C_CARD)
        M5.Display.drawString("eCO2  " + fmt_val(eco2, 0) + " ppm", x + 5, y + 20)
        M5.Display.drawString("TVOC  " + fmt_val(tvoc, 0) + " ppb", x + 5, y + 34)

        # AQI colour bar
        bar_w = int(w - 14)
        if eco2 is not None:
            fill = min(bar_w, max(4, bar_w * min(eco2, 5000) // 5000))
            M5.Display.fillRoundRect(x + 5, y + 52, bar_w, 8, 2, C_CARD)
            M5.Display.fillRoundRect(x + 5, y + 52, fill, 8, 2, col)

        # Badge
        draw_badge(x + 5, y + 66, level, col)

    def _draw_calculated(self) -> None:
        """Left column bottom: dew point, absolute humidity, feels like."""
        d  = self._data
        x, y, w, h = 2, STATUS_H + 94, 155, 86

        M5.Display.fillRoundRect(x, y, w, h, 4, C_CARD)
        M5.Display.drawRoundRect(x, y, w, h, 4, C_BORDER)

        M5.Display.setTextColor(C_MUTED, C_CARD)
        M5.Display.setTextSize(1)
        M5.Display.drawString("CALCULATED", x + 5, y + 5)

        rows = [
            ("Dew pt",  fmt_val(d.get("dew_point"))     + " C"),
            ("Abs hum", fmt_val(d.get("absolute_humidity")) + " g/m3"),
            ("Feels",   fmt_val(d.get("feels_like"))    + " C"),
        ]
        M5.Display.setTextColor(C_TEXT, C_CARD)
        for i, (label, val) in enumerate(rows):
            ly = y + 20 + i * 18
            M5.Display.setTextColor(C_MUTED, C_CARD)
            M5.Display.drawString(label, x + 5, ly)
            M5.Display.setTextColor(C_TEXT, C_CARD)
            M5.Display.drawString(val, x + 72, ly)

    def _draw_motion(self) -> None:
        """Right column bottom: motion sensor + comfort level."""
        d  = self._data
        x, y, w, h = 161, STATUS_H + 94, 157, 86

        M5.Display.fillRoundRect(x, y, w, h, 4, C_CARD)
        M5.Display.drawRoundRect(x, y, w, h, 4, C_BORDER)

        M5.Display.setTextColor(C_MUTED, C_CARD)
        M5.Display.setTextSize(1)
        M5.Display.drawString("MOTION", x + 5, y + 5)

        motion  = d.get("motion", False)
        dot_col = C_GREEN if motion else C_MUTED
        M5.Display.fillCircle(x + 14, y + 36, 7, dot_col)
        M5.Display.setTextColor(C_TEXT, C_CARD)
        M5.Display.drawString(
            "Detected" if motion else "No motion", x + 26, y + 30)

        # Comfort
        comfort = d.get("comfort_level", "N/A")
        col     = comfort_color(comfort)
        M5.Display.setTextColor(C_MUTED, C_CARD)
        M5.Display.drawString("Comfort", x + 5, y + 52)
        draw_badge(x + 5, y + 64, comfort, col)

    def _draw_alerts(self) -> None:
        """Show an alert banner if any threshold is exceeded."""
        d   = self._data
        hum = d.get("humidity")
        eco = d.get("eco2")

        msg = None
        if hum is not None and hum < _HUMIDITY_LOW:
            msg = "Humidity too low! ({:.0f}%) — consider a humidifier".format(hum)
        elif hum is not None and hum > _HUMIDITY_HIGH:
            msg = "Humidity too high! ({:.0f}%) — ventilate".format(hum)
        elif eco is not None and eco > _ECO2_WARN:
            msg = "Poor air quality! eCO2 {}ppm — open a window".format(eco)

        if msg:
            draw_alert(msg)