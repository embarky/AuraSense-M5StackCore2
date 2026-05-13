# main.py — Smart Space entry point (UIFlow2).
#
# Interaction Logic (Redesigned):
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
                           play_wav_from_memory)
from components   import (SCREEN_W, SCREEN_H, STATUS_H,
                           C_BG, C_MUTED, C_GREEN, C_RED, C_BLUE,
                           PAGES, is_btnc_pressed,
                           draw_status_bar, update_rec_indicator, draw_text)
from pages.home     import HomePage
from pages.sensor   import SensorPage
from pages.settings import SettingsPage

# ── Constants ─────────────────────────────────────────────────────────────────
REC_WAV         = "/flash/rec.wav"
SENSOR_INTERVAL = 3     # Seconds
DRAW_INTERVAL   = 2     # Seconds
UPLOAD_INTERVAL = 5     # Seconds
RETRY_INTERVAL  = 10    # Seconds
LONG_PRESS_MS   = 600   # Threshold for switching to Settings

# ── Global State ──────────────────────────────────────────────────────────────
_current_name = "Home"
_pages       = {}
_hub         = None
_sensor_data = {}
_outdoor     = {}
_flask_ok    = False
_last_sensor = 0
_last_upload = 0
_last_retry  = 0
_last_draw   = 0


# ── Helpers ───────────────────────────────────────────────────────────────────

def _time_str():
    """
    Returns the current local time dynamically adjusted by NTP offset.
    The system RTC runs on UTC. We add the offset (e.g., +2 hours for CEST) here.
    """
    try:
        # MicroPython's time.time() returns seconds since Epoch (based on UTC).
        # Add 2 hours (7200 seconds) for Switzerland (CEST).
        local_sec = time.time() + (2 * 3600)
        t = time.localtime(local_sec)
        return "{:02d}:{:02d}".format(t[3], t[4])
    except Exception: 
        return "--:--"

def _current_page():
    return _pages.get(_current_name)

def _go_to(name: str):
    """Transition to a specific page by name."""
    global _current_name, _last_draw
    
    current = _current_page()
    if current and hasattr(current, "on_exit"):
        try: current.on_exit()
        except Exception: pass
            
    _current_name = name
    page = _current_page()
    if page:
        page.on_enter()
    _last_draw = 0 # Force immediate redraw upon entry

def _cycle_nav(delta: int):
    """Cycle between pages defined in PAGES (Home, Sensors)."""
    # If currently in Settings, jump back into the cycle at Home
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

    ok = record_while_held(REC_WAV, is_btnc_pressed, _status_cb)
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
    global _hub, _pages, _sensor_data

    M5.begin()
    Speaker.begin()
    Speaker.setVolume(config.SPK_VOLUME)

    M5.Display.fillScreen(C_BG)
    draw_text("SMART SPACE", 75, 95, 0xFFA500, C_BG, 2)
    draw_text("Initializing...", 95, 125, C_MUTED, C_BG, 1)

    try: _hub = SensorHub()
    except Exception as e: print("[Setup] SensorHub error:", e)

    _pages["Home"]     = HomePage()
    _pages["Sensors"]  = SensorPage()
    _pages["Settings"] = SettingsPage()

    # 1. Connect WiFi
    if wifi_connect(status_cb=lambda msg, col: draw_text(msg, 50, 150, col, C_BG, 1)):
        # 2. Sync Time via NTP (Keeps RTC at UTC standard time)
        sync_ntp()

    if _hub: _sensor_data = _hub.read_all()
    _go_to(_current_name)


# ── Main Loop ─────────────────────────────────────────────────────────────────

def loop():
    global _sensor_data, _outdoor, _flask_ok
    global _last_sensor, _last_upload, _last_retry, _last_draw

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
                while M5.BtnA.isPressed(): M5.update() # Wait for release
                break
        if not is_long:
            _cycle_nav(-1)
        return

    # ── Button B: Home Page (Short) ───────────────────────────────────────────
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
                if _current_name in ("Home", "Sensors"):
                    _do_voice()
                is_long = True
                while M5.BtnC.isPressed(): M5.update() # Wait for release
                break
        if not is_long:
            _cycle_nav(1)
        return

    # CRITICAL FIX: Use a monotonic clock (ticks_ms) instead of real-time (time.time())
    # This prevents the application from freezing if the NTP synchronizer shifts the RTC.
    now = time.ticks_ms()

    # ── Sensor read ───────────────────────────────────────────────────────────
    if time.ticks_diff(now, _last_sensor) >= SENSOR_INTERVAL * 1000:
        _last_sensor = now
        if _hub: _sensor_data = _hub.read_all()

    # ── Screen refresh ────────────────────────────────────────────────────────
    if time.ticks_diff(now, _last_draw) >= DRAW_INTERVAL * 1000:
        _last_draw = now
        page = _current_page()
        if page:
            if _current_name in ("Home", "Sensors"):
                page.update(
                    sensor_data=_sensor_data, outdoor=_outdoor,
                    time_str=_time_str(), wifi_ok=is_connected(), flask_ok=_flask_ok,
                )
            elif _current_name == "Settings":
                page.update()

    # ── Backend networking ────────────────────────────────────────────────────
    if is_connected() and _sensor_data:
        if _flask_ok:
            if time.ticks_diff(now, _last_upload) >= UPLOAD_INTERVAL * 1000:
                _last_upload = now
                _last_retry = now
                result = upload_sensor_data(_sensor_data)
                if result: _outdoor, _flask_ok = result, True
                else: _flask_ok = False
        else:
            if time.ticks_diff(now, _last_retry) >= RETRY_INTERVAL * 1000:
                _last_retry = now
                result = upload_sensor_data(_sensor_data)
                if result: _outdoor, _flask_ok = result, True

    time.sleep_ms(20)


if __name__ == "__main__":
    try:
        setup()
        while True: loop()
    except Exception as e:
        import sys; sys.print_exception(e)