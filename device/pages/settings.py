# pages/settings.py — WiFi provisioning via captive portal.
#
# Flow:
#   1. Device opens AP "SmartSpace-Setup" (no password)
#   2. DNS server hijacks all requests → phone auto-opens browser
#   3. QR code on right side for instant phone connection
#   4. Left side shows manual steps as fallback
#   5. User fills SSID + password → device saves to config.py → restarts
#
# Both DNS and HTTP servers are non-blocking (settimeout=0),
# so main.py loop keeps running: swipe exits, sensors keep uploading.

import network
import socket
import time
import machine
import M5
from M5 import *

import config
from components import (
    SCREEN_W, SCREEN_H, STATUS_H,
    C_BG, C_MUTED, C_TEXT, C_YELLOW, C_ORANGE, C_BLUE, C_GREEN, draw_text,
)

_AP_SSID   = "SmartSpace-Setup"
_LOCAL_IP  = "192.168.4.1"
_QR_CONTENT = "WIFI:S:{};T:nopass;;".format(_AP_SSID)

# ── HTML served to phones ─────────────────────────────────────────────────────

_FORM = (
    "HTTP/1.1 200 OK\r\nContent-Type: text/html;charset=utf-8\r\nConnection: close\r\n\r\n"
    "<!DOCTYPE html><html><head><meta charset='utf-8'>"
    "<meta name='viewport' content='width=device-width,initial-scale=1'>"
    "<style>*{box-sizing:border-box}"
    "body{font-family:Arial;background:#0d1117;color:#e6edf3;"
    "display:flex;flex-direction:column;align-items:center;"
    "justify-content:center;min-height:100vh;padding:24px}"
    "h2{color:#58a6ff;margin-bottom:6px}"
    "p{color:#8b949e;font-size:13px;margin-bottom:20px}"
    "label{display:block;color:#8b949e;font-size:12px;margin:10px 0 4px}"
    "input{width:100%;padding:12px;background:#161b22;color:#e6edf3;"
    "border:1px solid #21262d;border-radius:8px;font-size:15px}"
    "button{width:100%;margin-top:20px;padding:14px;background:#238636;"
    "color:#fff;border:none;border-radius:8px;font-size:16px;font-weight:bold}"
    "form{width:100%;max-width:360px}</style></head><body>"
    "<h2>Smart Space Setup</h2>"
    "<p>Connect your device to home WiFi.</p>"
    "<form method='POST' action='/'>"
    "<label>WiFi Name (SSID)</label>"
    "<input name='ssid' placeholder='e.g. iot-unil' required autocomplete='off'>"
    "<label>Password</label>"
    "<input name='password' type='password' placeholder='Leave blank if open'>"
    "<button>Save &amp; Restart</button>"
    "</form></body></html>"
)
_OK = (
    "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n"
    "<body style='font-family:Arial;background:#0d1117;color:#3fb950;"
    "text-align:center;padding-top:40vh'><h2>Saved! Restarting...</h2></body>"
)
_ERR = (
    "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n"
    "<body style='font-family:Arial;background:#0d1117;color:#ff4444;"
    "text-align:center;padding-top:40vh'>"
    "<h2>SSID required</h2><a href='/' style='color:#58a6ff'>Try again</a></body>"
)


class SettingsPage:

    def __init__(self):
        self._ap  = None
        self._dns = None   # UDP socket — hijacks DNS to trigger captive portal
        self._srv = None   # TCP socket — serves HTML config page

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_enter(self) -> None:
        self._draw_ui()
        self._start_ap()
        self._start_dns()
        self._start_server()

    def update(self, **kwargs) -> None:
        """Called every loop iteration. Polls DNS + HTTP sockets (non-blocking)."""
        self._poll_dns()
        self._poll_http()

    def on_exit(self) -> None:
        """Stop all services when user swipes away."""
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
        print("[Settings] AP + servers stopped")

    # ── AP ────────────────────────────────────────────────────────────────────

    def _start_ap(self) -> None:
        self._ap = network.WLAN(network.AP_IF)
        self._ap.active(True)
        self._ap.ifconfig((_LOCAL_IP, "255.255.255.0", _LOCAL_IP, "8.8.8.8"))
        self._ap.config(essid=_AP_SSID, authmode=0)
        for _ in range(10):
            if self._ap.active(): break
            time.sleep_ms(200)
        print("[Settings] AP active:", _AP_SSID, "@", _LOCAL_IP)

    # ── DNS captive portal ────────────────────────────────────────────────────

    def _start_dns(self) -> None:
        """
        Non-blocking UDP server on port 53.
        Responds to any DNS query with our local IP so the phone's
        'captive portal detection' fires and auto-opens the browser.
        """
        try:
            self._dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._dns.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._dns.bind(("0.0.0.0", 53))
            self._dns.settimeout(0)
            print("[Settings] DNS server ready")
        except Exception as e:
            print("[Settings] DNS error:", e)

    def _poll_dns(self) -> None:
        if not self._dns:
            return
        try:
            data, addr = self._dns.recvfrom(1024)
            # Minimal DNS response: redirect everything to _LOCAL_IP
            reply = (data[:2]
                     + b"\x81\x80\x00\x01\x00\x01\x00\x00\x00\x00"
                     + data[12:]
                     + b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04"
                     + bytes(map(int, _LOCAL_IP.split("."))))
            self._dns.sendto(reply, addr)
        except OSError:
            pass   # no packet waiting

    # ── HTTP server ───────────────────────────────────────────────────────────

    def _start_server(self) -> None:
        try:
            self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._srv.bind(("0.0.0.0", 80))
            self._srv.listen(2)
            self._srv.settimeout(0)   # non-blocking
            print("[Settings] HTTP server ready")
        except Exception as e:
            print("[Settings] HTTP error:", e)

    def _poll_http(self) -> None:
        if not self._srv:
            return
        try:
            conn, _ = self._srv.accept()
            conn.settimeout(5)
            self._handle(conn)
            conn.close()
        except OSError:
            pass   # no connection waiting

    def _handle(self, conn) -> None:
        try:
            raw = conn.recv(1024).decode("utf-8", "ignore")
        except Exception:
            return

        if "POST" in raw:
            body  = raw.split("\r\n\r\n", 1)[-1]
            ssid, pwd = _parse_form(body)
            if ssid:
                conn.send(_OK.encode())
                time.sleep_ms(300)
                _save_wifi(ssid, pwd)
                machine.reset()
            else:
                conn.send(_ERR.encode())
        else:
            conn.send(_FORM.encode())

    # ── Screen ────────────────────────────────────────────────────────────────

    def _draw_ui(self) -> None:
        M5.Display.fillScreen(C_BG)

        # ── Left: manual instructions ─────────────────────────────────────────
        y = 4
        lbl = Widgets.Label("WiFi Setup", 6, y, 1.0,
                        C_ORANGE, C_BG, Widgets.FONTS.DejaVu18)
        y += 30

        for line, color in [
            ("1. Join WiFi:",    C_MUTED),
            (_AP_SSID,          C_YELLOW),
            ("",                C_TEXT),
            ("2. Open browser:", C_MUTED),
            (_LOCAL_IP,         C_BLUE),
            ("",                C_TEXT),
            ("3. Enter WiFi & Save.",   C_MUTED),
        ]:
            draw_text(line, 6, y, color, C_BG, 1)
            y += 18

        draw_text("Swipe right to exit", 6, SCREEN_H - 14, C_MUTED, C_BG, 1)

        # ── Right: QR code (dynamic API detection) ────────────────────────────

        qr_size = 150
        qr_x = 160
        qr_y = (SCREEN_H - qr_size) // 2 
        qr_drawn = False

        # Try each known API variant in order
        for method_name in ("qrcode", "drawQrcode", "drawQR"):
            if hasattr(M5.Display, method_name):
                try:
                    getattr(M5.Display, method_name)(_QR_CONTENT, qr_x, qr_y, qr_size, 4)
                    qr_drawn = True
                    print("[Settings] QR via M5.Display.{}".format(method_name))
                    break
                except Exception as e:
                    print("[Settings] {} failed: {}".format(method_name, e))

        if not qr_drawn:
            # Fallback: plain URL text in a box
            M5.Display.drawRect(qr_x, qr_y, qr_size, qr_size, 0x444444)
            draw_text("Open browser:", qr_x + 6, qr_y + 50, C_MUTED, C_BG, 1)
            draw_text(_LOCAL_IP,      qr_x + 6, qr_y + 70, C_YELLOW, C_BG, 2)
            print("[Settings] QR not available, showing URL")


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
    """Overwrite WIFI_SSID and WIFI_PASSWORD in config.py, preserve all other settings."""
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
        f.writelines(new)
    print("[Settings] Saved SSID:", ssid)