# pages/settings.py — WiFi configuration via AP mode + QR code.
#
# Flow:
#   1. Device switches to AP mode and hosts "SmartSpace-Setup"
#   2. QR code on screen encodes the config URL (auto-opens on most phones)
#   3. User scans QR → phone connects to AP → browser opens config page
#   4. User fills in new WiFi SSID + password → submits form
#   5. Credentials written to config.py → device restarts in STA mode
#
# The web page is mobile-friendly and matches the device dark theme.

import device.connectivity as connectivity
import socket
import time
import os

import M5
from M5 import *

import config
from components import (
    C_BG, C_CARD, C_BORDER, C_TEXT, C_MUTED,
    C_GREEN, C_RED, C_BLUE, C_YELLOW,
    SCREEN_W, SCREEN_H, NAV_H, STATUS_H,
    draw_nav_bar, draw_status_bar,
)

# ── AP configuration ──────────────────────────────────────────────────────────

_AP_SSID  = "SmartSpace-Setup"
_AP_PASS  = "12345678"           # min 8 chars for WPA2
_AP_IP    = "192.168.4.1"
_CFG_URL  = "http://192.168.4.1"

# ── HTML pages ────────────────────────────────────────────────────────────────

_HTML_FORM = """\
HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nConnection: close\r\n\r\n\
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>SmartSpace — WiFi Setup</title>
  <style>
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:Arial,sans-serif;background:#0d1117;color:#e6edf3;
         display:flex;flex-direction:column;align-items:center;
         justify-content:center;min-height:100vh;padding:24px}
    h2{color:#58a6ff;margin-bottom:6px;font-size:22px}
    p{color:#8b949e;font-size:13px;margin-bottom:24px}
    form{width:100%;max-width:360px}
    label{display:block;color:#8b949e;font-size:12px;margin:12px 0 4px}
    input{width:100%;padding:12px;background:#161b22;color:#e6edf3;
          border:1px solid #21262d;border-radius:8px;font-size:15px}
    input:focus{outline:none;border-color:#58a6ff}
    button{width:100%;margin-top:20px;padding:14px;background:#238636;
           color:#fff;border:none;border-radius:8px;font-size:16px;
           font-weight:bold;cursor:pointer}
    button:active{background:#2ea043}
  </style>
</head>
<body>
  <h2>WiFi Setup</h2>
  <p>Enter your home WiFi credentials below.</p>
  <form method="POST" action="/">
    <label>WiFi Name (SSID)</label>
    <input name="ssid" placeholder="e.g. iot-unil" required autocomplete="off">
    <label>Password</label>
    <input name="password" type="password" placeholder="Leave blank if open network">
    <button type="submit">Save &amp; Connect</button>
  </form>
</body>
</html>"""

_HTML_SUCCESS = """\
HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nConnection: close\r\n\r\n\
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>SmartSpace — Saved</title>
  <style>
    body{font-family:Arial,sans-serif;background:#0d1117;color:#e6edf3;
         display:flex;flex-direction:column;align-items:center;
         justify-content:center;min-height:100vh;text-align:center;padding:24px}
    h2{color:#3fb950;font-size:24px;margin-bottom:12px}
    p{color:#8b949e}
  </style>
</head>
<body>
  <h2>✓ Saved!</h2>
  <p>The device is restarting and will connect to your WiFi.<br>
     This page will close. You can close this tab.</p>
</body>
</html>"""

_HTML_ERROR = """\
HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nConnection: close\r\n\r\n\
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>SmartSpace — Error</title>
  <style>
    body{font-family:Arial,sans-serif;background:#0d1117;color:#e6edf3;
         display:flex;flex-direction:column;align-items:center;
         justify-content:center;min-height:100vh;text-align:center;padding:24px}
    h2{color:#ff4444;font-size:24px;margin-bottom:12px}
    a{color:#58a6ff}
  </style>
</head>
<body>
  <h2>✗ SSID missing</h2>
  <p><a href="/">← Try again</a></p>
</body>
</html>"""


class SettingsPage:
    """
    WiFi provisioning page.

    Opens an AP, shows a QR code and instructions, then serves a single-page
    web form.  On form submission the new credentials are written to config.py
    and the device restarts.
    """

    def on_enter(self) -> None:
        """Called when the user navigates to Settings."""
        self._draw_setup_screen()
        self._start_ap()
        self._draw_qr_and_info()
        self._run_web_server()   # blocks until config saved or timeout

    def update(self, **kwargs) -> str | None:
        """Settings page does not auto-navigate. Returns None."""
        M5.update()
        if M5.Touch.getCount() > 0:
            try:
                from components import nav_tap_page
                tx, ty = M5.Touch.getX(), M5.Touch.getY()
                return nav_tap_page(tx, ty)
            except Exception:
                pass
        return None

    # ── AP control ────────────────────────────────────────────────────────────

    @staticmethod
    def _start_ap() -> None:
        ap = connectivity.WLAN(connectivity.AP_IF)
        ap.active(True)
        ap.config(essid=_AP_SSID, password=_AP_PASS, authmode=3)  # WPA2
        # Wait for AP to be ready
        for _ in range(10):
            if ap.active():
                break
            time.sleep_ms(200)
        print("[Settings] AP started:", _AP_SSID)

    @staticmethod
    def _stop_ap() -> None:
        ap = connectivity.WLAN(connectivity.AP_IF)
        ap.active(False)

    # ── Drawing ───────────────────────────────────────────────────────────────

    @staticmethod
    def _draw_setup_screen() -> None:
        M5.Display.fillScreen(C_BG)
        draw_status_bar("", False)

        M5.Display.setTextColor(C_BLUE, C_BG)
        M5.Display.setTextSize(2)
        M5.Display.drawString("WiFi Setup", 10, STATUS_H + 6)

        M5.Display.setTextColor(C_MUTED, C_BG)
        M5.Display.setTextSize(1)
        M5.Display.drawString("Starting access point...", 10, STATUS_H + 30)

        draw_nav_bar("Settings")

    def _draw_qr_and_info(self) -> None:
        """
        Draw QR code (UIFlow2 built-in) + text instructions.
        Falls back to text-only if Widgets.QRCode is unavailable.
        """
        qr_size  = 110
        qr_x     = SCREEN_W - qr_size - 8
        qr_y     = STATUS_H + 4
        info_x   = 8
        info_y   = STATUS_H + 30

        # ── QR code (encodes the config URL) ─────────────────────────────────
        try:
            Widgets.QRCode(_CFG_URL, qr_x, qr_y, qr_size, 0xFFFFFF, 0x000000)
        except Exception:
            # Fallback: just show URL text
            M5.Display.setTextColor(C_YELLOW, C_BG)
            M5.Display.setTextSize(1)
            M5.Display.drawString(_CFG_URL, qr_x, qr_y + 50)

        # ── Instructions ──────────────────────────────────────────────────────
        M5.Display.setTextColor(C_TEXT, C_BG)
        M5.Display.setTextSize(1)

        lines = [
            "1. Scan QR or connect to:",
            "",
            "   WiFi: " + _AP_SSID,
            "   Pass: " + _AP_PASS,
            "",
            "2. Open browser:",
            "   " + _CFG_URL,
            "",
            "3. Enter WiFi credentials",
            "   and tap Save.",
        ]
        for i, line in enumerate(lines):
            color = C_YELLOW if "WiFi:" in line or "Pass:" in line or _CFG_URL in line else C_MUTED
            M5.Display.setTextColor(color, C_BG)
            M5.Display.drawString(line, info_x, info_y + i * 14)

        print("[Settings] AP:", _AP_SSID, "/ URL:", _CFG_URL)

    # ── Web server ────────────────────────────────────────────────────────────

    def _run_web_server(self, timeout: int = 300) -> None:
        """
        Serve the WiFi config form until credentials are submitted or
        timeout (seconds) is reached.
        """
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", 80))
        srv.listen(3)
        srv.settimeout(timeout)

        print("[Settings] Web server listening on port 80")
        t_start = time.time()

        try:
            while time.time() - t_start < timeout:
                try:
                    conn, addr = srv.accept()
                    conn.settimeout(10)
                    self._handle_request(conn)
                    conn.close()
                except OSError:
                    # Accept timed out — keep waiting
                    pass
        except Exception as e:
            print("[Settings] Server error:", e)
        finally:
            srv.close()
            self._stop_ap()

    def _handle_request(self, conn) -> None:
        """Parse HTTP request and serve form or save credentials."""
        try:
            raw = conn.recv(2048).decode("utf-8", "ignore")
        except Exception:
            return

        if "POST" in raw:
            ssid, password = self._parse_form_data(raw)
            if ssid:
                self._save_credentials(ssid, password)
                conn.send(_HTML_SUCCESS.encode())
                time.sleep_ms(500)
                import machine
                machine.reset()
            else:
                conn.send(_HTML_ERROR.encode())
        else:
            # GET — serve the config form
            conn.send(_HTML_FORM.encode())

    @staticmethod
    def _parse_form_data(raw: str) -> tuple:
        """Extract ssid and password from a URL-encoded POST body."""
        body = raw.split("\r\n\r\n", 1)[-1]
        params = {}
        for part in body.split("&"):
            if "=" in part:
                k, _, v = part.partition("=")
                params[k.strip()] = _url_decode(v.strip())
        return params.get("ssid", ""), params.get("password", "")

    @staticmethod
    def _save_credentials(ssid: str, password: str) -> None:
        """
        Overwrite config.py with updated WiFi credentials.
        All other settings are preserved verbatim.
        """
        # Read existing config to preserve other settings
        try:
            with open("config.py") as f:
                lines = f.readlines()
        except Exception:
            lines = []

        new_lines = []
        ssid_written = False
        pass_written = False

        for line in lines:
            if line.startswith("WIFI_SSID"):
                new_lines.append('WIFI_SSID     = "{}"\n'.format(ssid))
                ssid_written = True
            elif line.startswith("WIFI_PASSWORD"):
                new_lines.append('WIFI_PASSWORD = "{}"\n'.format(password))
                pass_written = True
            else:
                new_lines.append(line)

        # Append if not found in existing file
        if not ssid_written:
            new_lines.append('WIFI_SSID     = "{}"\n'.format(ssid))
        if not pass_written:
            new_lines.append('WIFI_PASSWORD = "{}"\n'.format(password))

        with open("config.py", "w") as f:
            f.writelines(new_lines)

        print("[Settings] Saved — SSID:", ssid)


# ── URL decode helper ─────────────────────────────────────────────────────────

def _url_decode(s: str) -> str:
    """Decode percent-encoded URL string (e.g. %21 → !)."""
    s = s.replace("+", " ")
    result = ""
    i = 0
    while i < len(s):
        if s[i] == "%" and i + 2 < len(s):
            try:
                result += chr(int(s[i + 1:i + 3], 16))
                i += 3
                continue
            except ValueError:
                pass
        result += s[i]
        i += 1
    return result