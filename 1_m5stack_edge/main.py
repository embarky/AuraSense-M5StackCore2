import network
import socket
import machine
import time
import json
import sys
import urequests
from machine import I2C, Pin
import unit
from m5stack import lcd, btnA, btnB

# ==========================================
# 1. Core Configuration & UI Constants
# ==========================================
CONFIG_FILE = "config.json"
AP_SSID = "M5Stack_Smart_Setup"
API_URL = "http://10.145.83.153:5001/api/sensor_data" 

COLOR_BG = 0x000000
COLOR_TITLE = 0xFFA500
COLOR_TEXT = 0xFFFFFF
COLOR_VAL_1 = 0x00FFFF  
COLOR_VAL_2 = 0xFFFF00  
COLOR_OK = 0x00FF00
COLOR_ERR = 0xFF0000

# ==========================================
# 2. Hardware & Sensor Drivers
# ==========================================
class SGP30_Driver:
    """Manual I2C driver to bypass UIFlow's default SGP30 limitations."""
    def __init__(self, i2c_bus, address=0x58):
        self.i2c = i2c_bus
        self.addr = address
        try:
            self.i2c.writeto(self.addr, b'\x20\x03')
            time.sleep_ms(10)
        except:
            pass
            
    def read(self):
        self.i2c.writeto(self.addr, b'\x20\x08')
        time.sleep_ms(20)
        data = self.i2c.readfrom(self.addr, 6)
        eco2 = (data[0] << 8) | data[1]
        tvoc = (data[3] << 8) | data[4]
        return tvoc, eco2

lcd.clear(COLOR_BG)
lcd.font(lcd.FONT_DejaVu18)
lcd.print("Smart Space Node", 70, 5, COLOR_TITLE)
lcd.drawLine(0, 30, 320, 30, COLOR_TEXT)
lcd.print("Initializing Sensors...", 10, 40, COLOR_TEXT)

try:
    i2c_a = I2C(1, scl=Pin(33), sda=Pin(32), freq=100000)
    air_sensor = SGP30_Driver(i2c_a)
except Exception as e:
    print("Air Sensor Init Error")

try:
    pir_sensor = unit.get(unit.PIR, unit.PORTB)
except Exception as e:
    print("PIR Sensor Init Error")

try:
    env_sensor = unit.get(unit.ENV3, unit.PORTC)
except Exception as e:
    print("ENV Sensor Init Error")

# ==========================================
# 3. Smart Provisioning & Captive Portal
# ==========================================
def boot_manager():
    """Boot menu: Btn A for Dev Mode, Btn B for Wi-Fi Reset."""
    lcd.fillRect(0, 31, 320, 209, COLOR_BG)
    lcd.print("Booting System...", 60, 60, COLOR_TEXT)
    lcd.print("Btn A (Left): Dev Mode", 20, 100, COLOR_TITLE)
    lcd.print("Btn B (Mid):  Reset Wi-Fi", 20, 140, COLOR_VAL_1)
    
    force_setup = False
    
    for i in range(30):
        if i % 10 == 0:
            seconds_left = 3 - (i // 10)
            lcd.print("Auto-start in " + str(seconds_left) + "s...   ", 90, 180, COLOR_OK)
            
        # Left Button: Developer Escape Hatch
        if btnA.isPressed() or btnA.wasPressed():
            lcd.clear(COLOR_BG)
            lcd.print("Dev Mode Active!", 80, 100, COLOR_ERR)
            lcd.print("USB REPL is free.", 80, 130, COLOR_TEXT)
            print("Developer mode activated. Exiting main.py...")
            sys.exit() 
            
        # Middle Button: Force Wi-Fi Setup
        if btnB.isPressed() or btnB.wasPressed():
            lcd.clear(COLOR_BG)
            lcd.print("Resetting Wi-Fi...", 70, 100, COLOR_TITLE)
            print("User requested Wi-Fi reset.")
            force_setup = True
            time.sleep(1)
            break 
            
        time.sleep(0.1)
        
    return force_setup

def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.loads(f.read())
    except:
        return {"ssid": "", "pwd": ""}

def save_config(ssid, pwd):
    with open(CONFIG_FILE, 'w') as f:
        json.dump({"ssid": ssid, "pwd": pwd}, f)

def start_smart_config():
    """Starts AP mode, DNS Hijacking (Captive Portal), and Web Server."""
    sta = network.WLAN(network.STA_IF)
    sta.active(True)
    lcd.fillRect(0, 31, 320, 209, COLOR_BG)
    lcd.print("Scanning Wi-Fi...", 80, 110, COLOR_OK)
    
    try:
        networks = sta.scan()
    except Exception as e:
        networks = []
    
    ssid_options = ""
    seen_ssids = set()
    for net in networks:
        ssid_name = net[0].decode('utf-8')
        if ssid_name and ssid_name not in seen_ssids: 
            seen_ssids.add(ssid_name)
            ssid_options += '<option value="' + ssid_name + '">' + ssid_name + '</option>'
            
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.config(essid=AP_SSID, authmode=0) 
    
    lcd.fillRect(0, 31, 320, 209, COLOR_BG)
    lcd.print("1. Scan QR or Join Wi-Fi", 40, 40, COLOR_TEXT)
    qr_data = "WIFI:S:" + AP_SSID + ";T:nopass;P:;;"
    lcd.qrcode(qr_data, x=70, y=70, width=130)
    lcd.print("2. Wait for Auto-Popup", 60, 210, COLOR_VAL_1)
    lcd.print("Or go to 192.168.4.1", 70, 230, COLOR_TITLE)
    
    html_p1 = """<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no"><style>body{font-family:-apple-system,sans-serif;background-color:#f4f4f9;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;}.card{background:white;padding:30px;border-radius:15px;box-shadow:0 10px 20px rgba(0,0,0,0.1);width:85%;max-width:400px;text-align:center;}h2{color:#333;margin-bottom:20px;}select,input{width:100%;padding:12px;margin:10px 0 20px 0;border:1px solid #ccc;border-radius:8px;font-size:16px;box-sizing:border-box;}input[type="submit"]{background:#007AFF;color:white;border:none;font-weight:bold;cursor:pointer;transition:0.3s;}</style></head><body><div class="card"><h2>🌍 Smart Space Setup</h2><form action="/" method="get"><div style="text-align:left;color:#666;font-size:14px;">Select Wi-Fi:</div><select name="ssid">"""
    html_p2 = """<option value="Manual_Input">-- Other (Manual Input) --</option></select><div style="text-align:left;color:#666;font-size:14px;">Password:</div><input type="password" name="pwd" placeholder="Enter password"><input type="submit" value="Connect Device"></form></div></body></html>"""
    html = html_p1 + ssid_options + html_p2

    dns_s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dns_s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    dns_s.bind(('', 53))
    dns_s.setblocking(False)

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('', 80))
    s.listen(1)
    
    print("Captive Portal Active. Waiting for phone...")
    
    while True:
        try:
            req, addr = dns_s.recvfrom(1024)
            ip_bytes = bytes([192, 168, 4, 1])
            response = req[:2] + b'\x81\x80' + req[4:6] + b'\x00\x01\x00\x00\x00\x00'
            qname_len = req[12:].find(b'\x00') + 5
            response += req[12:12+qname_len]
            response += b'\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04' + ip_bytes
            dns_s.sendto(response, addr)
        except OSError:
            pass

        try:
            s.settimeout(0.2)
            conn, addr = s.accept()
            s.settimeout(None)
            request = conn.recv(1024).decode('utf-8')
            
            if 'GET /?ssid=' in request:
                try:
                    params = request.split('GET /?')[1].split(' HTTP')[0]
                    pairs = params.split('&')
                    new_ssid = pairs[0].split('=')[1].replace('+', ' ').replace('%20', ' ')
                    new_pwd = pairs[1].split('=')[1].replace('+', ' ').replace('%20', ' ')
                    
                    save_config(new_ssid, new_pwd)
                        
                    conn.send('HTTP/1.1 200 OK\nContent-Type: text/html\nConnection: close\n\n')
                    success_html = """<body style="font-family:sans-serif;text-align:center;margin-top:20vh;background:#f4f4f9;"><h2 style="color:#00C851;">✅ Saved!</h2><p>Device is restarting...</p></body>"""
                    conn.send(success_html)
                    conn.close()
                    
                    lcd.fillRect(0, 31, 320, 209, COLOR_BG)
                    lcd.print("Applying Settings...", 60, 110, COLOR_OK)
                    time.sleep(2)
                    machine.reset()
                except Exception as e:
                    conn.close()
            else:
                conn.send('HTTP/1.1 200 OK\nContent-Type: text/html\nConnection: close\n\n')
                conn.send(html)
                conn.close()
        except OSError:
            pass

def connect_network(force_setup=False):
    """Network logic. Can be forced into Setup Mode."""
    lcd.fillRect(0, 31, 320, 209, COLOR_BG)
    
    if force_setup:
        start_smart_config()
        return

    lcd.print("Connecting Wi-Fi...", 60, 110, COLOR_TEXT)
    
    config = load_config()
    ssid = config.get("ssid", "")
    pwd = config.get("pwd", "")
    
    sta = network.WLAN(network.STA_IF)
    sta.active(True)
    
    if not sta.isconnected():
        if ssid:
            sta.connect(ssid, pwd)
            timeout = 10
            while not sta.isconnected() and timeout > 0:
                time.sleep(1)
                timeout -= 1
        
        if not sta.isconnected():
            start_smart_config()
            
    lcd.fillRect(0, 31, 320, 209, COLOR_BG)
    lcd.print("Wi-Fi Connected! ✅", 70, 110, COLOR_OK)
    time.sleep(1)

def clear_line(y, height=22):
    lcd.fillRect(10, y, 300, height, COLOR_BG)

# ==========================================
# 4. Main Execution Entry Point
# ==========================================

# 1. Show Boot Menu (Returns True if user presses Btn B)
force_wifi_setup = boot_manager()

# 2. Handle Network (Pass the boolean flag)
connect_network(force_setup=force_wifi_setup)

# 3. Draw main UI framework
lcd.fillRect(0, 31, 320, 209, COLOR_BG)
sta = network.WLAN(network.STA_IF)

while True:
    # --- Data Acquisition ---
    try:
        t = env_sensor.temperature
        h = env_sensor.humidity
        p = env_sensor.pressure
        v, c = air_sensor.read()
        motion = pir_sensor.state
    except Exception as e:
        t, h, p, v, c, motion = 0.0, 0.0, 0.0, 0, 0, 0

    # --- UI Rendering ---
    clear_line(40)
    lcd.print("Temp: " + str(round(t, 1)) + " C", 10, 40, COLOR_TEXT)
    clear_line(65)
    lcd.print("Hum:  " + str(round(h, 1)) + " %", 10, 65, COLOR_VAL_1)
    
    clear_line(100)
    lcd.print("TVOC: " + str(v) + " ppb", 10, 100, COLOR_VAL_2)
    clear_line(125)
    lcd.print("eCO2: " + str(c) + " ppm", 10, 125, 0xCCCCCC)

    clear_line(165, 30)
    if motion == 1:
        lcd.print(">>> MOTION DETECTED <<<", 10, 170, COLOR_ERR)
    else:
        lcd.print("Area Status: Clear", 10, 170, COLOR_OK)

    # --- Cloud Transmission ---
    if sta.isconnected():
        try:
            payload = {
                "temperature": round(t, 2),
                "humidity": round(h, 2),
                "pressure": round(p, 2),
                "tvoc": v,
                "eco2": c,
                "motion_detected": motion
            }
            headers = {'Content-Type': 'application/json'}
            res = urequests.post(API_URL, json=payload, headers=headers)
            lcd.circle(310, 15, 5, COLOR_OK) 
            res.close()
        except Exception as e:
            lcd.circle(310, 15, 5, COLOR_ERR)
            print("HTTP POST Failed:", e)
    else:
        lcd.circle(310, 15, 5, COLOR_TITLE)
    
    time.sleep(5)
