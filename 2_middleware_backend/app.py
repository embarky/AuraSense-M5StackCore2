from flask import Flask, request, jsonify
import datetime

# Initialize the Flask application
app = Flask(__name__)

@app.route('/api/sensor_data', methods=['POST'])
def receive_data():
    """
    Endpoint to receive environmental data from the M5Stack edge device.
    Expected payload format: JSON
    """
    try:
        # Extract JSON payload from the incoming POST request
        payload = request.get_json()
        
        # Validate if payload exists
        if not payload:
            return jsonify({"status": "error", "message": "No JSON payload provided"}), 400

        # Retrieve current server timestamp for logging purposes
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Log the received data to the console (for debugging)
        print(f"[{timestamp}] 📥 Data received from M5Stack edge node:")
        print(f"🌡️  Temp: {payload.get('temperature')}°C | 💧 Hum: {payload.get('humidity')}% | 🎈 Pres: {payload.get('pressure')}hPa")
        print(f"💨 TVOC: {payload.get('tvoc')}ppb | 🚶‍♂️ Motion: {payload.get('motion_detected')}")
        print("-" * 50)
        
        # TODO: Integrate Google BigQuery connector here
        # bq_connector.insert_row(payload)
        
        # Return a success response to the edge device
        return jsonify({
            "status": "success", 
            "message": "Data received and queued for BigQuery insertion"
        }), 200

    except Exception as e:
        # Handle unexpected errors and return a 500 Internal Server Error
        print(f"Error processing incoming data: {str(e)}")
        return jsonify({"status": "error", "message": "Internal server error"}), 500

if __name__ == '__main__':
    # Run the server accessible on the local network (0.0.0.0) at port 5001
    app.run(host='0.0.0.0', port=5001, debug=True)