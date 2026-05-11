# network.py — All network operations: WiFi, sensor upload, voice assistant.
#
# Three responsibilities:
#   1. wifi_connect()         — connect on startup or reconnect if dropped
#   2. upload_sensor_data()   — POST sensor readings to backend
#   3. Voice assistant        — record while held, upload WAV, play reply

import struct
import time

import device.connectivity as net
import requests
from machine import I2C, Pin
import M5
from M5 import *

import config


# ── WiFi ──────────────────────────────────────────────────────────────────────

def wifi_connect(status_cb=None) -> bool:
    """
    Connect to the configured WiFi network.

    Parameters
    ----------
    status_cb : optional callable(msg, color) for UI feedback.

    Returns True on success, False on failure.
    """
    def _status(msg, color=0xFFFF00):
        print("[WiFi]", msg)
        if status_cb:
            status_cb(msg, color)

    wlan = net.WLAN(net.STA_IF)
    wlan.active(True)

    if wlan.isconnected():
        _status("Already connected: " + wlan.ifconfig()[0], 0x3fb950)
        return True

    _status("Connecting...")
    wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)

    for _ in range(20):
        if wlan.isconnected():
            _status("WiFi OK  " + wlan.ifconfig()[0], 0x3fb950)
            return True
        time.sleep(1)

    _status("WiFi FAILED", 0xFF4444)
    return False


def is_connected() -> bool:
    wlan = net.WLAN(net.STA_IF)
    return wlan.isconnected()


# ── Sensor data upload ────────────────────────────────────────────────────────

def upload_sensor_data(sensor_data: dict) -> dict | None:
    """
    POST the sensor reading dict to the backend /api/sensor_data endpoint.

    Returns the JSON response dict (contains outdoor weather + NTP time),
    or None on failure.
    """
    try:
        resp = requests.post(
            config.SENSOR_URL,
            json=sensor_data,
            headers={"Content-Type": "application/json"},
        )
        if resp.status_code == 200:
            result = resp.json()
            resp.close()
            return result
        resp.close()
        print("[Upload] Server error:", resp.status_code)
    except Exception as e:
        print("[Upload] Failed:", e)
    return None


# ── AXP192 mic power (Core2 hardware requirement) ────────────────────────────

def _axp_mic_on() -> None:
    """Enable microphone power via AXP192 power management chip."""
    i2c = I2C(0, scl=Pin(22), sda=Pin(21), freq=400000)
    i2c.writeto_mem(0x34, 0x12, bytes([0x57]))
    i2c.writeto_mem(0x34, 0x96, bytes([0x06]))
    time.sleep(0.3)


# ── WAV chunk recording ───────────────────────────────────────────────────────

def _merge_wav_chunks(chunk_paths: list, out_path: str) -> None:
    """Concatenate PCM data from multiple WAV files into one WAV file."""
    import os
    all_pcm = b""
    for path in chunk_paths:
        try:
            with open(path, "rb") as f:
                all_pcm += f.read()[44:]   # strip 44-byte WAV header
            os.remove(path)
        except Exception as e:
            print("[MERGE ERR]", path, e)

    n   = len(all_pcm)
    sr  = config.REC_RATE
    hdr = (b"RIFF" + struct.pack('<I', 36 + n)
           + b"WAVEfmt " + struct.pack('<I', 16)
           + struct.pack('<H', 1)            # PCM
           + struct.pack('<H', 1)            # mono
           + struct.pack('<I', sr)
           + struct.pack('<I', sr * 2)
           + struct.pack('<H', 2)
           + struct.pack('<H', 16)
           + b"data" + struct.pack('<I', n))
    with open(out_path, "wb") as f:
        f.write(hdr)
        f.write(all_pcm)
    print("[MERGE] %d chunks → %d bytes" % (len(chunk_paths), len(hdr) + n))


def record_while_held(rec_path: str, status_cb=None) -> bool:
    """
    Record audio while Button A is held, save to rec_path.

    Records in 1-second chunks and merges them so the button
    release is detected within 1 second.

    Returns True if a usable recording was captured.
    """
    import os

    def _status(msg, color=0xFF4444):
        print("[REC]", msg)
        if status_cb:
            status_cb(msg, color)

    CHUNK_SEC = 1

    Speaker.end()
    time.sleep_ms(100)
    _axp_mic_on()
    Mic.begin()
    try:
        Mic.setGain(config.MIC_GAIN)
    except Exception:
        pass

    chunks    = []
    total_sec = 0
    _status("REC...")
    _vibrate(50)

    while True:
        chunk_path = "/flash/chunk_%d.wav" % len(chunks)
        Mic.recordWavFile(chunk_path, config.REC_RATE, CHUNK_SEC, False)
        chunks.append(chunk_path)
        total_sec += CHUNK_SEC

        M5.update()
        if not M5.BtnA.isPressed() or total_sec >= config.MAX_REC_SECONDS:
            break
        _status("REC %ds" % total_sec)

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
        _merge_wav_chunks(chunks, rec_path)

    print("[REC] %ds recorded" % total_sec)
    return True


def upload_voice_and_receive(rec_path: str) -> bytes | None:
    """
    Upload recorded WAV to /voice and return the reply WAV bytes in memory.
    Returns None if the server indicates silence (204) or on error.
    """
    try:
        with open(rec_path, "rb") as f:
            wav_bytes = f.read()

        print("[Voice] Uploading %d bytes" % len(wav_bytes))
        resp = requests.post(
            config.VOICE_URL,
            data=wav_bytes,
            headers={"Content-Type": "audio/wav"},
        )

        if resp.status_code == 204:
            resp.close()
            return None

        audio = resp.content
        resp.close()
        print("[Voice] Received %d bytes" % len(audio))
        return audio

    except Exception as e:
        print("[Voice] Upload error:", e)
        return None


def play_wav_from_memory(wav_bytes: bytes) -> None:
    """
    Play a WAV file stored in RAM directly via Speaker.playRaw.
    Skips the 44-byte WAV header to extract raw PCM.
    Avoids writing to flash, saving ~7 seconds.
    """
    Speaker.begin()
    Speaker.setVolume(config.SPK_VOLUME)
    pcm = wav_bytes[44:]
    Speaker.playRaw(pcm, config.REC_RATE, False)
    try:
        while Speaker.isPlaying():
            M5.update()
            time.sleep_ms(50)
    except Exception:
        pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def _vibrate(ms: int = 80, intensity: int = 180) -> None:
    try:
        M5.Power.setVibration(intensity)
        time.sleep_ms(ms)
        M5.Power.setVibration(0)
    except Exception:
        pass