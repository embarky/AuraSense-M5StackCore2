# connectivity.py — WiFi, NTP sync, sensor upload, and voice assistant.
#
# Implements non-blocking architectural patterns, strict timeouts, 
# guaranteed socket closures (via finally), and an aggressive software 
# watchdog to recover from LwIP SRAM exhaustion and consecutive timeouts.

import json
import struct
import time
import network
import requests
import ntptime
import machine
from machine import I2C, Pin
import M5
from M5 import *

import config

# Global counter for the software watchdog
_consecutive_upload_fails = 0


# ── WiFi ──────────────────────────────────────────────────────────────────────

def wifi_connect(status_cb=None) -> bool:
    """Connect to the configured Wi-Fi network with visual feedback."""
    def _log(msg, color=0xFFFF00):
        print("[WiFi]", msg)
        if status_cb:
            status_cb(msg, color)

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    
    # 🌟 GHOST CONNECTION CRUSHER: 
    # Force a disconnect to clear any half-open states in the router
    # caused by a previous Watchdog hardware reset.
    try:
        wlan.disconnect()
        time.sleep(1)
    except Exception:
        pass
    
    if wlan.isconnected():
        _log("Connected: " + wlan.ifconfig()[0], 0x00FF00)
        return True
        
    if not config.WIFI_SSID:
        _log("No SSID Configured", 0xFF0000)
        return False
        
    _log("Connecting to " + config.WIFI_SSID)
    wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
    
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

def sync_ntp() -> bool:
    """Fetch UTC time from NTP. Timezone offsets are handled dynamically."""
    if not is_connected():
        print("[NTP] Failed: No WiFi")
        return False

    try:
        print("[NTP] Syncing with pool.ntp.org...")
        ntptime.settime()
        print("[NTP] Success! System time set to UTC.")
        return True
    except Exception as e:
        print("[NTP] Error during sync:", e)
        return False


# ── Sensor Upload & Watchdog ──────────────────────────────────────────────────

def upload_sensor_data(sensor_data: dict):
    """
    Upload sensor readings to the backend.
    Includes a Software Watchdog: reboots the ESP32 on LwIP memory 
    exhaustion (errno 12/105) or 5 consecutive timeouts.
    """
    global _consecutive_upload_fails
    clean = {k: (v if v is not None else 0) for k, v in sensor_data.items()}
    resp = None
    
    try:
        payload = json.dumps(clean)
        headers = {
            "Content-Type":   "application/json",
            "Connection":     "close",
            "Content-Length": str(len(payload)),
        }
        resp = requests.post(config.SENSOR_URL, data=payload, headers=headers, timeout=3)
        
        if resp.status_code == 200:
            _consecutive_upload_fails = 0  # Reset watchdog counter on success
            return resp.json()
            
        print("[Upload] Server Error HTTP", resp.status_code)
        return None
        
    except Exception as e:
        _consecutive_upload_fails += 1
        print(f"[Upload] Request Failed: {e} | Consecutive Fails: {_consecutive_upload_fails}")
        
        try:
            err_code = e.args[0]
        except Exception:
            err_code = 0
            
        # 🌟 SOFTWARE WATCHDOG TRIGGER
        # 12 = ENOMEM, 105 = ENOBUFS (Internal SRAM exhausted)
        if err_code in (12, 105) or _consecutive_upload_fails >= 15:
            print("=========================================")
            print("🚨 FATAL: Network stack blocked or SRAM depleted!")
            print("🚨 Triggering hardware watchdog reset...")
            print("=========================================")
            if resp is not None:
                try: resp.close()
                except Exception: pass
            time.sleep(1)
            machine.reset()  # Full system reboot to clear zombie sockets
            
        return None
        
    finally:
        # GUARANTEED execution: Prevent standard memory leaks
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass


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
    total  = 1
    _log("REC 1s")
    _vibrate(50)

    while True:
        chunk = "/flash/chunk_%d.wav" % len(chunks)
        Mic.recordWavFile(chunk, config.REC_RATE, 1, False)
        chunks.append(chunk)
        
        M5.update()
        
        if not held_check() or total >= config.MAX_REC_SECONDS:
            break
        total += 1
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

def upload_voice_and_receive(rec_path: str):
    """Uploads the WAV file to the Flask backend and waits for TTS audio."""
    resp = None
    try:
        with open(rec_path, "rb") as f:
            wav = f.read()
            
        print("[Voice] Uploading %d bytes" % len(wav))
        
        resp = requests.post(config.VOICE_URL, data=wav,
                             headers={"Content-Type": "audio/wav"}, timeout=10)
                             
        if resp.status_code == 204:
            return None
            
        audio = resp.content
        print("[Voice] Received %d bytes of TTS audio" % len(audio))
        return audio
        
    except Exception as e:
        print("[Voice] Communication Error:", e)
        return None
    finally:
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass


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


# ── Weather API ───────────────────────────────────────────────────────────────

def fetch_forecast():
    """Fetch the 5-day weather forecast from the backend."""
    if not is_connected():
        print("[Weather] Failed: No WiFi")
        return None

    resp = None
    try:
        resp = requests.get(config.WEATHER_URL, timeout=3)
        
        if resp.status_code == 200:
            result = resp.json()
            forecast = result.get("forecast", [])
            print("[Weather] Fetched", len(forecast), "days")
            return forecast
            
        print("[Weather] Server Error HTTP", resp.status_code)
        return None
        
    except Exception as e:
        print("[Weather] Request Failed (Timeout/Network):", e)
        return None
    finally:
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass


# ── Announcement & Alert ──────────────────────────────────────────────────────

def speak_announcement(sensor_data: dict, outdoor: dict, forecast: list):
    """Send current context to backend /speak endpoint."""
    if not is_connected():
        print("[Speak] Failed: No WiFi")
        return None

    resp = None
    try:
        payload = json.dumps({
            "sensor_data": sensor_data,
            "outdoor":     outdoor,
            "forecast":    forecast,
        })
        url = "http://{}:{}/speak".format(config.SERVER_HOST, config.SERVER_PORT)
        resp = requests.post(url, data=payload,
                             headers={"Content-Type": "application/json"}, timeout=10)
                             
        if resp.status_code == 200:
            audio = resp.content
            print("[Speak] Received", len(audio), "bytes")
            return audio
            
        print("[Speak] Server error HTTP", resp.status_code)
        return None
        
    except Exception as e:
        print("[Speak] Failed:", e)
        return None
    finally:
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass


def speak_alert(sensor_data: dict, anomaly_type: str):
    """Send anomaly data to backend /alert endpoint."""
    if not is_connected():
        print("[Alert] Failed: No WiFi")
        return None

    resp = None
    try:
        payload = json.dumps({
            "sensor_data":  sensor_data,
            "anomaly_type": anomaly_type,
        })
        url = "http://{}:{}/alert".format(config.SERVER_HOST, config.SERVER_PORT)
        resp = requests.post(url, data=payload,
                             headers={"Content-Type": "application/json"}, timeout=10)
                             
        if resp.status_code == 200:
            audio = resp.content
            print("[Alert] Received", len(audio), "bytes")
            return audio
            
        print("[Alert] Server error HTTP", resp.status_code)
        return None
        
    except Exception as e:
        print("[Alert] Failed:", e)
        return None
    finally:
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass