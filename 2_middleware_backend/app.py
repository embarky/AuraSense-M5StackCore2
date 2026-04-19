from flask import Flask, request, jsonify
import requests
import time
import json
import os

app = Flask(__name__)

# ==========================================
# 1. Dynamic Configuration Loading
# ==========================================
CONFIG_FILE = "caa_weather.json"

try:
    with open(CONFIG_FILE, 'r') as f:
        config = json.load(f)
        OPENWEATHER_API_KEY = config.get("api_key")
        # Fallback city: Default to Lausanne if IP detection fails
        FALLBACK_CITY = config.get("city", "Lausanne,CH") 
    print("✅ Configuration loaded successfully: caa_weather.json")
except FileNotFoundError:
    print(f"❌ CRITICAL ERROR: Configuration file {CONFIG_FILE} not found! Check path.")
    exit(1)

# ==========================================
# 2. IP Geolocation System & Cache
# ==========================================
cached_location = {
    "lat": None,
    "lon": None,
    "city": "Unknown",
    "last_update": 0
}
LOC_CACHE_DURATION = 3600 # Location cache duration: 1 hour

def update_location_by_ip():
    """Automatically fetch current latitude and longitude using public IP."""
    current_time = time.time()
    
    # Return immediately if cache is still valid
    if current_time - cached_location["last_update"] < LOC_CACHE_DURATION and cached_location["lat"] is not None:
        return True

    print("🌍 [Location API] Auto-detecting location via IP...")
    try:
        # Fetch geolocation data using the free ip-api service
        res = requests.get("http://ip-api.com/json/", timeout=5)
        if res.status_code == 200:
            data = res.json()
            if data["status"] == "success":
                cached_location["lat"] = data["lat"]
                cached_location["lon"] = data["lon"]
                cached_location["city"] = f"{data['city']}, {data['countryCode']}"
                cached_location["last_update"] = current_time
                print(f"📍 Location locked: {cached_location['city']} (Lat: {cached_location['lat']}, Lon: {cached_location['lon']})")
                return True
    except Exception as e:
        print(f"⚠️ [Location API] IP detection failed: {e}")

    # Fallback to the configured city if network/API fails
    if cached_location["lat"] is None:
        cached_location["city"] = FALLBACK_CITY
        print(f"⚠️ Using fallback location: {FALLBACK_CITY}")
    
    return False

# ==========================================
# 3. Weather Data Cache System
# ==========================================
cached_weather = {
    "temp_out": None,
    "hum_out": None,
    "pressure_out": None,
    "description": None,
    "last_update": 0
}
WEATHER_CACHE_DURATION = 600 # Weather cache duration: 10 minutes

def get_outdoor_weather():
    """Fetch outdoor weather with lat/lon precision and cache protection."""
    current_time = time.time()
    
    # Cache hit: Avoid redundant network requests
    if current_time - cached_weather["last_update"] < WEATHER_CACHE_DURATION and cached_weather["temp_out"] is not None:
        return cached_weather

    # Ensure we have the latest geographic location
    update_location_by_ip()

    # Dynamically build request URL (Prioritize highly accurate lat/lon)
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
        else:
            print(f"⚠️ [Weather API] Error {response.status_code}: {response.text}")
    except Exception as e:
        print(f"⚠️ [Weather API] Network request failed: {e}")

    return cached_weather

# ==========================================
# 4. Global State (For Frontend Dashboard)
# ==========================================
latest_sensor_data = {}

# ==========================================
# API 1: IoT Device Data Ingestion (POST)
# ==========================================
@app.route('/api/sensor_data', methods=['POST'])
def receive_data():
    """Endpoint for M5Stack to upload indoor data and receive outdoor weather."""
    global latest_sensor_data
    indoor_data = request.json
    
    if not indoor_data:
        return jsonify({"error": "No JSON payload"}), 400

    # Retrieve current outdoor weather (leveraging cache)
    outdoor_data = get_outdoor_weather()

    # Update global state for the frontend dashboard
    latest_sensor_data = {
        "timestamp": time.time(),
        "location": cached_location["city"],
        
        # Indoor Sensor Data
        "indoor_temp": indoor_data.get("temperature"),
        "indoor_hum": indoor_data.get("humidity"),
        "indoor_pressure": indoor_data.get("pressure"),
        "indoor_tvoc": indoor_data.get("tvoc"),
        "indoor_eco2": indoor_data.get("eco2"),
        "motion_detected": indoor_data.get("motion_detected"),
        
        # Outdoor Meteorological Data
        "outdoor_temp": outdoor_data.get("temp_out"),
        "outdoor_hum": outdoor_data.get("hum_out"),
        "outdoor_pressure": outdoor_data.get("pressure_out"),
        "outdoor_desc": outdoor_data.get("description")
    }

    print(f"📦 Data Synced -> In: {latest_sensor_data['indoor_temp']}°C | Out: {latest_sensor_data['outdoor_temp']}°C")

    # TODO: Next Milestone -> Write latest_sensor_data to Google BigQuery

    # Return weather data to the IoT device for screen display
    return jsonify({
        "status": "success",
        "outdoor_temp": latest_sensor_data["outdoor_temp"],
        "outdoor_desc": latest_sensor_data["outdoor_desc"]
    }), 200

# ==========================================
# API 2: Frontend Dashboard Data Fetch (GET)
# ==========================================
@app.route('/api/current_status', methods=['GET'])
def get_status():
    """Endpoint for Frontend React/Vue to fetch real-time merged data."""
    if not latest_sensor_data:
        return jsonify({"message": "Waiting for IoT device data..."}), 202
    
    # Add CORS headers to allow cross-origin requests from frontend frameworks
    response = jsonify(latest_sensor_data)
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response, 200

if __name__ == '__main__':
    print("🚀 Smart Space Backend is running...")
    # Proactively fetch location on startup for a better UX
    with app.app_context():
        update_location_by_ip()
    # Listen on all network interfaces to allow M5Stack connection
    app.run(host='0.0.0.0', port=5001, debug=True)