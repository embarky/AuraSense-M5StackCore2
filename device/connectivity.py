# connectivity.py — WiFi, sensor upload, voice assistant (UIFlow2).

import json
import struct
import time

import network
import requests
from machine import I2C, Pin, RTC
import M5
from M5 import *

import config


# ── WiFi ──────────────────────────────────────────────────────────────────────

def wifi_connect(status_cb=None):
    def _log(msg, color=0xFFFF00):
        print("[WiFi]", msg)
        if status_cb:
            status_cb(msg, color)

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if wlan.isconnected():
        _log("Already connected: " + wlan.ifconfig()[0], 0x00FF00)
        return True
    if not config.WIFI_SSID:
        _log("No SSID configured", 0xFF0000)
        return False
    _log("Connecting to " + config.WIFI_SSID + "...")
    wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
    for _ in range(20):
        if wlan.isconnected():
            _log("WiFi OK  " + wlan.ifconfig()[0], 0x00FF00)
            return True
        time.sleep(1)
    _log("WiFi FAILED", 0xFF0000)
    return False


def is_connected():
    return network.WLAN(network.STA_IF).isconnected()


# ── Sensor upload ─────────────────────────────────────────────────────────────

def upload_sensor_data(sensor_data):
    clean = {k: (v if v is not None else 0) for k, v in sensor_data.items()}
    try:
        payload = json.dumps(clean)
        headers = {
            "Content-Type":   "application/json",
            "Connection":     "close",
            "Content-Length": str(len(payload)),
        }
        resp = requests.post(config.SENSOR_URL, data=payload, headers=headers)
        if resp.status_code == 200:
            result = resp.json()
            resp.close()
            utc = result.get("utc_time")
            if utc and len(utc) >= 7:
                try:
                    if RTC().datetime()[0] < 2020:
                        RTC().datetime((int(utc[0]), int(utc[1]), int(utc[2]),
                                        1, int(utc[4]), int(utc[5]), int(utc[6]), 0))
                except Exception:
                    pass
            return result
        resp.close()
        print("[Upload] Error:", resp.status_code)
    except Exception as e:
        print("[Upload] Failed:", e)
    return None


# ── AXP192 mic power ──────────────────────────────────────────────────────────

def _axp_mic_on():
    try:
        i2c = I2C(0, scl=Pin(22), sda=Pin(21), freq=400000)
        i2c.writeto_mem(0x34, 0x12, bytes([0x57]))
        i2c.writeto_mem(0x34, 0x96, bytes([0x06]))
        time.sleep(0.3)
    except Exception as e:
        print("[AXP]", e)


# ── Recording ─────────────────────────────────────────────────────────────────

def _merge_chunks(paths, out):
    import os
    pcm = b""
    for p in paths:
        try:
            with open(p, "rb") as f:
                pcm += f.read()[44:]
            os.remove(p)
        except Exception as e:
            print("[MERGE]", e)
    sr  = config.REC_RATE
    n   = len(pcm)
    hdr = (b"RIFF" + struct.pack('<I', 36 + n) + b"WAVEfmt "
           + struct.pack('<I', 16) + struct.pack('<HH', 1, 1)
           + struct.pack('<II', sr, sr * 2) + struct.pack('<HH', 2, 16)
           + b"data" + struct.pack('<I', n))
    with open(out, "wb") as f:
        f.write(hdr)
        f.write(pcm)


def record_while_held(rec_path, held_check=None, status_cb=None):
    """
    Record in 1-second chunks while held_check() returns True.
    held_check: callable() -> bool. Defaults to checking BtnC touch zone.
    """
    import os

    if held_check is None:
        # Default: bottom-right touch area (BtnC zone)
        held_check = lambda: (M5.Touch.getCount() > 0
                              and M5.Touch.getX() >= 214
                              and M5.Touch.getY() >= 220)

    def _log(msg, color=0xFF4444):
        print("[REC]", msg)
        if status_cb:
            status_cb(msg, color)

    Speaker.end()
    time.sleep_ms(100)
    _axp_mic_on()
    Mic.begin()
    try:
        Mic.setGain(config.MIC_GAIN)
    except Exception:
        pass

    chunks = []
    total  = 0
    _log("REC...")
    _vibrate(50)

    while True:
        chunk = "/flash/chunk_%d.wav" % len(chunks)
        Mic.recordWavFile(chunk, config.REC_RATE, 1, False)
        chunks.append(chunk)
        total += 1
        M5.update()
        if not held_check() or total >= config.MAX_REC_SECONDS:
            break
        _log("REC %ds" % total)

    Mic.end()
    _vibrate(50)

    if not chunks:
        return False
    if len(chunks) == 1:
        try:
            os.remove(rec_path)
        except Exception:
            pass
        os.rename(chunks[0], rec_path)
    else:
        _merge_chunks(chunks, rec_path)
    print("[REC] %ds recorded" % total)
    return True


# ── Voice upload + playback ───────────────────────────────────────────────────

def upload_voice_and_receive(rec_path):
    try:
        with open(rec_path, "rb") as f:
            wav = f.read()
        print("[Voice] Uploading %d bytes" % len(wav))
        resp = requests.post(config.VOICE_URL, data=wav,
                             headers={"Content-Type": "audio/wav"})
        if resp.status_code == 204:
            resp.close()
            return None
        audio = resp.content
        resp.close()
        print("[Voice] Received %d bytes" % len(audio))
        return audio
    except Exception as e:
        print("[Voice] Error:", e)
        return None


def play_wav_from_memory(wav_bytes):
    Speaker.begin()
    Speaker.setVolume(config.SPK_VOLUME)
    Speaker.playRaw(wav_bytes[44:], config.REC_RATE, False)
    try:
        while Speaker.isPlaying():
            M5.update()
            time.sleep_ms(50)
    except Exception:
        pass


def _vibrate(ms=80, intensity=180):
    try:
        M5.Power.setVibration(intensity)
        time.sleep_ms(ms)
        M5.Power.setVibration(0)
    except Exception:
        pass