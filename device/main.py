# main.py — AuraSense entry point (UIFlow2).
# "AuraSense: See the air you breathe."
#
# Interaction Logic:
#   BtnA (Left):   Short -> Prev Page | Long (600ms) -> Enter Settings
#   BtnB (Center): Short -> Home Page
#   BtnC (Right):  Short -> Next Page | Long -> Voice Assistant

import gc
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
UPLOAD_INTERVAL   = 30000  # 30s
RETRY_INTERVAL    = 10000
FORECAST_INTERVAL = 3600000
LONG_PRESS_MS     = 600

# Screen / motion / announce intervals (ms)
SCREEN_DIM_MS     = 60000   # 60s idle -> dim to 20%
SCREEN_OFF_MS     = 120000  # 120s idle -> screen off
ANNOUNCE_MS       = 3600000 # 1h between ambient announcements
ANOMALY_LEAD_MS   = 10000   # LED must be on 10s before alert plays
ANOMALY_REPEAT_MS = 30000   # repeat alert every 30s while anomaly persists

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
_last_gc       = 0

# Motion / screen state
_last_motion_ms    = 0
_last_announce_ms  = 0
_screen_off        = False

# Anomaly state — LED on for ANOMALY_LEAD_MS before alert plays
_anomaly_start_ms  = 0     
_last_anomaly_type = None  
_last_alert_ms     = 0     

# LED state
_rgb_bar       = None
_led_state     = False
_last_led_tick = 0

# ── State Protectors ──────────────────────────────────────────────────────────

def _safe_update_outdoor(new_data: dict) -> bool:
    """
    Safely updates the global _outdoor state. 
    Prevents location amnesia if the backend omits the 'location' key.
    """
    global _outdoor, _flask_ok
    if not new_data:
        return False
        
    old_loc = _outdoor.get("location")
    _outdoor = new_data
    
    if old_loc and not _outdoor.get("location"):
        _outdoor["location"] = old_loc
        
    _flask_ok = True
    return True

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
    hum  = (_sensor_data.get("humidity") or 50) if _sensor_data else 50

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
    """PIR + touch -> screen brightness only."""
    global _last_motion_ms, _screen_off

    motion = bool(_sensor_data.get("motion", False)) if _sensor_data else False

    touched = M5.Touch.getCount() > 0
    btn_any = M5.BtnA.isPressed() or M5.BtnB.isPressed() or M5.BtnC.isPressed()
    if (_screen_off or M5.Display.getBrightness() < 100) and (touched or btn_any):
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
    if not _flask_ok or not is_connected():
        return
    print("[AuraSense | Announce] Generating hourly announcement...")
    audio = speak_announcement(_sensor_data, _outdoor, _forecast)
    if audio and len(audio) > 44:
        play_wav_from_memory(audio)
    audio = None
    gc.collect()
    print("[AuraSense | Announce] Done. Free mem:", gc.mem_free())

def _do_alert(anomaly_type):
    if not _flask_ok or not is_connected():
        return
    print("[AuraSense | Alert] Generating alert:", anomaly_type)
    audio = speak_alert(_sensor_data, anomaly_type)
    if audio and len(audio) > 44:
        play_wav_from_memory(audio)
    audio = None
    gc.collect()
    print("[AuraSense | Alert] Done. Free mem:", gc.mem_free())

def _handle_announce(now_ms):
    global _last_announce_ms
    if _screen_off or not _flask_ok or not is_connected():
        return
    if time.ticks_diff(now_ms, _last_announce_ms) >= ANNOUNCE_MS:
        _last_announce_ms = now_ms
        _do_announce()

def _handle_anomaly(now_ms):
    global _anomaly_start_ms, _last_anomaly_type, _last_alert_ms, _last_upload, _last_retry, _outdoor, _flask_ok

    if not _flask_ok or not is_connected():
        return

    anomaly = _check_anomaly()

    if anomaly:
        if _anomaly_start_ms == 0:
            _anomaly_start_ms = now_ms
            print("[AuraSense | Anomaly] Detected:", anomaly, "- waiting", ANOMALY_LEAD_MS // 1000, "s")
        else:
            elapsed = time.ticks_diff(now_ms, _anomaly_start_ms)
            since_last = time.ticks_diff(now_ms, _last_alert_ms)
            if elapsed >= ANOMALY_LEAD_MS and (
                _last_anomaly_type is None or since_last >= ANOMALY_REPEAT_MS
            ):
                print("[AuraSense | Anomaly] Firing alert:", anomaly)
                _last_anomaly_type = anomaly
                _last_alert_ms = now_ms
                
                result = upload_sensor_data(_sensor_data)
                if _safe_update_outdoor(result):
                    _last_upload = now_ms
                    _last_retry  = now_ms
                    
                _do_alert(anomaly)
    else:
        if _last_anomaly_type is not None or _anomaly_start_ms == 0:
            if _anomaly_start_ms != 0:
                print("[AuraSense | Anomaly] Cleared after alert, resetting")
            _anomaly_start_ms  = 0
            _last_anomaly_type = None
            _last_alert_ms     = 0


# ── Voice Assistant ───────────────────────────────────────────────────────────

def _voice_label(text, color):
    M5.Display.fillRect(0, 95, 320, 30, C_BG)
    Widgets.Label(text, 160 - len(text) * 5, 100, 1.0, color, C_BG, Widgets.FONTS.DejaVu18)

def _do_voice():
    global _flask_ok, _hub, _sensor_data
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
        _voice_label("No WiFi", C_RED)
        time.sleep(1)
        _current_page().on_enter()
        return

    _voice_label("Uploading...", C_BLUE)
    audio = upload_voice_and_receive(REC_WAV)

    if audio and len(audio) > 44:
        _flask_ok = True
        _voice_label("Playing...", C_GREEN)
        play_wav_from_memory(audio)
    else:
        _flask_ok = False
        _voice_label("No reply", C_MUTED)
        time.sleep(1)

    global _last_draw
    _last_draw = 0

    try:
        if _hub and _hub._qmp:
            from sensors import QMP6988
            _hub._qmp = QMP6988()
            print("[AuraSense | Voice] QMP6988 re-initialized")
    except Exception as e:
        print("[AuraSense | Voice] QMP6988 re-init failed:", e)


# ── Setup ─────────────────────────────────────────────────────────────────────

def setup():
    global _hub, _pages, _sensor_data, _forecast, _rgb_bar, _outdoor
    global _last_motion_ms, _last_announce_ms

    M5.begin()
    Speaker.begin()
    Speaker.setVolume(config.SPK_VOLUME)

    try:
        import m5things
        m5things.stop()
        print("[AuraSense | Setup] M5Things stopped")
    except Exception:
        pass

    if _HAS_HARDWARE:
        try:
            _rgb_bar = hardware.RGB(io=25, n=10, type="SK6812")
            _rgb_bar.fill_color(0x000000)
        except Exception as e:
            print("[AuraSense | Setup] RGB Init error:", e)

    M5.Display.fillScreen(C_BG)
    Widgets.Label("AuraSense",    55, 88,  1.0, 0xFFA500, C_BG, Widgets.FONTS.DejaVu24)
    Widgets.Label("Initializing...", 88, 126, 1.0, C_MUTED,  C_BG, Widgets.FONTS.DejaVu18)

    try: _hub = SensorHub()
    except Exception as e: print("[AuraSense | Setup] SensorHub error:", e)

    _pages["Home"]     = HomePage()
    _pages["Sensors"]  = SensorPage()
    _pages["Weather"]  = WeatherPage()
    _pages["Settings"] = SettingsPage()

    if wifi_connect(status_cb=lambda msg, col: draw_text(msg, 50, 150, col, C_BG, 1)):
        sync_ntp()
        
        fc_data, loc_data = fetch_forecast()
        if fc_data is not None:
            _forecast = fc_data
            if loc_data:
                _outdoor["location"] = loc_data

    if _hub: _sensor_data = _hub.read_all()

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

    _handle_motion_and_screen(now)

    # ── Button A ──────────────────────────────────────────────────────────────
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

    # ── Button B ──────────────────────────────────────────────────────────────
    if M5.BtnB.wasPressed():
        _go_to("Home")
        return

    # ── Button C ──────────────────────────────────────────────────────────────
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

    # ── Touch Poll ────────────────────────────────────────────────────────────
    if _current_name == "Weather":
        page = _current_page()
        if page and hasattr(page, "poll_touch"):
            page.poll_touch()

    # ── Sensor Poll ───────────────────────────────────────────────────────────
    if time.ticks_diff(now, _last_sensor) >= SENSOR_INTERVAL:
        _last_sensor = now
        if _hub: _sensor_data = _hub.read_all()

    # ── Screen Redraw ─────────────────────────────────────────────────────────
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

    # ── Backend Networking ────────────────────────────────────────────────────
    if is_connected() and _sensor_data:
        anomaly_active = _check_anomaly() is not None
        upload_interval = 5000 if anomaly_active else UPLOAD_INTERVAL
        
        if _flask_ok:
            if time.ticks_diff(now, _last_upload) >= upload_interval:
                _last_upload = now
                _last_retry  = now
                result = upload_sensor_data(_sensor_data)
                
                if not _safe_update_outdoor(result):
                    _flask_ok = False
        else:
            if time.ticks_diff(now, _last_retry) >= RETRY_INTERVAL:
                _last_retry = now
                result = upload_sensor_data(_sensor_data)
                _safe_update_outdoor(result)

    # ── Recover Backend State ─────────────────────────────────────────────────
    if _flask_ok and not _prev_flask_ok:
        fc_data, loc_data = fetch_forecast()
        if fc_data is not None:
            _forecast = None
            _forecast = fc_data
            if loc_data:
                _outdoor["location"] = loc_data
            _last_forecast = now
            fc_data = None
    _prev_flask_ok = _flask_ok

    # ── Hourly Forecast ───────────────────────────────────────────────────────
    if is_connected():
        if time.ticks_diff(now, _last_forecast) >= FORECAST_INTERVAL:
            _last_forecast = now
            fc_data, loc_data = fetch_forecast()
            if fc_data is not None:
                _forecast = None
                _forecast = fc_data
                if loc_data:
                    _outdoor["location"] = loc_data
                fc_data = None

    # ── Garbage Collection ────────────────────────────────────────────────────
    global _last_gc
    if time.ticks_diff(now, _last_gc) >= 300000:
        _last_gc = now
        gc.collect()
        print("[AuraSense | GC] Free mem:", gc.mem_free())

    _handle_announce(now)
    _handle_anomaly(now)

    time.sleep_ms(20)


if __name__ == "__main__":
    try:
        setup()
        while True: loop()
    except Exception as e:
        import sys; sys.print_exception(e)