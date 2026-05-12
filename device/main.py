# main.py — Smart Space entry point (UIFlow2).

import time
import M5
from M5 import *

import config
from sensors      import SensorHub
from connectivity import (wifi_connect, is_connected, upload_sensor_data,
                           record_while_held, upload_voice_and_receive,
                           play_wav_from_memory)
from components   import (SCREEN_W, SCREEN_H, STATUS_H,
                           C_BG, C_MUTED, C_GREEN, C_RED, C_BLUE,
                           PAGES, SwipeDetector, is_btnc_pressed,
                           draw_status_bar, update_rec_indicator, draw_text)
from pages.home     import HomePage
from pages.settings import SettingsPage

# ── Constants ─────────────────────────────────────────────────────────────────
REC_WAV        = "/flash/rec.wav"
DRAW_INTERVAL  = 2000
RETRY_INTERVAL = 10

# ── State ─────────────────────────────────────────────────────────────────────
_page_idx    = PAGES.index("Home")
_pages       = {}
_hub         = None
_sensor_data = {}
_outdoor     = {}
_flask_ok    = False
_last_upload = 0
_last_retry  = 0
_last_draw   = 0
_swipe       = SwipeDetector()


def _time_str():
    try:
        t = time.localtime()
        return "{:02d}:{:02d}".format(t[3], t[4])
    except Exception:
        return "--:--"


def _current_page():
    return _pages.get(PAGES[_page_idx])


def _go_to(idx):
    global _page_idx, _last_draw
    # Notify current page it's being left
    current = _current_page()
    if current and hasattr(current, "on_exit"):
        try:
            current.on_exit()
        except Exception as e:
            print("[Nav] on_exit:", e)
    _page_idx = idx % len(PAGES)
    page = _current_page()
    if page:
        page.on_enter()
    _last_draw = 0   # force immediate refresh on next loop


# ── Voice assistant ───────────────────────────────────────────────────────────

def _do_voice():
    global _flask_ok

    _rec_sec = [0]

    def _status_cb(msg, color):
        if "REC" in msg and "s" in msg:
            try:
                _rec_sec[0] = int(msg.strip().split()[-1].replace("s", ""))
            except Exception:
                pass
        update_rec_indicator(_rec_sec[0])

    # Pass held_check as positional arg to avoid keyword mismatch on old firmware
    ok = record_while_held(REC_WAV, is_btnc_pressed, _status_cb)

    update_rec_indicator(0)

    if not ok:
        return

    if not is_connected():
        draw_text(" No WiFi ", 90, 110, C_RED, C_BG, 2)
        time.sleep(1)
        _current_page().on_enter()
        return

    if not _flask_ok:
        draw_text("No Backend", 80, 110, C_RED, C_BG, 2)
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
    global _hub, _pages

    M5.begin()
    Speaker.begin()
    Speaker.setVolume(config.SPK_VOLUME)

    M5.Display.fillScreen(C_BG)
    draw_text("SMART SPACE",    75, 95,  0xFFA500, C_BG, 2)
    draw_text("Initialising...", 95, 125, C_MUTED,  C_BG, 1)

    try:
        _hub = SensorHub()
    except Exception as e:
        print("[Setup] SensorHub:", e)

    _pages["Home"]     = HomePage()
    _pages["Settings"] = SettingsPage()

    wifi_connect(
        status_cb=lambda msg, col: draw_text(msg, 50, 150, col, C_BG, 1)
    )

    _go_to(_page_idx)


# ── Main loop ─────────────────────────────────────────────────────────────────

def loop():
    global _sensor_data, _outdoor, _flask_ok
    global _last_upload, _last_retry, _last_draw

    # ── BtnC zone: hold to record ─────────────────────────────────────────────
    if is_btnc_pressed():
        t0 = time.ticks_ms()
        while is_btnc_pressed():
            M5.update()
            if time.ticks_diff(time.ticks_ms(), t0) >= config.HOLD_TO_REC_MS:
                if PAGES[_page_idx] == "Home":
                    _do_voice()
                return
        return   # short tap → ignore

    # ── Swipe ─────────────────────────────────────────────────────────────────
    direction = _swipe.update()
    if direction == "left":
        _go_to(_page_idx + 1)
        return
    elif direction == "right":
        _go_to(_page_idx - 1)
        return

    # ── Sensor read ───────────────────────────────────────────────────────────
    now = time.time()
    if now - _last_upload >= config.UPLOAD_INTERVAL:
        _last_upload = now
        if _hub:
            _sensor_data = _hub.read_all()

    # ── Backend upload / retry ────────────────────────────────────────────────
    if is_connected() and _sensor_data:
        if _flask_ok:
            if now - _last_retry >= config.UPLOAD_INTERVAL:
                _last_retry = now
                result = upload_sensor_data(_sensor_data)
                if result:
                    _outdoor  = result
                    _flask_ok = True
                else:
                    _flask_ok = False
                    print("[Main] Backend offline")
        else:
            if now - _last_retry >= RETRY_INTERVAL:
                _last_retry = now
                print("[Main] Retrying backend...")
                result = upload_sensor_data(_sensor_data)
                if result:
                    _outdoor  = result
                    _flask_ok = True
                    print("[Main] Backend connected!")

    # ── Screen refresh ────────────────────────────────────────────────────────
    now_ms = time.ticks_ms()
    if time.ticks_diff(now_ms, _last_draw) >= DRAW_INTERVAL:
        _last_draw = now_ms
        page = _current_page()
        if page:
            if PAGES[_page_idx] == "Home":
                page.update(
                    sensor_data=_sensor_data,
                    outdoor=_outdoor,
                    time_str=_time_str(),
                    wifi_ok=is_connected(),
                    flask_ok=_flask_ok,
                )
            elif PAGES[_page_idx] == "Settings":
                page.update()


    time.sleep_ms(20)


if __name__ == "__main__":
    try:
        setup()
        while True:
            loop()
    except Exception as e:
        print("[CRASH]", e)
        import sys
        sys.print_exception(e)