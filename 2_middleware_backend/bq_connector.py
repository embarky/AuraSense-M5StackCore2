import os
from google.cloud import bigquery
from google.oauth2 import service_account

# 1. Configuration - Using the project ID and table info you provided
PROJECT_ID = "caa-project-493719"
DATASET_ID = "iot_data"
TABLE_ID = "sensor_logs"
KEY_PATH = "caa-project-493719-0326a6be8e90.json"

class BigQueryConnector:
    def __init__(self):
        """Initializes the BigQuery client using the service account key."""
        try:
            # Load credentials from the JSON key file
            self.credentials = service_account.Credentials.from_service_account_file(KEY_PATH)
            self.client = bigquery.Client(credentials=self.credentials, project=PROJECT_ID)
            self.table_ref = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"
            print(f"Successfully connected to BigQuery: {self.table_ref}")
        except Exception as e:
            print(f"Failed to initialize BigQuery client: {e}")

    def insert_sensor_data(self, data_dict):
        """
        Inserts a single row of sensor data into BigQuery.
        data_dict should match the table schema.
        """
        # Add a server-side timestamp if not provided by the edge device
        import datetime
        if 'timestamp' not in data_dict:
            data_dict['timestamp'] = datetime.datetime.utcnow().isoformat()

        # Prepare the row for insertion
        rows_to_insert = [data_dict]

        # Stream the data into BigQuery
        errors = self.client.insert_rows_json(self.table_ref, rows_to_insert)

        if not errors:
            return True, "Data streamed successfully"
        else:
            return False, f"Errors occurred during insertion: {errors}"