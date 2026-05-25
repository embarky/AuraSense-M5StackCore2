# pages/settings.py — WiFi provisioning via captive portal for AuraSense.
# "AuraSense: See the air you breathe."
#
# Non-blocking design: WiFi connection attempt runs as a state machine
# in update(), so BtnB can exit at any time including during connection.

import network
import socket
import time
import machine
import M5
from M5 import *

from components import (
    SCREEN_W, SCREEN_H,
    C_BG, C_MUTED, C_TEXT, C_YELLOW, C_ORANGE, C_BLUE, C_GREEN, C_RED, draw_text,
)

_AP_SSID    = "AuraSense-Setup"
_LOCAL_IP   = "192.168.4.1"
_QR_CONTENT = "WIFI:S:{};T:nopass;;".format(_AP_SSID)

# Connection state machine
_STATE_IDLE       = 0
_STATE_CONNECTING = 1
_STATE_SUCCESS    = 2
_STATE_FAILED     = 3

# ── HTML ──────────────────────────────────────────────────────────────────────

_FORM = (
    "HTTP/1.1 200 OK\r\nContent-Type: text/html;charset=utf-8\r\nConnection: close\r\n\r\n"
    "<!DOCTYPE html><html><head><meta charset='utf-8'>"
    "<meta name='viewport' content='width=device-width,initial-scale=1'>"
    "<style>"
    "*{box-sizing:border-box;margin:0;padding:0}"
    "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;"
    "background:#f5f5f7;min-height:100vh;display:flex;flex-direction:column;"
    "align-items:center;justify-content:center;padding:32px 24px}"
    "h1{color:#1d1d1f;font-size:24px;font-weight:700;margin-bottom:6px}"
    "p{color:#86868b;font-size:14px;margin-bottom:28px;text-align:center}"
    ".card{width:100%;max-width:340px;background:#fff;border-radius:16px;"
    "padding:24px;box-shadow:0 2px 12px rgba(0,0,0,0.08)}"
    "label{display:block;color:#86868b;font-size:11px;font-weight:600;"
    "letter-spacing:0.6px;text-transform:uppercase;margin-bottom:6px}"
    "input{width:100%;padding:12px 14px;background:#f5f5f7;color:#1d1d1f;"
    "border:none;border-radius:10px;font-size:15px;outline:none}"
    ".gap{margin-top:14px}"
    "button{width:100%;margin-top:20px;padding:14px;background:#1a1a1a;"
    "color:#fff;border:none;border-radius:10px;font-size:15px;font-weight:600}"
    "footer{color:#c7c7cc;font-size:12px;margin-top:24px}"
    "</style></head><body>"
    "<h1>AuraSense</h1>"
    "<p>Enter your WiFi details to connect your device.</p>"
    "<div class='card'><form method='POST' action='/'>"
    "<label>Network Name</label>"
    "<input name='ssid' placeholder='e.g. Home WiFi' required autocomplete='off'>"
    "<div class='gap'><label>Password</label>"
    "<input name='password' type='password' placeholder='Leave blank if open'></div>"
    "<button type='submit'>Connect</button>"
    "</form></div>"
    "<footer>AuraSense &middot; See the air you breathe.</footer>"
    "</body></html>"
)

_OK = (
    "HTTP/1.1 200 OK\r\nContent-Type: text/html;charset=utf-8\r\nConnection: close\r\n\r\n"
    "<!DOCTYPE html><html><head><meta charset='utf-8'>"
    "<meta name='viewport' content='width=device-width,initial-scale=1'>"
    "<style>body{font-family:-apple-system,BlinkMacSystemFont,Arial,sans-serif;"
    "background:#f5f5f7;display:flex;flex-direction:column;align-items:center;"
    "justify-content:center;min-height:100vh;padding:24px;text-align:center}"
    "h2{color:#1d1d1f;font-size:22px;font-weight:700;margin-bottom:8px}"
    "p{color:#86868b;font-size:14px}</style></head><body>"
    "<h2>Connected!</h2>"
    "<p>Your device is restarting and will connect to the new network.</p>"
    "</body></html>"
)


class SettingsPage:

    def __init__(self):
        self._ap    = None
        self._dns   = None
        self._srv   = None
        # Connection state machine
        self._state      = _STATE_IDLE
        self._wlan       = None
        self._ssid       = ""
        self._pwd        = ""
        self._connect_t  = 0   # ticks_ms when connection started
        self._pending_conn = None  # HTTP conn waiting for response

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_enter(self) -> None:
        self._state = _STATE_IDLE
        self._draw_ui()
        self._start_ap()
        self._start_dns()
        self._start_server()

    def update(self, **kwargs) -> None:
        self._poll_dns()
        self._poll_http()
        self._poll_connection()

    def on_exit(self) -> None:
        # Abort any in-progress connection
        if self._state == _STATE_CONNECTING and self._wlan:
            try: self._wlan.disconnect()
            except Exception: pass
        self._state = _STATE_IDLE
        self._wlan  = None

        # Close pending HTTP connection if any
        if self._pending_conn:
            try: self._pending_conn.close()
            except Exception: pass
            self._pending_conn = None

        for attr in ("_srv", "_dns"):
            obj = getattr(self, attr, None)
            if obj:
                try: obj.close()
                except Exception: pass
                setattr(self, attr, None)
        if self._ap:
            try: self._ap.active(False)
            except Exception: pass
            self._ap = None

        # Give radio time to settle before AP restarts next entry
        time.sleep_ms(500)
        print("[AuraSense | Settings] AP + servers stopped")

    # ── AP ────────────────────────────────────────────────────────────────────

    def _start_ap(self) -> None:
        self._ap = network.WLAN(network.AP_IF)
        self._ap.active(True)
        self._ap.ifconfig((_LOCAL_IP, "255.255.255.0", _LOCAL_IP, "8.8.8.8"))
        self._ap.config(essid=_AP_SSID, authmode=0)
        for _ in range(10):
            if self._ap.active(): break
            time.sleep_ms(200)
        print("[AuraSense | Settings] AP active:", _AP_SSID, "@", _LOCAL_IP)

    # ── DNS ───────────────────────────────────────────────────────────────────

    def _start_dns(self) -> None:
        try:
            self._dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._dns.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._dns.bind(("0.0.0.0", 53))
            self._dns.settimeout(0)
            print("[AuraSense | Settings] DNS server ready")
        except Exception as e:
            print("[AuraSense | Settings] DNS error:", e)

    def _poll_dns(self) -> None:
        if not self._dns:
            return
        try:
            data, addr = self._dns.recvfrom(1024)
            reply = (data[:2]
                     + b"\x81\x80\x00\x01\x00\x01\x00\x00\x00\x00"
                     + data[12:]
                     + b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04"
                     + bytes(map(int, _LOCAL_IP.split("."))))
            self._dns.sendto(reply, addr)
        except OSError:
            pass

    # ── HTTP ──────────────────────────────────────────────────────────────────

    def _start_server(self) -> None:
        try:
            self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._srv.bind(("0.0.0.0", 80))
            self._srv.listen(2)
            self._srv.settimeout(0)
            print("[AuraSense | Settings] HTTP server ready")
        except Exception as e:
            print("[AuraSense | Settings] HTTP error:", e)

    def _poll_http(self) -> None:
        if not self._srv:
            return
        # Don't accept new connections while connecting
        if self._state == _STATE_CONNECTING:
            return
        try:
            conn, _ = self._srv.accept()
            conn.settimeout(3)
            try:
                raw = conn.recv(1024).decode("utf-8", "ignore")
            except Exception:
                conn.close()
                return

            if "POST" in raw:
                body = raw.split("\r\n\r\n", 1)[-1]
                ssid, pwd = _parse_form(body)
                if ssid:
                    # Start non-blocking connection attempt
                    self._ssid = ssid
                    self._pwd  = pwd
                    self._pending_conn = conn
                    self._start_connect()
                    return  # don't close conn yet
                else:
                    conn.send(_FORM.encode())
            else:
                conn.send(_FORM.encode())
            conn.close()
        except OSError:
            pass

    # ── Non-blocking connection state machine ─────────────────────────────────

    def _start_connect(self) -> None:
        self._state = _STATE_CONNECTING
        self._connect_t = time.ticks_ms()
        self._wlan = network.WLAN(network.STA_IF)
        self._wlan.active(True)
        self._wlan.disconnect()
        time.sleep_ms(300)
        self._wlan.connect(self._ssid, self._pwd)
        # Update screen
        M5.Display.fillRect(0, SCREEN_H // 2 - 10, 155, 20, C_BG)
        draw_text("Connecting...", 6, SCREEN_H // 2 - 6, C_YELLOW, C_BG, 1)
        print("[AuraSense | Settings] Connecting to:", self._ssid)

    def _poll_connection(self) -> None:
        if self._state != _STATE_CONNECTING:
            return

        if self._wlan and self._wlan.isconnected():
            # Success
            self._state = _STATE_SUCCESS
            M5.Display.fillRect(0, SCREEN_H // 2 - 10, 155, 20, C_BG)
            draw_text("Connected!", 6, SCREEN_H // 2 - 6, C_GREEN, C_BG, 1)
            if self._pending_conn:
                try:
                    self._pending_conn.send(_OK.encode())
                    self._pending_conn.close()
                except Exception:
                    pass
                self._pending_conn = None
            _save_wifi(self._ssid, self._pwd)
            time.sleep(1)
            machine.reset()

        elif time.ticks_diff(time.ticks_ms(), self._connect_t) > 10000:
            # Timeout — failed
            self._state = _STATE_FAILED
            if self._wlan:
                self._wlan.disconnect()
            M5.Display.fillRect(0, SCREEN_H // 2 - 10, 155, 20, C_BG)
            draw_text("Failed. Try again.", 6, SCREEN_H // 2 - 6, C_RED, C_BG, 1)
            if self._pending_conn:
                try:
                    err = _FORM.replace(
                        "<button type='submit'>Connect</button>",
                        "<p style='color:#ff3b30;font-size:13px;margin-top:12px'>"
                        "Connection failed. Check WiFi name and password.</p>"
                        "<button type='submit'>Try Again</button>"
                    )
                    self._pending_conn.send(err.encode())
                    self._pending_conn.close()
                except Exception:
                    pass
                self._pending_conn = None
            self._state = _STATE_IDLE

    # ── Screen ────────────────────────────────────────────────────────────────

    def _draw_ui(self) -> None:
        M5.Display.fillScreen(C_BG)

        y = 4
        try:
            Widgets.Label("WiFi Setup", 6, y, 1.0, C_ORANGE, C_BG, Widgets.FONTS.DejaVu18)
        except Exception:
            draw_text("WiFi Setup", 6, y, C_ORANGE, C_BG, 1)
        y += 30

        for line, color in [
            ("1. Join WiFi:",         C_MUTED),
            (_AP_SSID,                C_YELLOW),
            ("",                      C_TEXT),
            ("2. Open browser:",      C_MUTED),
            (_LOCAL_IP,               C_BLUE),
            ("",                      C_TEXT),
            ("3. Enter WiFi & Save.", C_MUTED),
        ]:
            draw_text(line, 6, y, color, C_BG, 1)
            y += 18

        draw_text("Press B to exit", 6, SCREEN_H - 14, C_MUTED, C_BG, 1)

        qr_size = 150
        qr_x    = 160
        qr_y    = (SCREEN_H - qr_size) // 2
        qr_drawn = False

        for method_name in ("qrcode", "drawQrcode", "drawQR"):
            if hasattr(M5.Display, method_name):
                try:
                    getattr(M5.Display, method_name)(_QR_CONTENT, qr_x, qr_y, qr_size, 4)
                    qr_drawn = True
                    print("[AuraSense | Settings] QR via M5.Display.{}".format(method_name))
                    break
                except Exception as e:
                    print("[AuraSense | Settings] {} failed: {}".format(method_name, e))

        if not qr_drawn:
            M5.Display.drawRect(qr_x, qr_y, qr_size, qr_size, 0x444444)
            draw_text("Open browser:", qr_x + 6, qr_y + 50, C_MUTED, C_BG, 1)
            draw_text(_LOCAL_IP,      qr_x + 6, qr_y + 70, C_YELLOW, C_BG, 2)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _url_decode(s: str) -> str:
    s = s.replace("+", " ")
    r, i = "", 0
    while i < len(s):
        if s[i] == "%" and i + 2 < len(s):
            try:
                r += chr(int(s[i + 1:i + 3], 16))
                i += 3
                continue
            except ValueError:
                pass
        r += s[i]
        i += 1
    return r


def _parse_form(body: str) -> tuple:
    p = {}
    for part in body.split("&"):
        if "=" in part:
            k, _, v = part.partition("=")
            p[k.strip()] = _url_decode(v.strip())
    return p.get("ssid", ""), p.get("password", "")


def _save_wifi(ssid: str, pwd: str) -> None:
    try:
        with open("config.py") as f:
            lines = f.readlines()
    except Exception:
        lines = []
    new = []
    sw = pw = False
    for line in lines:
        if line.startswith("WIFI_SSID"):
            new.append('WIFI_SSID     = "{}"\n'.format(ssid)); sw = True
        elif line.startswith("WIFI_PASSWORD"):
            new.append('WIFI_PASSWORD = "{}"\n'.format(pwd)); pw = True
        else:
            new.append(line)
    if not sw: new.append('WIFI_SSID     = "{}"\n'.format(ssid))
    if not pw: new.append('WIFI_PASSWORD = "{}"\n'.format(pwd))
    with open("config.py", "w") as f:
        for line in new:
            f.write(line)
    print("[AuraSense | Settings] Saved SSID:", ssid)