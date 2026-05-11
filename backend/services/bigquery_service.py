# bq_connector.py

import os
from datetime import datetime, timezone
from google.cloud import bigquery
from google.oauth2 import service_account

# ==========================================
# 1. Configuration Constants
# ==========================================
PROJECT_ID = "caa-project-493719"
DATASET_ID = "iot_data"
TABLE_ID = "sensor_logs"
KEY_PATH = "caa-project-493719-0326a6be8e90.json"

class BigQueryConnector:
    def __init__(self):
        """Initializes the BigQuery client using the GCP service account key."""
        try:
            # Load credentials securely from the JSON key file
            self.credentials = service_account.Credentials.from_service_account_file(KEY_PATH)
            self.client = bigquery.Client(credentials=self.credentials, project=PROJECT_ID)
            self.table_ref = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"
            print(f"✅ [Data Layer] Successfully connected to BigQuery: {self.table_ref}")
        except Exception as e:
            print(f"❌ [Data Layer] Failed to initialize BigQuery client: {e}")

    def insert_sensor_data(self, data_dict):
        """
        Inserts a single row of formatted sensor data into BigQuery.
        Dynamically generates a strict UTC timestamp formatted for BigQuery.
        """
        # Inject standard timezone-aware UTC timestamp with microseconds 
        # (Resolves the 'datetime.utcnow() is deprecated' warning)
        if 'timestamp' not in data_dict:
            data_dict['timestamp'] = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')

        # Prepare the payload array for BigQuery streaming API
        rows_to_insert = [data_dict]

        try:
            # Use insert_rows_json for low-latency real-time streaming
            errors = self.client.insert_rows_json(self.table_ref, rows_to_insert)
            if not errors:
                return True, "Data streamed successfully"
            else:
                return False, f"Insert Errors: {errors}"
        except Exception as e:
            return False, f"Execution Error: {e}"