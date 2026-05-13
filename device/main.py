# main.py — Smart Space entry point (UIFlow2).
#
# Interaction Logic:
#   BtnA (Left):   Short -> Prev Page | Long (600ms) -> Enter Settings
#   BtnB (Center): Short -> Home Page
#   BtnC (Right):  Short -> Next Page | Long -> Voice Assistant

import time
import M5
from M5 import *

import config
from sensors      import SensorHub
from connectivity import (wifi_connect, sync_ntp, is_connected, upload_sensor_data,
                           record_while_held, upload_voice_and_receive,
                           play_wav_from_memory, fetch_forecast)
from components   import (SCREEN_W, SCREEN_H, STATUS_H,
                           C_BG, C_MUTED, C_GREEN, C_RED, C_BLUE,
                           PAGES, weather_icon,
                           draw_status_bar, update_rec_indicator, draw_text)
from pages.home     import HomePage
from pages.sensor   import SensorPage
from pages.weather  import WeatherPage
from pages.settings import SettingsPage

# ── Constants ─────────────────────────────────────────────────────────────────
REC_WAV           = "/flash/rec.wav"
SENSOR_INTERVAL   = 3000     # ms
DRAW_INTERVAL     = 2000     # ms
UPLOAD_INTERVAL   = 5000     # ms
RETRY_INTERVAL    = 10000    # ms
FORECAST_INTERVAL = 3600000  # ms (1 hour)
LONG_PRESS_MS     = 600

# ── Global State ──────────────────────────────────────────────────────────────
_current_name  = "Home"
_pages         = {}
_hub           = None
_sensor_data   = {}
_outdoor       = {}
_forecast      = []
_flask_ok      = False
_last_sensor   = 0
_last_upload   = 0
_last_retry    = 0
_last_draw     = 0
_last_forecast   = 0
_prev_flask_ok  = False   # detect backend connection event


# ── Helpers ───────────────────────────────────────────────────────────────────

def _time_str():
    try:
        local_sec = time.time() + (2 * 3600)
        t = time.localtime(local_sec)
        return "{:02d}:{:02d}".format(t[3], t[4])
    except Exception:
        return "--:--"

def _current_page():
    return _pages.get(_current_name)

def _go_to(name):
    global _current_name, _last_draw
    current = _current_page()
    if current and hasattr(current, "on_exit"):
        try: current.on_exit()
        except Exception: pass
    _current_name = name
    page = _current_page()
    if page:
        page.on_enter()
    _last_draw = 0

def _cycle_nav(delta):
    try:
        curr_idx = PAGES.index(_current_name)
    except ValueError:
        curr_idx = 0
    new_idx = (curr_idx + delta) % len(PAGES)
    _go_to(PAGES[new_idx])


# ── Voice Assistant ───────────────────────────────────────────────────────────

def _do_voice():
    global _flask_ok
    _rec_sec = [0]

    def _status_cb(msg, color):
        if "REC" in msg and "s" in msg:
            try: _rec_sec[0] = int(msg.strip().split()[-1].replace("s", ""))
            except Exception: pass
        update_rec_indicator(_rec_sec[0])

    # isPressed() maintains hold across 1s recording chunks
    ok = record_while_held(REC_WAV, lambda: M5.BtnC.isPressed(), _status_cb)
    update_rec_indicator(0)

    if not ok: return

    if not is_connected():
        draw_text(" No WiFi ", 90, 110, C_RED, C_BG, 2)
        time.sleep(1)
        _current_page().on_enter()
        return

    draw_text("Uploading...", 75, 110, C_BLUE, C_BG, 2)
    audio = upload_voice_and_receive(REC_WAV)

    if audio and len(audio) > 44:
        _flask_ok = True
        draw_text(" Playing... ", 80, 110, C_GREEN, C_BG, 2)
        play_wav_from_memory(audio)
    else:
        _flask_ok = False
        draw_text(" No reply  ", 80, 110, C_MUTED, C_BG, 2)
        time.sleep(1)

    _current_page().on_enter()


# ── Setup ─────────────────────────────────────────────────────────────────────

def setup():
    global _hub, _pages, _sensor_data, _forecast

    M5.begin()
    Speaker.begin()
    Speaker.setVolume(config.SPK_VOLUME)

    M5.Display.fillScreen(C_BG)
    draw_text("SMART SPACE",    75, 95,  0xFFA500, C_BG, 2)
    draw_text("Initializing...", 95, 125, C_MUTED,  C_BG, 1)

    try: _hub = SensorHub()
    except Exception as e: print("[Setup] SensorHub error:", e)

    _pages["Home"]     = HomePage()
    _pages["Sensors"]  = SensorPage()
    _pages["Weather"]  = WeatherPage()
    _pages["Settings"] = SettingsPage()

    if wifi_connect(status_cb=lambda msg, col: draw_text(msg, 50, 150, col, C_BG, 1)):
        sync_ntp()
        # Fetch forecast immediately on boot
        data = fetch_forecast()
        if data: _forecast = data

    if _hub: _sensor_data = _hub.read_all()
    _go_to(_current_name)


# ── Main Loop ─────────────────────────────────────────────────────────────────

def loop():
    global _sensor_data, _outdoor, _flask_ok, _forecast, _prev_flask_ok
    global _last_sensor, _last_upload, _last_retry, _last_draw, _last_forecast

    M5.update()

    # ── Button A: Prev Page (Short) | Settings (Long) ─────────────────────────
    if M5.BtnA.wasPressed():
        t0 = time.ticks_ms()
        is_long = False
        while M5.BtnA.isPressed():
            M5.update()
            if time.ticks_diff(time.ticks_ms(), t0) >= LONG_PRESS_MS:
                _go_to("Settings")
                is_long = True
                while M5.BtnA.isPressed(): M5.update()
                break
        if not is_long:
            _cycle_nav(-1)
        return

    # ── Button B: Home Page ───────────────────────────────────────────────────
    if M5.BtnB.wasPressed():
        _go_to("Home")
        return

    # ── Button C: Next Page (Short) | Voice Assistant (Long) ──────────────────
    if M5.BtnC.wasPressed():
        t0 = time.ticks_ms()
        is_long = False
        while M5.BtnC.isPressed():
            M5.update()
            if time.ticks_diff(time.ticks_ms(), t0) >= config.HOLD_TO_REC_MS:
                if _current_name in ("Home", "Sensors", "Weather"):
                    _do_voice()
                is_long = True
                while M5.BtnC.isPressed(): M5.update()
                break
        if not is_long:
            _cycle_nav(1)
        return

    now = time.ticks_ms()

    # ── Sensor read ───────────────────────────────────────────────────────────
    if time.ticks_diff(now, _last_sensor) >= SENSOR_INTERVAL:
        _last_sensor = now
        if _hub: _sensor_data = _hub.read_all()

    # ── Screen refresh ────────────────────────────────────────────────────────
    if time.ticks_diff(now, _last_draw) >= DRAW_INTERVAL:
        _last_draw = now
        page = _current_page()
        if page:
            if _current_name in ("Home", "Sensors"):
                page.update(
                    sensor_data=_sensor_data, outdoor=_outdoor,
                    time_str=_time_str(), wifi_ok=is_connected(), flask_ok=_flask_ok,
                )
            elif _current_name == "Weather":
                page.update(
                    forecast=_forecast,
                    time_str=_time_str(), wifi_ok=is_connected(), flask_ok=_flask_ok,
                )
            elif _current_name == "Settings":
                page.update()

    # ── Backend networking ────────────────────────────────────────────────────
    if is_connected() and _sensor_data:
        if _flask_ok:
            if time.ticks_diff(now, _last_upload) >= UPLOAD_INTERVAL:
                _last_upload = now
                _last_retry  = now
                result = upload_sensor_data(_sensor_data)
                if result: _outdoor, _flask_ok = result, True
                else: _flask_ok = False
        else:
            if time.ticks_diff(now, _last_retry) >= RETRY_INTERVAL:
                _last_retry = now
                result = upload_sensor_data(_sensor_data)
                if result: _outdoor, _flask_ok = result, True

    # ── Detect backend just came online → fetch forecast immediately ──────────
    if _flask_ok and not _prev_flask_ok:
        data = fetch_forecast()
        if data:
            _forecast = data
            _last_forecast = now
    _prev_flask_ok = _flask_ok

    # ── Forecast fetch (every hour) ───────────────────────────────────────────
    if is_connected():
        if time.ticks_diff(now, _last_forecast) >= FORECAST_INTERVAL:
            _last_forecast = now
            data = fetch_forecast()
            if data: _forecast = data

    time.sleep_ms(20)

        # ── Weather page touch (needs per-frame polling, not just DRAW_INTERVAL) ──
    if _current_name == "Weather":
        page = _current_page()
        if page:
            page.poll_touch()


if __name__ == "__main__":
    try:
        setup()
        while True: loop()
    except Exception as e:
        import sys; sys.print_exception(e)