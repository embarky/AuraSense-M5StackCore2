# main.py — Smart Space device entry point.
#
# Responsibilities
# ────────────────
#   - Initialise hardware and services on boot.
#   - Run the main loop: read sensors, upload data, update UI.
#   - Handle page navigation (Home / Forecast / Settings).
#   - Trigger voice assistant on Button A hold.

import time
import M5
from M5 import *

import config
from sensors  import SensorHub
from connectivity import (wifi_connect, is_connected,
                          upload_sensor_data,
                          record_while_held, upload_voice_and_receive,
                          play_wav_from_memory)
from pages.home     import HomePage
# from pages.forecast import ForecastPage   # implement when ready
# from pages.settings import SettingsPage   # implement when ready
from components import C_YELLOW, C_GREEN, C_RED, C_BLUE, C_GRAY

# ── Constants ─────────────────────────────────────────────────────────────────
REC_WAV         = "/flash/rec.wav"
HOLD_TO_REC_MS  = config.HOLD_TO_REC_MS
UPLOAD_INTERVAL = config.UPLOAD_INTERVAL

# ── Global state ──────────────────────────────────────────────────────────────
_page_name   = "Home"
_pages       = {}
_sensor_hub  = None
_sensor_data = {}
_outdoor     = {}
_last_upload = 0

C_GRAY = 0x8B949E


def _set_status(msg, color=C_YELLOW):
    print("[STATUS]", msg)


def _get_time_str() -> str:
    try:
        t = time.localtime()
        return "{:02d}:{:02d}".format(t[3], t[4])
    except Exception:
        return "--:--"


# ── Setup ─────────────────────────────────────────────────────────────────────

def setup():
    global _sensor_hub, _pages

    M5.begin()
    Speaker.begin()
    Speaker.setVolume(config.SPK_VOLUME)

    # Initialise sensors
    try:
        _sensor_hub = SensorHub()
    except Exception as e:
        print("[Setup] Sensor init failed:", e)

    # Initialise pages
    _pages = {
        "Home": HomePage(),
        # "Forecast": ForecastPage(),
        # "Settings": SettingsPage(),
    }

    # WiFi
    wifi_connect(status_cb=_set_status)

    # Enter home page
    _pages["Home"].on_enter()


# ── Main loop ─────────────────────────────────────────────────────────────────

def loop():
    global _page_name, _sensor_data, _outdoor, _last_upload

    M5.update()

    # ── Button A: hold to record voice query ──────────────────────────────────
    if M5.BtnA.isPressed():
        t0 = time.ticks_ms()
        while M5.BtnA.isPressed():
            M5.update()
            if time.ticks_diff(time.ticks_ms(), t0) >= HOLD_TO_REC_MS:
                # Run voice assistant
                _set_status("REC...", C_RED)
                ok = record_while_held(REC_WAV, status_cb=_set_status)
                if ok:
                    _set_status("Wait...", C_BLUE)
                    audio = upload_voice_and_receive(REC_WAV)
                    if audio and len(audio) > 44:
                        _set_status("Play...", C_GREEN)
                        play_wav_from_memory(audio)
                    else:
                        _set_status("Silence", C_GRAY)
                _set_status("Ready", C_GREEN)
                _pages[_page_name].on_enter()
                return

    # ── Periodic sensor read + upload ─────────────────────────────────────────
    now = time.time()
    if now - _last_upload >= UPLOAD_INTERVAL:
        _last_upload = now

        if _sensor_hub:
            _sensor_data = _sensor_hub.read_all()

        if is_connected() and _sensor_data:
            result = upload_sensor_data(_sensor_data)
            if result:
                _outdoor = result   # contains outdoor_temp, outdoor_desc, etc.

    # ── Update current page ───────────────────────────────────────────────────
    current_page = _pages.get(_page_name)
    if current_page:
        next_page = current_page.update(
            sensor_data=_sensor_data,
            outdoor=_outdoor,
            time_str=_get_time_str(),
            wifi_ok=is_connected(),
        )
        if next_page and next_page in _pages:
            _page_name = next_page
            _pages[_page_name].on_enter()

    time.sleep_ms(200)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        setup()
        while True:
            loop()
    except Exception as e:
        print("[CRASH]", e)
        # Uncomment for auto-restart in production:
        # import machine; machine.reset()