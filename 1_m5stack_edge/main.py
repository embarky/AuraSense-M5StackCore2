from m5stack import *
from m5ui import *
from uiflow import *
from machine import I2C, Pin
import unit
import time
import wifiCfg
import urequests
import json

# ==========================================
# 1. Constants and UI Configuration
# ==========================================
# Hex color codes to prevent UI library conflicts
COLOR_BG = 0x000000
COLOR_TITLE = 0xFFA500
COLOR_TEXT = 0xFFFFFF
COLOR_VAL_1 = 0x00FFFF  
COLOR_VAL_2 = 0xFFFF00  
COLOR_OK = 0x00FF00
COLOR_ERR = 0xFF0000

# Backend API Endpoint (TODO: Replace with your actual Flask/Cloud Run IP)
API_URL = "http://10.145.83.153:5001/api/sensor_data"

# Initialize LCD Screen
lcd.clear(COLOR_BG)
lcd.font(lcd.FONT_DejaVu18)
lcd.print("Smart Space Node", 70, 5, COLOR_TITLE)
lcd.drawLine(0, 30, 320, 30, COLOR_TEXT)

# ==========================================
# 2. Hardware Drivers
# ==========================================
class SGP30_Driver:
    """Manual I2C driver to bypass UIFlow's default SGP30 limitations."""
    def __init__(self, i2c_bus, address=0x58):
        self.i2c = i2c_bus
        self.addr = address
        try:
            # Send initialization command [0x20, 0x03]
            self.i2c.writeto(self.addr, b'\x20\x03')
            time.sleep_ms(10)
        except:
            pass
            
    def read(self):
        """Request and parse TVOC and eCO2 measurements."""
        self.i2c.writeto(self.addr, b'\x20\x08')
        time.sleep_ms(20)
        data = self.i2c.readfrom(self.addr, 6)
        eco2 = (data[0] << 8) | data[1]
        tvoc = (data[3] << 8) | data[4]
        return tvoc, eco2

# Hardware Initialization (Assuming sensors are distributed across Ports A, B, C)
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

# Connect to WiFi (Uses credentials stored in device settings)
# wifiCfg.doConnect('YOUR_SSID', 'YOUR_PASSWORD')

# ==========================================
# 3. Main Operational Loop
# ==========================================
def clear_line(y, height=22):
    """Utility function to prevent text overlapping on the LCD."""
    lcd.fillRect(10, y, 300, height, COLOR_BG)

while True:
    # --- Data Acquisition ---
    try:
        t = env_sensor.temperature
        h = env_sensor.humidity
        p = env_sensor.pressure
        v, c = air_sensor.read()
        motion = pir_sensor.state
    except Exception as e:
        # Fallback values if hardware read fails
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
    if wifiCfg.wlan_sta.isconnected():
        try:
            # Construct JSON payload
            payload = {
                "temperature": round(t, 2),
                "humidity": round(h, 2),
                "pressure": round(p, 2),
                "tvoc": v,
                "eco2": c,
                "motion_detected": motion
            }
            
            headers = {'Content-Type': 'application/json'}
            
            # Execute HTTP POST request
            res = urequests.post(API_URL, json=payload, headers=headers)
            
            # Visual indicator for successful transmission
            lcd.circle(310, 10, 5, COLOR_OK) 
            res.close() # CRITICAL: Prevent memory leaks
            
        except Exception as e:
            # Visual indicator for network failure
            lcd.circle(310, 10, 5, COLOR_ERR)
            print("HTTP POST Failed:", e)
    
    # Wait 5 seconds before the next cycle to prevent flooding the server
    time.sleep(5)