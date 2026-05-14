# main.py — Smart Space entry point (UIFlow2).
#
# Interaction Logic:
#   BtnA (Left):   Short -> Prev Page | Long (600ms) -> Enter Settings
#   BtnB (Center): Short -> Home Page
#   BtnC (Right):  Short -> Next Page | Long -> Voice Assistant

import time
import M5
from M5 import *

# Try importing hardware for global LED control
try:
    import hardware
    _HAS_HARDWARE = True
except ImportError:
    _HAS_HARDWARE = False

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
SENSOR_INTERVAL   = 3000
DRAW_INTERVAL     = 2000
UPLOAD_INTERVAL   = 5000
RETRY_INTERVAL    = 10000
FORECAST_INTERVAL = 3600000
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
_last_forecast = 0
_prev_flask_ok = False

# Global LED State
_rgb_bar       = None
_led_state     = False
_last_led_tick = 0

# ── Date/time helpers ─────────────────────────────────────────────────────────
_DAYS   = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
_MONTHS = ["Jan","Feb","Mar","Apr","May","Jun",
           "Jul","Aug","Sep","Oct","Nov","Dec"]

def _time_str():
    try:
        local_sec = time.time() + (2 * 3600)
        t = time.localtime(local_sec)
        return "{:02d}:{:02d}".format(t[3], t[4])
    except Exception:
        return "--:--"

def _date_str():
    try:
        local_sec = time.time() + (2 * 3600)
        t = time.localtime(local_sec)
        return "{}  {:02d} {}".format(
            _DAYS[t[6]].upper(), t[2], _MONTHS[t[1] - 1].upper()
        )
    except Exception:
        return ""

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

# ── Global LED Alert Engine ───────────────────────────────────────────────────
def global_led_alert():
    """Runs continuously in the main loop to provide cross-page hardware alerts"""
    global _led_state, _last_led_tick
    if not _HAS_HARDWARE or not _rgb_bar: 
        return

    eco2 = _sensor_data.get("eco2", 0) if _sensor_data else 0
    tvoc = _sensor_data.get("tvoc", 0) if _sensor_data else 0
    
    # Safe fallback if values are None
    eco2 = eco2 if eco2 is not None else 0
    tvoc = tvoc if tvoc is not None else 0

    if eco2 > 1000 or tvoc > 300:
        color = 0xFF0000
        interval = 250
    elif eco2 > 800 or tvoc > 150:
        color = 0xFFFF00
        interval = 500
    else:
        # Normal state: Keep hardware silent/off
        if _led_state:
            _rgb_bar.fill_color(0x000000)
            _led_state = False
        return

    # Blinking logic
    now = time.ticks_ms()
    if time.ticks_diff(now, _last_led_tick) > interval:
        _last_led_tick = now
        _led_state = not _led_state
        if _led_state:
            _rgb_bar.fill_color(color)
        else:
            _rgb_bar.fill_color(0x000000)

# ── Voice Assistant ───────────────────────────────────────────────────────────
def _do_voice():
    global _flask_ok
    _rec_sec = [0]

    def _status_cb(msg, color):
        if "REC" in msg and "s" in msg:
            try: _rec_sec[0] = int(msg.strip().split()[-1].replace("s", ""))
            except Exception: pass
        update_rec_indicator(_rec_sec[0])

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
    global _hub, _pages, _sensor_data, _forecast, _rgb_bar

    M5.begin()
    Speaker.begin()
    Speaker.setVolume(config.SPK_VOLUME)
    
    # Initialize Global Hardware LED
    if _HAS_HARDWARE:
        try:
            _rgb_bar = hardware.RGB(io=25, n=10, type="SK6812")
            _rgb_bar.fill_color(0x000000) # Ensure it's off
        except Exception as e:
            print("[Setup] RGB Init error:", e)

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
        data = fetch_forecast()
        if data: _forecast = data

    if _hub: _sensor_data = _hub.read_all()
    _go_to(_current_name)

# ── Main Loop ─────────────────────────────────────────────────────────────────
def loop():
    global _sensor_data, _outdoor, _flask_ok, _forecast, _prev_flask_ok
    global _last_sensor, _last_upload, _last_retry, _last_draw, _last_forecast

    M5.update()
    
    # Run the global LED alert engine every tick (approx 20ms)
    global_led_alert()

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

    # ── Weather page touch (per-frame for responsiveness) ─────────────────────
    if _current_name == "Weather":
        page = _current_page()
        if page and hasattr(page, "poll_touch"):
            page.poll_touch()

    # ── Sensor read ───────────────────────────────────────────────────────────
    if time.ticks_diff(now, _last_sensor) >= SENSOR_INTERVAL:
        _last_sensor = now
        if _hub: _sensor_data = _hub.read_all()

    # ── Screen refresh ────────────────────────────────────────────────────────
    if time.ticks_diff(now, _last_draw) >= DRAW_INTERVAL:
        _last_draw = now
        page = _current_page()
        if page:
            if _current_name == "Home":
                if hasattr(page, "set_date"):
                    page.set_date(_date_str())
                page.update(
                    sensor_data=_sensor_data, outdoor=_outdoor,
                    time_str=_time_str(), wifi_ok=is_connected(), flask_ok=_flask_ok,
                )
            elif _current_name == "Sensors":
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

if __name__ == "__main__":
    try:
        setup()
        while True: loop()
    except Exception as e:
        import sys; sys.print_exception(e)