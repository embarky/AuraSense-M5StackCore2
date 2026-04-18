import streamlit as st
import pandas as pd
from data_fetcher import get_sensor_data

# 1. Page Configuration (Must be the first Streamlit command)
st.set_page_config(page_title="Smart Space Dashboard", page_icon="🌍", layout="wide")

# 2. UI Header
st.title("🌍 Smart Space Real-time Monitoring")
st.markdown("This dashboard pulls live IoT data from **Google BigQuery**.")

# 3. Fetch Data
# st.cache_data ensures we don't query the database on every minor UI interaction
@st.cache_data(ttl=5) # Cache expires every 5 seconds for near real-time updates
def load_data():
    return get_sensor_data(limit=100)

df = load_data()

# 4. Render UI Components
if df.empty:
    st.error("No data found or BigQuery connection failed. Please check your backend.")
else:
    # Get the absolute latest reading (row 0 since we ordered by DESC in SQL)
    latest_data = df.iloc[0]
    last_update = latest_data['timestamp'].strftime("%Y-%m-%d %H:%M:%S")
    st.caption(f"Last updated: {last_update}")

    # --- Section: KPI Metrics ---
    st.subheader("Current Environment Status")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Temperature", f"{latest_data['temperature']:.1f} °C")
    with col2:
        st.metric("Humidity", f"{latest_data['humidity']:.1f} %")
    with col3:
        st.metric("Air Quality (TVOC)", f"{latest_data['tvoc']} ppb")
    with col4:
        motion_status = "🚨 Detected!" if latest_data['motion_detected'] == 1 else "✅ Clear"
        st.metric("Motion Sensor", motion_status)

    st.divider()

    # --- Section: Time Series Charts ---
    st.subheader("Historical Trends (Last 100 records)")
    
    # Process dataframe for charting: set timestamp as the index
    chart_df = df.set_index('timestamp')
    
    # Create two columns for charts
    chart_col1, chart_col2 = st.columns(2)
    
    with chart_col1:
        st.markdown("**Temperature & Humidity**")
        st.line_chart(chart_df[['temperature', 'humidity']])
        
    with chart_col2:
        st.markdown("**Air Quality (eCO2 & TVOC)**")
        st.line_chart(chart_df[['eco2', 'tvoc']])

    # --- Section: Raw Data Explorer ---
    with st.expander("View Raw Database Logs"):
        st.dataframe(df, use_container_width=True)