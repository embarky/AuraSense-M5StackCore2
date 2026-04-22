# app.py

from flask import Flask, request, jsonify
import requests
import time
import json
import os

# Import our custom database handler
from bq_connector import BigQueryConnector

app = Flask(__name__)

# ==========================================
# 0. Database Initialization
# ==========================================
# Instantiate the database connector once on startup
bq_db = BigQueryConnector()

# ==========================================
# 1. Dynamic Configuration Loading
# ==========================================
CONFIG_FILE = "caa_weather.json"

try:
    with open(CONFIG_FILE, 'r') as f:
        config = json.load(f)
        OPENWEATHER_API_KEY = config.get("api_key")
        FALLBACK_CITY = config.get("city", "Lausanne,CH") 
    print("✅ [API Layer] Configuration loaded successfully.")
except FileNotFoundError:
    print(f"❌ [API Layer] CRITICAL ERROR: Configuration file {CONFIG_FILE} not found!")
    exit(1)

# ==========================================
# 2. IP Geolocation & Weather Cache System
# ==========================================
cached_location = {
    "lat": None, 
    "lon": None, 
    "city": "Unknown", 
    "offset": 7200, 
    "last_update": 0
}
LOC_CACHE_DURATION = 3600 # 1 Hour

def update_location_by_ip():
    """Automatically fetch coordinates and timezone offset via public IP."""
    current_time = time.time()
    if current_time - cached_location["last_update"] < LOC_CACHE_DURATION and cached_location["lat"] is not None:
        return True
        
    print("🌍 [Location API] Auto-detecting location & timezone via IP...")
    try:
        url = "http://ip-api.com/json/?fields=status,lat,lon,city,countryCode,offset"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if data.get("status") == "success":
                cached_location["lat"] = data["lat"]
                cached_location["lon"] = data["lon"]
                cached_location["city"] = f"{data['city']}, {data['countryCode']}"
                cached_location["offset"] = data.get("offset", 7200) 
                cached_location["last_update"] = current_time
                return True
    except Exception as e:
        print(f"⚠️ [Location API] IP detection failed: {e}")

    if cached_location["lat"] is None: 
        cached_location["city"] = FALLBACK_CITY
    return False

cached_weather = {
    "temp_out": None, 
    "hum_out": None, 
    "pressure_out": None, 
    "description": None, 
    "last_update": 0
}
WEATHER_CACHE_DURATION = 600 # 10 Minutes

def get_outdoor_weather():
    """Fetch accurate outdoor weather based on detected lat/lon."""
    current_time = time.time()
    if current_time - cached_weather["last_update"] < WEATHER_CACHE_DURATION and cached_weather["temp_out"] is not None:
        return cached_weather
        
    update_location_by_ip()
    
    if cached_location["lat"] is not None:
        url = f"http://api.openweathermap.org/data/2.5/weather?lat={cached_location['lat']}&lon={cached_location['lon']}&appid={OPENWEATHER_API_KEY}&units=metric"
    else:
        url = f"http://api.openweathermap.org/data/2.5/weather?q={cached_location['city']}&appid={OPENWEATHER_API_KEY}&units=metric"
        
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            cached_weather["temp_out"] = data["main"]["temp"]
            cached_weather["hum_out"] = data["main"]["humidity"]
            cached_weather["pressure_out"] = data["main"]["pressure"]
            cached_weather["description"] = data["weather"][0]["description"]
            cached_weather["last_update"] = current_time
    except Exception as e:
        print(f"⚠️ [Weather API] Network request failed: {e}")
        
    return cached_weather

# Global state to serve the Streamlit Frontend
latest_sensor_data = {}

# ==========================================
# 3. API: Receive IoT Data & Insert to BigQuery
# ==========================================
@app.route('/api/sensor_data', methods=['POST'])
def receive_data():
    """Ingest hardware data, enrich with weather, and write to BigQuery."""
    global latest_sensor_data
    indoor_data = request.json
    
    if not indoor_data:
        return jsonify({"error": "No JSON payload provided"}), 400

    outdoor_data = get_outdoor_weather()
    current_timestamp = time.time()

    # 1. Update Global State for Streamlit Dashboard
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
        "outdoor_desc": outdoor_data.get("description")
    }

    # 2. Package data for BigQuery mapping
    bq_payload = {
        "temperature": indoor_data.get("temperature"),
        "humidity": indoor_data.get("humidity"),
        "pressure": indoor_data.get("pressure"), 
        "tvoc": indoor_data.get("tvoc"),
        "eco2": indoor_data.get("eco2"),
        "motion_detected": indoor_data.get("motion_detected")
    }

    # 3. Delegate database insertion to our BigQueryConnector class
    success, message = bq_db.insert_sensor_data(bq_payload)
    if success:
        print(f"📦 [BigQuery] Logged! Temp: {bq_payload['temperature']}°C | CO2: {bq_payload['eco2']} ppm")
    else:
        print(f"❌ [BigQuery] {message}")

    # 4. Calculate exact local time for M5Stack synchronization
    local_epoch = current_timestamp + cached_location["offset"]
    g = time.gmtime(local_epoch)
    
    utc_time_list = [g.tm_year, g.tm_mon, g.tm_mday, 0, g.tm_hour, g.tm_min, g.tm_sec, 0]

    # Respond to M5Stack
    return jsonify({
        "status": "success",
        "outdoor_temp": latest_sensor_data["outdoor_temp"],
        "outdoor_desc": latest_sensor_data["outdoor_desc"],
        "utc_time": utc_time_list 
    }), 200

# ==========================================
# 4. API: Fetch Latest Status for Streamlit
# ==========================================
@app.route('/api/current_status', methods=['GET'])
def get_status():
    """Endpoint for Frontend dashboards (Streamlit/React) to poll current data."""
    if not latest_sensor_data:
        return jsonify({"message": "Waiting for IoT device data..."}), 202
    
    response = jsonify(latest_sensor_data)
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response, 200

if __name__ == '__main__':
    print(f"🚀 Smart Space Backend starting up...")
    
    with app.app_context():
        update_location_by_ip()
        
    app.run(host='0.0.0.0', port=5001, debug=True)