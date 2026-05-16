# main.py — Smart Space entry point (UIFlow2).
#
# Interaction Logic:
#   BtnA (Left):   Short -> Prev Page | Long (600ms) -> Enter Settings
#   BtnB (Center): Short -> Home Page
#   BtnC (Right):  Short -> Next Page | Long -> Voice Assistant

import time
import M5
from M5 import *

try:
    import hardware
    _HAS_HARDWARE = True
except ImportError:
    _HAS_HARDWARE = False

import config
from sensors      import SensorHub
from connectivity import (wifi_connect, sync_ntp, is_connected, upload_sensor_data,
                           record_while_held, upload_voice_and_receive,
                           play_wav_from_memory, fetch_forecast,
                           speak_announcement, speak_alert)
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

# Screen / motion / announce intervals (ms)
SCREEN_DIM_MS    = 60000   # 60s idle → dim to 20%
SCREEN_OFF_MS    = 120000  # 120s idle → screen off
ANNOUNCE_MS      = 3600000 # 1h between ambient announcements
ANOMALY_LEAD_MS  = 10000   # LED must be on 10s before alert plays

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

# Motion / screen state
_last_motion_ms    = 0
_last_announce_ms  = 0
_screen_off        = False

# Anomaly state — LED on for ANOMALY_LEAD_MS before alert plays
_anomaly_start_ms  = 0     # when current anomaly first appeared
_last_anomaly_type = None  # type of last alerted anomaly

# LED state
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
    global _led_state, _last_led_tick
    if not _HAS_HARDWARE or not _rgb_bar:
        return

    eco2 = (_sensor_data.get("eco2") or 0) if _sensor_data else 0
    tvoc = (_sensor_data.get("tvoc") or 0) if _sensor_data else 0

    hum = (_sensor_data.get("humidity") or 50) if _sensor_data else 50

    if eco2 > 1500 or tvoc > 660 or hum < 20 or hum > 75:
        color, interval = 0xFF0000, 250
    elif eco2 > 800 or tvoc > 220 or hum < 30 or hum > 65:
        color, interval = 0xFFFF00, 500
    else:
        if _led_state:
            _rgb_bar.fill_color(0x000000)
            _led_state = False
        return

    now = time.ticks_ms()
    if time.ticks_diff(now, _last_led_tick) > interval:
        _last_led_tick = now
        _led_state = not _led_state
        _rgb_bar.fill_color(color if _led_state else 0x000000)


# ── Motion / Screen ───────────────────────────────────────────────────────────

def _handle_motion_and_screen(now_ms):
    """PIR + touch → screen brightness only. No announce logic here."""
    global _last_motion_ms, _screen_off

    motion = bool(_sensor_data.get("motion", False)) if _sensor_data else False

    # Touch while screen off → wake, no announce
    if _screen_off and M5.Touch.getCount() > 0:
        _last_motion_ms = now_ms
        _screen_off = False
        M5.Display.setBrightness(100)
        return

    if motion:
        _last_motion_ms = now_ms
        _screen_off = False
        M5.Display.setBrightness(100)
    else:
        idle = time.ticks_diff(now_ms, _last_motion_ms)
        if idle >= SCREEN_OFF_MS and not _screen_off:
            M5.Display.setBrightness(0)
            _screen_off = True
        elif idle >= SCREEN_DIM_MS and not _screen_off:
            M5.Display.setBrightness(20)


# ── Announce & Alert ──────────────────────────────────────────────────────────

def _check_anomaly():
    """
    Return combined anomaly key for all active RED-level alerts.
    Multiple anomalies are joined e.g. "co2_danger+tvoc_danger".
    Returns None if no red-level anomaly detected.
    """
    eco2 = (_sensor_data.get("eco2") or 0)
    tvoc = (_sensor_data.get("tvoc") or 0)
    hum  = (_sensor_data.get("humidity") or 50)

    active = []
    if eco2 > 1500: active.append("co2_danger")
    if tvoc > 660:  active.append("tvoc_danger")
    if hum < 20:    active.append("humidity_low")
    if hum > 75:    active.append("humidity_high")

    return "+".join(active) if active else None

def _do_announce():
    """Hourly ambient announcement via Gemini + TTS."""
    if not _flask_ok or not is_connected():
        return
    print("[Announce] Generating hourly announcement...")
    audio = speak_announcement(_sensor_data, _outdoor, _forecast)
    if audio and len(audio) > 44:
        play_wav_from_memory(audio)

def _do_alert(anomaly_type):
    """Anomaly alert via Gemini + TTS."""
    if not _flask_ok or not is_connected():
        return
    print("[Alert] Generating alert:", anomaly_type)
    audio = speak_alert(_sensor_data, anomaly_type)
    if audio and len(audio) > 44:
        play_wav_from_memory(audio)

def _handle_announce(now_ms):
    """
    Hourly announcement: independent of PIR, skipped when screen off.
    Runs every loop iteration.
    """
    global _last_announce_ms
    if _screen_off or not _flask_ok or not is_connected():
        return
    if time.ticks_diff(now_ms, _last_announce_ms) >= ANNOUNCE_MS:
        _last_announce_ms = now_ms
        _do_announce()

def _handle_anomaly(now_ms):
    """
    Anomaly alert: LED must be on for ANOMALY_LEAD_MS before alert plays.
    Alert plays once per anomaly type; resets only when anomaly fully clears.
    Timer is NOT reset by brief sensor fluctuations.
    """
    global _anomaly_start_ms, _last_anomaly_type
    if _screen_off or not _flask_ok or not is_connected():
        return

    anomaly = _check_anomaly()

    if anomaly:
        if _anomaly_start_ms == 0:
            # Anomaly just appeared, start timer
            _anomaly_start_ms = now_ms
            print("[Anomaly] Detected:", anomaly, "- waiting", ANOMALY_LEAD_MS // 1000, "s")
        elif anomaly != _last_anomaly_type:
            # Check if LED has been on long enough
            elapsed = time.ticks_diff(now_ms, _anomaly_start_ms)
            if elapsed >= ANOMALY_LEAD_MS:
                print("[Anomaly] Firing alert:", anomaly)
                _last_anomaly_type = anomaly
                _do_alert(anomaly)
    else:
        # Only reset if already alerted or timer not started
        # This prevents brief dips from resetting the 30s timer
        if _last_anomaly_type is not None or _anomaly_start_ms == 0:
            if _anomaly_start_ms != 0:
                print("[Anomaly] Cleared after alert, resetting")
            _anomaly_start_ms  = 0
            _last_anomaly_type = None
        # If timer started but no alert yet, keep timer running through brief dips


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
    global _last_motion_ms, _last_announce_ms

    M5.begin()
    Speaker.begin()
    Speaker.setVolume(config.SPK_VOLUME)

    if _HAS_HARDWARE:
        try:
            _rgb_bar = hardware.RGB(io=25, n=10, type="SK6812")
            _rgb_bar.fill_color(0x000000)
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

    # Init timers to now so device doesn't immediately trigger
    t0 = time.ticks_ms()
    _last_motion_ms   = t0
    _last_announce_ms = t0

    _go_to(_current_name)


# ── Main Loop ─────────────────────────────────────────────────────────────────

def loop():
    global _sensor_data, _outdoor, _flask_ok, _forecast, _prev_flask_ok
    global _last_sensor, _last_upload, _last_retry, _last_draw, _last_forecast

    M5.update()
    global_led_alert()

    now = time.ticks_ms()

    # Screen brightness from PIR + touch
    _handle_motion_and_screen(now)

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

    # ── Weather page touch (per-frame) ────────────────────────────────────────
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
                    location=_outdoor.get("location", ""),
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

    # ── Hourly announcement (independent of PIR) ──────────────────────────────
    _handle_announce(now)

    # ── Anomaly alert (LED on 30s before alert plays) ─────────────────────────
    _handle_anomaly(now)

    time.sleep_ms(20)


if __name__ == "__main__":
    try:
        setup()
        while True: loop()
    except Exception as e:
        import sys; sys.print_exception(e)