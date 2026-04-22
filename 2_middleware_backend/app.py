# app.py

from flask import Flask, request, jsonify
import requests
import time
import json
import os
from datetime import datetime, timezone
import threading  # Added for asynchronous AI processing

# Import our custom Data and AI layers
from bq_connector import BigQueryConnector
from ai_services import SmartSpaceAI

app = Flask(__name__)

# ==========================================
# 0. Core Services Initialization
# ==========================================
# Instantiate the database connector
bq_db = BigQueryConnector()

# Instantiate the AI Brain
space_ai = SmartSpaceAI()

# ==========================================
# 1. Dynamic Configuration Loading
# ==========================================
CONFIG_FILE = "caa_weather.json"

try:
    with open(CONFIG_FILE, 'r') as f:
        config = json.load(f)
        OPENWEATHER_API_KEY = config.get("api_key")
        FALLBACK_CITY = config.get("city", "Lausanne,CH") 
    print("✅ [API Layer] Weather configuration loaded successfully.")
except FileNotFoundError:
    print(f"❌ [API Layer] CRITICAL ERROR: {CONFIG_FILE} not found!")
    exit(1)

# ==========================================
# 2. IP Geolocation & Weather Cache System
# ==========================================
cached_location = {
    "lat": None, 
    "lon": None, 
    "city": "Unknown", 
    "offset": 7200, 
    "timezone": "Europe/Zurich",
    "last_update": 0
}
LOC_CACHE_DURATION = 3600 # Cache location for 1 hour

def update_location_by_ip():
    """Automatically detects location, UTC offset, and timezone string via external IP."""
    current_time = time.time()
    
    # Return immediately if cache is still valid to save API calls
    if current_time - cached_location["last_update"] < LOC_CACHE_DURATION and cached_location["lat"] is not None:
        return True
        
    print("🌍 [Location API] Auto-detecting roaming profile via external IP...")
    try:
        url = "http://ip-api.com/json/?fields=status,lat,lon,city,countryCode,offset,timezone"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if data.get("status") == "success":
                cached_location["lat"] = data["lat"]
                cached_location["lon"] = data["lon"]
                cached_location["city"] = f"{data['city']}, {data['countryCode']}"
                cached_location["offset"] = data.get("offset", 7200) 
                cached_location["timezone"] = data.get("timezone", "Europe/Zurich")
                cached_location["last_update"] = current_time
                return True
    except Exception as e:
        print(f"⚠️ [Location API] IP detection failed: {e}")

    # Fallback to default city if network detection fails
    if cached_location["lat"] is None: 
        cached_location["city"] = FALLBACK_CITY
    return False

cached_weather = {
    "temp_out": None, 
    "description": None, 
    "last_update": 0
}
WEATHER_CACHE_DURATION = 600 # Cache weather for 10 minutes

def get_outdoor_weather():
    """Fetch real-time weather from OpenWeather based on dynamic location."""
    current_time = time.time()
    if current_time - cached_weather["last_update"] < WEATHER_CACHE_DURATION and cached_weather["temp_out"] is not None:
        return cached_weather
        
    update_location_by_ip()
    
    # Prefer exact latitude/longitude for hyper-local weather accuracy
    if cached_location["lat"] is not None:
        url = f"http://api.openweathermap.org/data/2.5/weather?lat={cached_location['lat']}&lon={cached_location['lon']}&appid={OPENWEATHER_API_KEY}&units=metric"
    else:
        url = f"http://api.openweathermap.org/data/2.5/weather?q={cached_location['city']}&appid={OPENWEATHER_API_KEY}&units=metric"
        
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            cached_weather["temp_out"] = data["main"]["temp"]
            cached_weather["description"] = data["weather"][0]["description"]
            cached_weather["last_update"] = current_time
    except Exception as e:
        print(f"⚠️ [Weather API] Weather fetch failed: {e}")
        
    return cached_weather

# ==========================================
# 3. Global State & AI Cooldown Logic
# ==========================================
# Global state to serve the Streamlit Frontend in real-time
latest_sensor_data = {
    "ai_advice": "Waiting for initial AI analysis..." # Placeholder for the dashboard
}

# AI Cooldown variables to prevent API quota exhaustion
last_ai_update_time = 0
AI_COOLDOWN_SECONDS = 600  # Allow LLM inference only once every 10 minutes

def background_ai_task(indoor_temp, indoor_hum, eco2, tvoc, outdoor_temp, outdoor_desc):
    """
    Runs the AI inference in a separate background thread.
    This guarantees zero latency for the IoT hardware's POST request.
    """
    global latest_sensor_data
    print("🧠 [AI Layer] AI is analyzing the environment in the background...")
    
    advice = space_ai.generate_health_advice(
        indoor_temp=indoor_temp,
        indoor_hum=indoor_hum,
        eco2=eco2,
        tvoc=tvoc,
        outdoor_temp=outdoor_temp,
        outdoor_desc=outdoor_desc
    )
    
    # Update the global state with the newly generated AI insight
    latest_sensor_data["ai_advice"] = advice
    print(f"🤖 [AI Layer] Insight updated: {advice}")

# ==========================================
# 4. API: Receive IoT Data & Global Sync
# ==========================================
@app.route('/api/sensor_data', methods=['POST'])
def receive_data():
    """Main ingestion endpoint for M5Stack. Handles logging, AI triggers, and time-sync."""
    global latest_sensor_data, last_ai_update_time
    indoor_data = request.json
    
    if not indoor_data:
        return jsonify({"error": "No JSON payload"}), 400

    outdoor_data = get_outdoor_weather()
    current_timestamp = time.time()

    # Preserve existing AI advice to prevent overwriting it with "None"
    current_advice = latest_sensor_data.get("ai_advice", "Analyzing environment...")

    # 1. Update Global Memory (State)
    latest_sensor_data = {
        "timestamp": current_timestamp,
        "location": cached_location["city"],
        "indoor_temp": indoor_data.get("temperature"),
        "indoor_hum": indoor_data.get("humidity"),
        "indoor_pressure": indoor_data.get("pressure"),
        "indoor_tvoc": indoor_data.get("tvoc"),
        "indoor_eco2": indoor_data.get("eco2"),
        "motion_detected": indoor_data.get("motion_detected"),
        "outdoor_temp": outdoor_data.get("temp_out"),
        "outdoor_desc": outdoor_data.get("description"),
        "timezone": cached_location["timezone"],
        "ai_advice": current_advice # Carry over the AI insight
    }

    # 2. Trigger AI inference (Protected by Cooldown Timer)
    if current_timestamp - last_ai_update_time >= AI_COOLDOWN_SECONDS:
        last_ai_update_time = current_timestamp # Lock the cooldown immediately
        
        # Spawn a non-blocking background thread for the Gemini API call
        ai_thread = threading.Thread(
            target=background_ai_task, 
            args=(
                indoor_data.get("temperature"),
                indoor_data.get("humidity"),
                indoor_data.get("eco2"),
                indoor_data.get("tvoc"),
                outdoor_data.get("temp_out"),
                outdoor_data.get("description")
            )
        )
        ai_thread.start()

    # 3. Store in BigQuery for long-term Analytics
    bq_payload = {
        "temperature": indoor_data.get("temperature"),
        "humidity": indoor_data.get("humidity"),
        "pressure": indoor_data.get("pressure"), 
        "tvoc": indoor_data.get("tvoc"),
        "eco2": indoor_data.get("eco2"),
        "motion_detected": indoor_data.get("motion_detected"),
        "timezone": cached_location["timezone"] 
    }

    success, message = bq_db.insert_sensor_data(bq_payload)
    if success:
        print(f"📦 [BigQuery] Logged | Temp: {bq_payload['temperature']}°C | TZ: {bq_payload['timezone']}")
    else:
        print(f"❌ [BigQuery] Failed: {message}")

    # 4. Calculate dynamic local time for hardware clock synchronization
    local_epoch = current_timestamp + cached_location["offset"]
    g = time.gmtime(local_epoch)
    
    # Required format for ESP32 Time library: [YYYY, MM, DD, Weekday, HH, MM, SS, Sub-sec]
    local_time_list = [g.tm_year, g.tm_mon, g.tm_mday, 0, g.tm_hour, g.tm_min, g.tm_sec, 0]

    # Return response in milliseconds
    return jsonify({
        "status": "success",
        "outdoor_temp": latest_sensor_data["outdoor_temp"],
        "outdoor_desc": latest_sensor_data["outdoor_desc"],
        "utc_time": local_time_list,
        "ai_advice": latest_sensor_data.get("ai_advice")
    }), 200

# ==========================================
# 5. API: Status Endpoint for Streamlit
# ==========================================
@app.route('/api/current_status', methods=['GET'])
def get_status():
    """Real-time data bridge for the Streamlit dashboard."""
    if not latest_sensor_data.get("timestamp"):
        return jsonify({"message": "Device offline or waiting for telemetry..."}), 202
    
    response = jsonify(latest_sensor_data)
    # Enable CORS to allow the frontend to fetch data without browser security blocks
    response.headers.add('Access-Control-Allow-Origin', '*') 
    return response, 200

if __name__ == '__main__':
    print(f"🚀 [API Layer] Smart Space Hub starting up...")
    print(f"🌐 Server active on http://0.0.0.0:5001")
    
    # Pre-fetch IP location on server startup to eliminate latency on the first device ping
    with app.app_context():
        update_location_by_ip()
        
    app.run(host='0.0.0.0', port=5001, debug=True)