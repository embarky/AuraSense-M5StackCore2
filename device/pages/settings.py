# pages/settings.py — WiFi configuration via AP + QR code.
# Navigate away by swiping right (back to Home).

import network
import socket
import time

import M5
from M5 import *

import config
from components import (
    SCREEN_W, SCREEN_H, STATUS_H,
    C_BG, C_PANEL, C_MUTED, C_TEXT, C_GREEN, C_RED,
    C_YELLOW, C_BORDER,
    draw_status_bar, draw_text,
)

_AP_SSID = "SmartSpace-Setup"
_CFG_URL = "http://192.168.4.1"

_FORM = (
    "HTTP/1.1 200 OK\r\nContent-Type: text/html;charset=utf-8\r\n"
    "Connection: close\r\n\r\n"
    "<!DOCTYPE html><html><head><meta charset='utf-8'>"
    "<meta name='viewport' content='width=device-width,initial-scale=1'>"
    "<title>WiFi Setup</title>"
    "<style>*{box-sizing:border-box}body{font-family:Arial;background:#0d1117;"
    "color:#e6edf3;display:flex;flex-direction:column;align-items:center;"
    "justify-content:center;min-height:100vh;padding:20px}"
    "h2{color:#58a6ff}label{display:block;color:#8b949e;font-size:12px;"
    "margin:10px 0 4px}input{width:100%;padding:12px;background:#161b22;"
    "color:#e6edf3;border:1px solid #21262d;border-radius:8px;font-size:15px}"
    "button{width:100%;margin-top:20px;padding:14px;background:#238636;"
    "color:#fff;border:none;border-radius:8px;font-size:16px;font-weight:bold}"
    "form{width:100%;max-width:360px}</style></head><body>"
    "<h2>WiFi Setup</h2>"
    "<form method='POST' action='/'>"
    "<label>WiFi Name (SSID)</label>"
    "<input name='ssid' placeholder='e.g. iot-unil' required autocomplete='off'>"
    "<label>Password</label>"
    "<input name='password' type='password' placeholder='Leave blank if open'>"
    "<button>Save &amp; Restart</button>"
    "</form></body></html>"
)
_OK = ("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n"
       "<body style='font-family:Arial;background:#0d1117;color:#3fb950;"
       "text-align:center;padding-top:40vh'><h2>Saved! Restarting...</h2></body>")
_ERR = ("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n"
        "<body style='font-family:Arial;background:#0d1117;color:#ff4444;"
        "text-align:center;padding-top:40vh'>"
        "<h2>SSID required</h2><a href='/' style='color:#58a6ff'>Try again</a></body>")


class SettingsPage:

    def on_enter(self) -> None:
        M5.Display.fillScreen(C_BG)
        draw_status_bar()
        self._draw_ui()
        self._start_ap()
        self._draw_qr()
        self._run_server()

    def update(self, **kwargs) -> None:
        pass   # settings page is blocking (web server runs inside on_enter)

    @staticmethod
    def _start_ap():
        ap = network.WLAN(network.AP_IF)
        ap.active(True)
        ap.config(essid=_AP_SSID, authmode=0)
        for _ in range(10):
            if ap.active(): break
            time.sleep_ms(200)

    @staticmethod
    def _stop_ap():
        network.WLAN(network.AP_IF).active(False)

    @staticmethod
    def _draw_ui():
        draw_text("WIFI SETUP", 5, STATUS_H + 4, 0xFFA500, C_BG, 2)
        draw_text("Swipe right to cancel.", 5, SCREEN_H - 14, C_MUTED, C_BG, 1)

    def _draw_qr(self):
        try:
            M5.Display.qrcode(
                "WIFI:S:{};T:nopass;P:;;".format(_AP_SSID),
                170, STATUS_H + 30, 130)
        except Exception:
            draw_text(_CFG_URL, 165, STATUS_H + 90, C_YELLOW, C_BG, 1)

        y = STATUS_H + 46
        for line, color in [
            ("1. Scan QR or join:",  C_TEXT),
            ("   " + _AP_SSID,       C_YELLOW),
            ("   (no password)",     C_MUTED),
            ("",                     C_TEXT),
            ("2. Open browser:",     C_TEXT),
            ("   " + _CFG_URL,       C_YELLOW),
            ("",                     C_TEXT),
            ("3. Enter WiFi & save.",C_TEXT),
        ]:
            draw_text(line, 5, y, color, C_BG, 1)
            y += 14

    def _run_server(self, timeout=300):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", 80))
        srv.listen(3)
        srv.settimeout(0.3)
        t0 = time.time()
        while time.time() - t0 < timeout:
            M5.update()
            # Swipe right detection to cancel
            if M5.BtnB.isPressed():
                break
            try:
                conn, _ = srv.accept()
                conn.settimeout(10)
                self._handle(conn)
                conn.close()
            except OSError:
                pass
        srv.close()
        self._stop_ap()

    def _handle(self, conn):
        try: raw = conn.recv(2048).decode("utf-8", "ignore")
        except Exception: return
        if "POST" in raw:
            ssid, pwd = _parse_post(raw)
            if ssid:
                conn.send(_OK.encode())
                time.sleep_ms(300)
                _save_wifi(ssid, pwd)
                import machine; machine.reset()
            else:
                conn.send(_ERR.encode())
        else:
            conn.send(_FORM.encode())


def _url_decode(s):
    s = s.replace("+", " ")
    r, i = "", 0
    while i < len(s):
        if s[i] == "%" and i + 2 < len(s):
            try: r += chr(int(s[i+1:i+3], 16)); i += 3; continue
            except ValueError: pass
        r += s[i]; i += 1
    return r

def _parse_post(raw):
    body = raw.split("\r\n\r\n", 1)[-1]
    p = {}
    for part in body.split("&"):
        if "=" in part:
            k, _, v = part.partition("=")
            p[k.strip()] = _url_decode(v.strip())
    return p.get("ssid", ""), p.get("password", "")

def _save_wifi(ssid, pwd):
    try:
        with open("config.py") as f: lines = f.readlines()
    except Exception: lines = []
    new = []; sw = pw = False
    for line in lines:
        if line.startswith("WIFI_SSID"):
            new.append('WIFI_SSID     = "{}"\n'.format(ssid)); sw = True
        elif line.startswith("WIFI_PASSWORD"):
            new.append('WIFI_PASSWORD = "{}"\n'.format(pwd)); pw = True
        else:
            new.append(line)
    if not sw: new.append('WIFI_SSID     = "{}"\n'.format(ssid))
    if not pw: new.append('WIFI_PASSWORD = "{}"\n'.format(pwd))
    with open("config.py", "w") as f: f.writelines(new)
    print("[Settings] Saved:", ssid)