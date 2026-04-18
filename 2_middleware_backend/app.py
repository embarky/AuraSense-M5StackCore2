from flask import Flask, request, jsonify
import datetime
# Import the connector we just wrote
from bq_connector import BigQueryConnector

app = Flask(__name__)

# Initialize the BigQuery connector once when the server starts
bq_manager = BigQueryConnector()

@app.route('/api/sensor_data', methods=['POST'])
def receive_data():
    try:
        payload = request.get_json()
        if not payload:
            return jsonify({"status": "error", "message": "Missing JSON"}), 400

        # --- NEW: Streaming to BigQuery ---
        success, message = bq_manager.insert_sensor_data(payload)
        
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if success:
            print(f"[{timestamp}] ✅ Data persisted to BigQuery: {payload.get('temperature')}°C")
        else:
            print(f"[{timestamp}] ❌ BigQuery Error: {message}")

        return jsonify({"status": "success" if success else "error", "message": message}), 200

    except Exception as e:
        print(f"Server Error: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)