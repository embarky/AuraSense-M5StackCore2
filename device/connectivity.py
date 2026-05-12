# connectivity.py — WiFi, NTP sync, sensor upload, and voice assistant (UIFlow2).
#
# Implements non-blocking architectural patterns by enforcing strict timeouts 
# on all HTTP requests to prevent single-thread starvation.

import json
import struct
import time
import network
import requests
import ntptime
from machine import I2C, Pin, RTC
import M5
from M5 import *

import config


# ── WiFi ──────────────────────────────────────────────────────────────────────

def wifi_connect(status_cb=None) -> bool:
    """Connect to the configured Wi-Fi network with visual feedback."""
    def _log(msg, color=0xFFFF00):
        print("[WiFi]", msg)
        if status_cb:
            status_cb(msg, color)

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    
    if wlan.isconnected():
        _log("Connected: " + wlan.ifconfig()[0], 0x00FF00)
        return True
        
    if not config.WIFI_SSID:
        _log("No SSID Configured", 0xFF0000)
        return False
        
    _log("Connecting to " + config.WIFI_SSID)
    wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
    
    # Wait up to 20 seconds for connection
    for _ in range(20):
        if wlan.isconnected():
            _log("WiFi OK: " + wlan.ifconfig()[0], 0x00FF00)
            return True
        time.sleep(1)
        
    _log("WiFi FAILED", 0xFF0000)
    return False


def is_connected() -> bool:
    """Check if the device currently has an active Wi-Fi connection."""
    return network.WLAN(network.STA_IF).isconnected()


# ── NTP Time Sync ─────────────────────────────────────────────────────────────

def sync_ntp(offset_hours: int = 2) -> bool:
    """
    Fetch UTC time from NTP and apply timezone offset to local RTC.
    Default offset is +2 (CEST for Switzerland).
    """
    if not is_connected():
        print("[NTP] Failed: No WiFi")
        return False

    try:
        print("[NTP] Syncing with pool.ntp.org...")
        # Sets the internal RTC to UTC time
        ntptime.settime()
        
        # Apply timezone offset (MicroPython time is seconds since 2000-01-01)
        local_time_sec = time.time() + (offset_hours * 3600)
        
        # Convert seconds to a structured time tuple
        lt = time.localtime(local_time_sec)
        
        # Re-set the RTC hardware with the local timezone values
        # RTC.datetime format: (year, month, day, weekday, hour, minute, second, subsecond)
        RTC().datetime((lt[0], lt[1], lt[2], lt[6] + 1, lt[3], lt[4], lt[5], 0))
        
        print("[NTP] Success! Local time set.")
        return True
    except Exception as e:
        print("[NTP] Error during sync:", e)
        return False


# ── Sensor Upload ─────────────────────────────────────────────────────────────

def upload_sensor_data(sensor_data: dict) -> dict | None:
    """
    Upload sensor readings to the Flask backend.
    CRITICAL: Uses timeout=3 to prevent the main UI loop from freezing if the server is down.
    """
    clean = {k: (v if v is not None else 0) for k, v in sensor_data.items()}
    
    try:
        payload = json.dumps(clean)
        headers = {
            "Content-Type":   "application/json",
            "Connection":     "close",
            "Content-Length": str(len(payload)),
        }
        
        # TIMEOUT ADDED: Prevents the "fake death" of the UI and sensor readings
        resp = requests.post(config.SENSOR_URL, data=payload, headers=headers, timeout=3)
        
        if resp.status_code == 200:
            result = resp.json()
            resp.close()
            return result
            
        resp.close()
        print("[Upload] Server Error HTTP", resp.status_code)
        
    except Exception as e:
        print("[Upload] Request Failed (Timeout/Network):", e)
        
    return None


# ── AXP192 Mic Power Workaround ───────────────────────────────────────────────

def _axp_mic_on():
    """Forcefully powers on the microphone via the AXP192 PMU."""
    try:
        i2c = I2C(0, scl=Pin(22), sda=Pin(21), freq=400000)
        i2c.writeto_mem(0x34, 0x12, bytes([0x57]))
        i2c.writeto_mem(0x34, 0x96, bytes([0x06]))
        time.sleep(0.3)
    except Exception as e:
        print("[AXP] Mic power init skipped:", e)


# ── Recording ─────────────────────────────────────────────────────────────────

def _merge_chunks(paths, out):
    """Merges multiple 1-second WAV chunks into a single valid WAV file."""
    import os
    pcm = b""
    for p in paths:
        try:
            with open(p, "rb") as f:
                pcm += f.read()[44:]
            os.remove(p)
        except Exception as e:
            print("[MERGE] Error reading chunk:", e)
            
    sr  = config.REC_RATE
    n   = len(pcm)
    hdr = (b"RIFF" + struct.pack('<I', 36 + n) + b"WAVEfmt "
           + struct.pack('<I', 16) + struct.pack('<HH', 1, 1)
           + struct.pack('<II', sr, sr * 2) + struct.pack('<HH', 2, 16)
           + b"data" + struct.pack('<I', n))
           
    with open(out, "wb") as f:
        f.write(hdr)
        f.write(pcm)


def record_while_held(rec_path: str, held_check=None, status_cb=None) -> bool:
    """Record audio in 1-second chunks as long as held_check() returns True."""
    import os

    if held_check is None:
        held_check = lambda: M5.BtnC.isPressed()

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
        try: os.remove(rec_path)
        except OSError: pass
        os.rename(chunks[0], rec_path)
    else:
        _merge_chunks(chunks, rec_path)
        
    print("[REC] Total %ds recorded" % total)
    return True


# ── Voice Upload & Playback ───────────────────────────────────────────────────

def upload_voice_and_receive(rec_path: str) -> bytes | None:
    """Uploads the WAV file to the Flask backend and waits for the TTS audio reply."""
    try:
        with open(rec_path, "rb") as f:
            wav = f.read()
            
        print("[Voice] Uploading %d bytes" % len(wav))
        
        resp = requests.post(config.VOICE_URL, data=wav,
                             headers={"Content-Type": "audio/wav"}, timeout=10)
                             
        if resp.status_code == 204:
            resp.close()
            return None
            
        audio = resp.content
        resp.close()
        print("[Voice] Received %d bytes of TTS audio" % len(audio))
        return audio
        
    except Exception as e:
        print("[Voice] Communication Error:", e)
        return None


def play_wav_from_memory(wav_bytes: bytes) -> None:
    """Plays the raw PCM data from the downloaded WAV file in memory."""
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
    """Trigger the Core2 internal vibration motor for tactile feedback."""
    try:
        M5.Power.setVibration(intensity)
        time.sleep_ms(ms)
        M5.Power.setVibration(0)
    except Exception:
        pass