import network
import socket
import machine
import time
import json
import sys
import urequests
from machine import I2C, Pin
import unit
from m5stack import lcd, btnA, btnB, btnC, touch

# ==========================================
# 1. Hardware Compatibility Layer (AXP Fix)
# ==========================================
# Try multiple ways to obtain the AXP power management object 
# to support various firmware versions.
axp = None
try:
    from m5stack import axp as _axp
    axp = _axp
except ImportError:
    try:
        import axp
    except ImportError:
        pass

def set_screen_brightness(level):
    """Safely adjust LCD brightness using the most compatible method available."""
    try:
        if hasattr(lcd, 'setBrightness'):
            lcd.setBrightness(level)
            return
    except: pass
    
    if axp is not None:
        try:
            if hasattr(axp, 'setLcdBrightness'): 
                axp.setLcdBrightness(level)
            elif hasattr(axp, 'lcd_brightness'): 
                axp.lcd_brightness(level)
        except: pass

# ==========================================
# 2. Core Configuration & UI Constants
# ==========================================
CONFIG_FILE = "config.json"
AP_SSID = "M5Stack_Smart_Setup"
API_URL = "http://10.145.83.153:5001/api/sensor_data" 

COLOR_BG = 0x000000
COLOR_PANEL = 0x1C1C1C
COLOR_TITLE = 0xFFA500
COLOR_TEXT = 0xFFFFFF
COLOR_VAL_1 = 0x00FFFF  
COLOR_VAL_2 = 0xFFFF00  
COLOR_OK = 0x00FF00
COLOR_ERR = 0xFF0000
COLOR_GREY = 0x888888

# ==========================================
# 3. Hardware Drivers
# ==========================================
class SGP30_Driver:
    """I2C Driver for SGP30 Air Quality Sensor"""
    def __init__(self, i2c_bus, address=0x58):
        self.i2c = i2c_bus
        self.addr = address
        try:
            self.i2c.writeto(self.addr, b'\x20\x03')
            time.sleep_ms(10)
        except: pass
            
    def read(self):
        try:
            self.i2c.writeto(self.addr, b'\x20\x08')
            time.sleep_ms(20)
            data = self.i2c.readfrom(self.addr, 6)
            eco2 = (data[0] << 8) | data[1]
            tvoc = (data[3] << 8) | data[4]
            return tvoc, eco2
        except: return 0, 400

# Initialize Hardware Components
lcd.clear(COLOR_BG)
try:
    i2c_a = I2C(1, scl=Pin(33), sda=Pin(32), freq=100000)
    air_sensor = SGP30_Driver(i2c_a)
    pir_sensor = unit.get(unit.PIR, unit.PORTB)
    env_sensor = unit.get(unit.ENV3, unit.PORTC)
except Exception as e: print("Sensor Init Failed:", e)

# ==========================================
# 4. Boot & Provisioning (Captive Portal)
# ==========================================
def boot_manager():
    """Handles boot menu for dev mode or forced Wi-Fi reset"""
    lcd.fillRect(0, 0, 320, 240, COLOR_BG)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print("SYSTEM BOOTING", 90, 40, COLOR_TITLE)
    lcd.print("A: Dev Mode", 40, 100, COLOR_TEXT)
    lcd.print("B: Force Wi-Fi Setup", 40, 130, COLOR_VAL_1)
    
    force_setup = False
    for i in range(30):
        if i % 10 == 0:
            lcd.fillRect(90, 180, 200, 30, COLOR_BG)
            lcd.print("Starting in " + str(3-(i//10)) + "s...", 90, 180, COLOR_OK)
        if btnA.isPressed(): sys.exit() 
        if btnB.isPressed():
            force_setup = True
            break
        time.sleep(0.1)
    return force_setup

def load_config():
    """Loads saved Wi-Fi credentials from local flash."""
    try:
        with open(CONFIG_FILE, 'r') as f: return json.loads(f.read())
    except: return {"ssid": "", "pwd": ""}

def save_config(ssid, pwd):
    """Saves Wi-Fi credentials to local flash."""
    with open(CONFIG_FILE, 'w') as f: json.dump({"ssid": ssid, "pwd": pwd}, f)

def url_unquote(s):
    """Decodes URL-encoded passwords with special characters sent from the mobile device."""
    s = s.replace('+', ' ')
    parts = s.split('%')
    res = parts[0]
    for p in parts[1:]:
        try: res += chr(int(p[:2], 16)) + p[2:]
        except: res += '%' + p
    return res

def start_smart_config():
    """Starts Access Point and Captive Portal for Wi-Fi credentials setup."""
    sta = network.WLAN(network.STA_IF)
    sta.active(True)
    lcd.fillRect(0, 0, 320, 240, COLOR_BG)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print("Waking up Wi-Fi...", 80, 110, COLOR_OK)
    
    # [CORE FIX]: Allow the hardware antenna 2 seconds to gather surrounding Wi-Fi signals.
    time.sleep(2)
    
    try: networks = sta.scan()
    except: networks = []
    
    ssid_options = ""
    seen_ssids = set()
    for net in networks:
        try:
            # [CORE FIX]: Safely decode and filter out Wi-Fi names with special characters that cause crashes.
            ssid_name = net[0].decode('utf-8', 'ignore').strip()
            if ssid_name and ssid_name not in seen_ssids: 
                seen_ssids.add(ssid_name)
                ssid_options += '<option value="' + ssid_name + '">' + ssid_name + '</option>'
        except: pass
            
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.config(essid=AP_SSID, authmode=0) 
    
    lcd.fillRect(0, 0, 320, 240, COLOR_BG)
    lcd.print("1. Scan QR or Join Wi-Fi", 40, 40, COLOR_TEXT)
    qr_data = "WIFI:S:" + AP_SSID + ";T:nopass;P:;;"
    lcd.qrcode(qr_data, x=70, y=70, width=130)
    lcd.print("2. Wait for Auto-Popup", 60, 210, COLOR_VAL_1)
    
    # HTML UI for the captive portal
    html = (
        '<!DOCTYPE html><html><head><meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">'
        '<style>body{font-family:-apple-system,sans-serif;background-color:#f4f4f9;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;}'
        '.card{background:white;padding:30px;border-radius:15px;box-shadow:0 10px 20px rgba(0,0,0,0.1);width:85%;max-width:400px;text-align:center;}'
        'h2{color:#333;margin-bottom:20px;}select,input{width:100%;padding:12px;margin:10px 0 20px 0;border:1px solid #ccc;border-radius:8px;font-size:16px;box-sizing:border-box;}'
        'input[type="submit"]{background:#007AFF;color:white;border:none;font-weight:bold;cursor:pointer;transition:0.3s;}</style></head>'
        '<body><div class="card"><h2>Smart Space Setup</h2>'
        '<form action="/" method="get"><div style="text-align:left;color:#666;font-size:14px;">Select Wi-Fi:</div>'
        '<select name="ssid">' + ssid_options + '<option value="Manual_Input">-- Other (Manual Input) --</option></select>'
        '<div style="text-align:left;color:#666;font-size:14px;">Password:</div>'
        '<input type="password" name="pwd" placeholder="Enter password">'
        '<input type="submit" value="Connect Device"></form></div></body></html>'
    )

    # Setup DNS server to hijack requests
    dns_s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dns_s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    dns_s.bind(('', 53))
    dns_s.setblocking(False)

    # Setup Web server
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('', 80))
    s.listen(1)
    
    while True:
        # DNS Handling
        try:
            r, a = dns_s.recvfrom(1024)
            dns_s.sendto(r[:2]+b'\x81\x80\x00\x01\x00\x01\x00\x00\x00\x00'+r[12:12+r[12:].find(b'\x00')+5]+b'\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04\xc0\xa8\x04\x01', a)
        except: pass

        # HTTP Handling
        try:
            s.settimeout(0.2)
            conn, addr = s.accept()
            s.settimeout(None)
            request = conn.recv(1024).decode('utf-8')
            
            if 'GET /?ssid=' in request:
                try:
                    params = request.split('GET /?')[1].split(' HTTP')[0].split('&')
                    new_ssid = url_unquote(params[0].split('=')[1])
                    new_pwd = url_unquote(params[1].split('=')[1])
                    
                    save_config(new_ssid, new_pwd)
                    conn.send('HTTP/1.1 200 OK\nContent-Type: text/html\nConnection: close\n\n')
                    conn.send("""<body style="font-family:sans-serif;text-align:center;margin-top:20vh;background:#f4f4f9;"><h2 style="color:#00C851;">Saved!</h2><p>Restarting...</p></body>""")
                    conn.close()
                    machine.reset()
                except Exception as e: conn.close()
            else:
                conn.send('HTTP/1.1 200 OK\nContent-Type: text/html\nConnection: close\n\n')
                conn.send(html)
                conn.close()
        except: pass

# --- [CORE FEATURE]: Graceful degradation to Offline Mode ---
def connect_network(force):
    """Attempts to connect to Wi-Fi. Falls back to local mode if connection fails."""
    sta = network.WLAN(network.STA_IF)
    sta.active(True)
    if force: start_smart_config() # User manually forced Wi-Fi setup via hardware button.
    
    cfg = load_config()
    if cfg.get("ssid"):
        lcd.clear(COLOR_BG)
        lcd.font(lcd.FONT_DejaVu18)
        lcd.print("Connecting to:", 40, 100, COLOR_TEXT)
        lcd.print(cfg["ssid"], 40, 130, COLOR_VAL_1)
        
        sta.connect(cfg["ssid"], cfg["pwd"])
        for i in range(15):
            if sta.isconnected(): 
                lcd.clear(COLOR_BG)
                lcd.print("Connected!", 100, 110, COLOR_OK)
                time.sleep(1)
                return # Successfully connected, proceed to main loop.
            time.sleep(1)
            
        # Connection failed after retries, fallback to local Offline Mode.
        sta.disconnect()
        lcd.clear(COLOR_BG)
        lcd.print("Offline Mode", 100, 100, COLOR_ERR)
        lcd.print("Press [B] to config Wi-Fi", 30, 130, COLOR_GREY)
        time.sleep(2.5)
    else:
        # No previous Wi-Fi configuration found, default to local Offline Mode.
        lcd.clear(COLOR_BG)
        lcd.font(lcd.FONT_DejaVu18)
        lcd.print("Local Mode", 110, 100, COLOR_GREY)
        lcd.print("Press [B] to config Wi-Fi", 30, 130, COLOR_TEXT)
        time.sleep(2.5)
    
    # Note: We no longer force start_smart_config() which blocks the user.
    # Instead, we let the function complete and enter the main monitoring loop.

# ==========================================
# 5. Icon Drawing Engine (Vector Graphics)
# ==========================================
def draw_temp_icon(x, y, color):
    lcd.fillRect(x+3, y, 4, 12, color); lcd.fillCircle(x+5, y+14, 5, color)

def draw_hum_icon(x, y, color):
    lcd.fillCircle(x+6, y+10, 6, color); lcd.fillTriangle(x+1, y+10, x+11, y+10, x+6, y, color)

def draw_co2_icon(x, y, color):
    lcd.fillCircle(x+5, y+10, 5, color); lcd.fillCircle(x+15, y+10, 5, color); lcd.fillCircle(x+10, y+5, 6, color)

# ==========================================
# 6. Dashboard Routing & Rendering
# ==========================================
def draw_dashboard_static():
    """Renders the static UI framework for the Main Dashboard"""
    lcd.clear(COLOR_BG); lcd.fillRect(0, 0, 320, 30, COLOR_PANEL)
    lcd.font(lcd.FONT_DejaVu18); lcd.print("SMART SPACE", 10, 5, COLOR_TITLE)
    draw_co2_icon(185, 75, COLOR_GREY); lcd.print("PPM CO2", 210, 75, COLOR_GREY)
    lcd.font(lcd.FONT_Default); lcd.print("Comfort Level", 10, 150, COLOR_GREY); lcd.drawRect(110, 153, 190, 10, COLOR_TEXT)
    lcd.drawLine(0, 175, 320, 175, COLOR_PANEL); lcd.drawLine(106, 175, 106, 240, COLOR_PANEL); lcd.drawLine(212, 175, 212, 240, COLOR_PANEL)
    draw_temp_icon(15, 218, COLOR_GREY); lcd.print("INDOOR", 30, 220, COLOR_GREY)
    draw_hum_icon(115, 218, COLOR_GREY); lcd.print("HUMIDITY", 135, 220, COLOR_GREY)
    draw_temp_icon(225, 218, COLOR_GREY); lcd.print("OUTDOOR", 240, 220, COLOR_GREY)
    
    lcd.print("[B] WIFI", 140, 160, 0x555555)
    lcd.print("[C] TREND", 255, 160, 0x555555)

def draw_chart_static():
    """Renders the static UI framework for the Trend Chart"""
    lcd.clear(COLOR_BG); lcd.fillRect(0, 0, 320, 30, COLOR_PANEL)
    lcd.font(lcd.FONT_DejaVu18); lcd.print("CO2 HISTORY", 10, 5, COLOR_TITLE)
    lcd.drawLine(40, 200, 300, 200, COLOR_GREY); lcd.drawLine(40, 200, 40, 50, COLOR_GREY) 
    lcd.font(lcd.FONT_Default); lcd.print("1000+", 5, 50, COLOR_GREY); lcd.print("400", 15, 195, COLOR_GREY)
    lcd.print("[C] HOME", 260, 220, 0x555555)

def draw_chart_lines(data_list):
    """Draws dynamic trend lines based on historical CO2 data"""
    lcd.fillRect(41, 50, 270, 149, COLOR_BG) 
    if len(data_list) < 2: return
    
    chart_h = 140
    chart_y_base = 195
    def scale_y(val):
        v = max(400, min(1200, val))
        return chart_y_base - int(((v - 400) / 800.0) * chart_h)

    for i in range(len(data_list) - 1):
        x1 = 45 + (i * 13)
        y1 = scale_y(data_list[i])
        x2 = 45 + ((i + 1) * 13)
        y2 = scale_y(data_list[i+1])
        lcd.drawLine(x1, y1, x2, y2, COLOR_OK)
        lcd.fillCircle(x2, y2, 2, COLOR_TITLE)

# ==========================================
# 7. Main Loop (With Online/Offline Segregation)
# ==========================================
force_setup = boot_manager()
connect_network(force_setup)

out_temp = "--"
sta = network.WLAN(network.STA_IF)
last_active_time = time.time()
last_sync_time = 0
SYNC_INTERVAL = 5 
is_asleep = False
current_page = 0
history_co2 = [400]

draw_dashboard_static()

while True:
    current_time = time.time()
    is_online = sta.isconnected() # Obtain current physical network status
    
    try: motion_detected = pir_sensor.state
    except: motion_detected = 0
    
    is_touched = touch.status()
    
    # --- 1. Wake-up Logic ---
    if motion_detected == 1 or is_touched or btnA.isPressed() or btnB.isPressed() or btnC.isPressed():
        last_active_time = current_time
        if is_asleep:
            set_screen_brightness(100)
            is_asleep = False
            
    # --- 2. On-Demand Wi-Fi Setup ---
    if btnB.wasPressed() and not is_asleep:
        lcd.clear(COLOR_BG); lcd.font(lcd.FONT_DejaVu18)
        lcd.print("Entering Setup Mode...", 60, 110, COLOR_TITLE)
        time.sleep(1); start_smart_config()

    # --- 3. Page Navigation ---
    if btnC.wasPressed() and not is_asleep:
        current_page = 1 if current_page == 0 else 0
        if current_page == 0:
            draw_dashboard_static()
        else:
            draw_chart_static()
            draw_chart_lines(history_co2)

    # --- 4. Auto-Sleep Logic ---
    if not is_asleep and (current_time - last_active_time > 15):
        set_screen_brightness(0)
        is_asleep = True

    # --- 5. Core Business Logic (5-second sync interval) ---
    if current_time - last_sync_time >= SYNC_INTERVAL:
        last_sync_time = current_time
        
        # 5.1 Read local sensors
        try:
            t, h, p = env_sensor.temperature, env_sensor.humidity, env_sensor.pressure
            v, c = air_sensor.read()
            if c < 400: c = 400 
        except:
            t, h, p, v, c = 0.0, 0.0, 0.0, 0, 400
            
        history_co2.append(c)
        if len(history_co2) > 20: history_co2.pop(0)

        # 5.2 Render UI
        if not is_asleep:
            # Toggle top-right status badge based on network connectivity
            lcd.fillRect(250, 5, 60, 20, COLOR_PANEL)
            lcd.font(lcd.FONT_DejaVu18)
            if is_online:
                lcd.print("LIVE", 260, 5, COLOR_OK)
            else:
                lcd.print("LOCAL", 250, 5, COLOR_GREY)
                out_temp = "--" # Clear outdoor weather in offline mode to prevent misleading stale data

            if current_page == 0:
                lcd.fillRect(50, 60, 110, 30, COLOR_BG)
                lcd.font(lcd.FONT_DejaVu24)
                lcd.print(str(c), 60, 65, COLOR_TEXT)
                
                badge_x, badge_w = 80, 130
                lcd.fillRect(badge_x, 115, badge_w, 24, COLOR_BG) 
                lcd.font(lcd.FONT_DejaVu18)
                if c < 800:
                    lcd.fillRect(badge_x, 115, badge_w, 24, COLOR_OK)
                    lcd.print("EXCELLENT", badge_x + 15, 118, COLOR_BG)
                elif c < 1200:
                    lcd.fillRect(badge_x, 115, badge_w, 24, COLOR_VAL_2)
                    lcd.print("MODERATE", badge_x + 18, 118, COLOR_BG)
                else:
                    lcd.fillRect(badge_x, 115, badge_w, 24, COLOR_ERR)
                    lcd.print("POOR AIR", badge_x + 18, 118, COLOR_TEXT)

                bar_w = int((h/100.0) * 188)
                lcd.fillRect(111, 154, 188, 8, COLOR_BG) 
                lcd.fillRect(111, 154, bar_w, 8, COLOR_VAL_1)

                lcd.font(lcd.FONT_DejaVu24)
                lcd.fillRect(10, 185, 90, 30, COLOR_BG)
                lcd.print(str(round(t, 1)) + "C", 20, 190, COLOR_TEXT)
                lcd.fillRect(116, 185, 90, 30, COLOR_BG)
                lcd.print(str(round(h, 0)) + "%", 130, 190, COLOR_VAL_1)
                lcd.fillRect(222, 185, 90, 30, COLOR_BG)
                lcd.print(str(out_temp) + "C", 235, 190, COLOR_TITLE)
            else:
                draw_chart_lines(history_co2)

        # 5.3 Cloud Sync Logic (Executes only in Online Mode)
        if is_online:
            try:
                payload = {"temperature": t, "humidity": h, "tvoc": v, "eco2": c, "motion_detected": motion_detected}
                res = urequests.post(API_URL, json=payload, headers={'Content-Type': 'application/json'})
                data = res.json()
                out_temp = data.get("outdoor_temp", "--")
                res.close()
                if not is_asleep: lcd.circle(310, 15, 4, COLOR_OK)
            except Exception as e:
                if not is_asleep: lcd.circle(310, 15, 4, COLOR_ERR)
        else:
            # In offline mode, the sync indicator dot turns grey
            if not is_asleep: lcd.circle(310, 15, 4, COLOR_PANEL)

    time.sleep(0.1)