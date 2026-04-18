import os
import pandas as pd
from google.cloud import bigquery
from google.oauth2 import service_account

# Configuration
PROJECT_ID = "caa-project-493719"
DATASET_ID = "iot_data"
TABLE_ID = "sensor_logs"
KEY_PATH = "caa-project-493719-0326a6be8e90.json"

def get_sensor_data(limit=100):
    """
    Fetches the latest sensor readings from Google BigQuery and returns a Pandas DataFrame.
    """
    try:
        # Authenticate using the service account key
        credentials = service_account.Credentials.from_service_account_file(KEY_PATH)
        client = bigquery.Client(credentials=credentials, project=PROJECT_ID)
        
        # SQL Query: Fetch the most recent rows, sorted by time
        query = f"""
            SELECT 
                timestamp, temperature, humidity, pressure, tvoc, eco2, motion_detected
            FROM 
                `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}`
            ORDER BY 
                timestamp DESC
            LIMIT {limit}
        """
        
        # Execute query and convert directly to a Pandas DataFrame
        df = client.query(query).to_dataframe()
        
        # Ensure timestamp is treated as a datetime object for proper plotting
        if not df.empty:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            
        return df

    except Exception as e:
        print(f"Database connection error: {e}")
        return pd.DataFrame() # Return an empty dataframe on failure