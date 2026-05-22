"""
dashboard/app.py — Smart Space Streamlit dashboard (Final Production Version).
"""
import time
import datetime
import requests
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from data import (
    FLASK_URL, get_current_status, get_last_known_context, get_history, 
    get_daily_aggregates, get_motion_heatmap, get_anomalies, get_anomalies_by_dates, THRESH
)
from charts import (
    temp_humidity_chart, co2_tvoc_chart, daily_temp_chart, motion_heatmap_chart
)

# ── API Helpers for Weather & Location ────────────────────────────────────────

@st.cache_data(ttl=3600)
def fetch_ip_location():
    """根据访客 IP 地址获取当前的城市和国家"""
    try:
        r = requests.get("http://ip-api.com/json/", timeout=3)
        if r.status_code == 200:
            data = r.json()
            city = data.get("city", "Unknown City")
            countryCode = data.get("countryCode", "CH")
            return f"{city}, {countryCode}"
    except Exception:
        pass
    return "Lausanne, CH" 

@st.cache_data(ttl=900)
def fetch_flask_forecast():
    """调用后端的 Forecast API 获取气象数据"""
    try:
        r = requests.get(f"{FLASK_URL}/api/forecast", timeout=3)
        if r.status_code == 200:
            res = r.json()
            if res.get("status") == "success":
                return res.get("forecast", [])
    except Exception as e:
        print(f"[app] Error fetching forecast: {e}")
    return []

# ── Page Configuration ────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Smart Space",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ── Enhanced UI / Modern CSS Typography ───────────────────────────────────────

st.markdown("""
<style>
  .block-container { padding-top: 2rem; padding-bottom: 2rem; max-width: 1400px; }
  .section-label { font-size: 13px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #6c757d; margin-top: 1.5rem; margin-bottom: 1rem; border-bottom: 1px solid #eee; padding-bottom: 0.5rem; }
  .anomaly-danger { background: #fff0f0; border-left: 4px solid #ff4b4b; padding: 8px 12px; margin-bottom: 8px; border-radius: 4px; color: #a32d2d; font-size: 13px; }
  .anomaly-warning { background: #fff8e6; border-left: 4px solid #ffc107; padding: 8px 12px; margin-bottom: 8px; border-radius: 4px; color: #854f0b; font-size: 13px; }
  [data-testid="stMetricValue"] { font-size: 2.2rem !important; font-weight: 700 !important; color: #1f2937; }
</style>
""", unsafe_allow_html=True)

# ── Sparkline Helper Function ─────────────────────────────────────────────────

def sparkline(series, color="#378ADD"):
    if series is None or len(series) == 0: return
    
    if color.startswith("#") and len(color) == 7:
        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
        fill_color = f"rgba({r}, {g}, {b}, 0.15)"
    elif "rgb" in color:
        fill_color = color.replace("rgb", "rgba").replace(")", ", 0.15)")
    else:
        fill_color = "rgba(55, 138, 221, 0.15)"
        
    fig = go.Figure(go.Scatter(
        y=series, mode="lines", 
        line=dict(color=color, width=2, shape="spline", smoothing=1), 
        fill="tozeroy", fillcolor=fill_color
    ))
    fig.update_layout(
        height=40, margin=dict(l=0, r=0, t=5, b=0), 
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", 
        xaxis=dict(visible=False), yaxis=dict(visible=False), 
        showlegend=False, hovermode=False
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# ── 1. Top Section (Real-time Auto-Refreshing Fragment) ───────────────────────

@st.fragment(run_every=30)
def render_live_dashboard():
    live_status = get_current_status()
    is_online = bool(live_status.get("timestamp"))

    if is_online:
        display_location = live_status.get("location", "Unknown Location")
        last_seen_ts = live_status.get("timestamp")
        current_metrics = live_status 
    else:
        db_context = get_last_known_context()
        display_location = db_context.get("location", "Unknown Location")
        last_seen_ts = db_context.get("timestamp", time.time())
        current_metrics = {} 

    if not is_online:
        last_seen_str = pd.to_datetime(last_seen_ts, unit='s').tz_localize('UTC').tz_convert('Europe/Zurich').strftime('%Y-%m-%d %H:%M') if db_context else "No historical records"
        st.warning(f"**⚠️ Sensor Offline.** Real-time metrics are unavailable. Displaying historical data up to: {last_seen_str}.")

    col_title, col_ctrl = st.columns([3, 1])
    with col_title:
        st.title("Smart Space Dashboard")
        st.caption(f"📍 Indoor Environment Monitor · {display_location}")

    with col_ctrl:
        dot = "🟢 Live" if is_online else "🔴 Offline"
        st.markdown(f"<div style='text-align: right; margin-top: 10px; font-weight: 600; color: {'#10B981' if is_online else '#EF4444'}; font-size: 18px;'>{dot}</div>", unsafe_allow_html=True)

    st.markdown('<div class="section-label">Real-time Overview</div>', unsafe_allow_html=True)

    df_sparklines = get_history(24)

    temp  = current_metrics.get("indoor_temp")
    hum   = current_metrics.get("indoor_hum")
    eco2  = current_metrics.get("eco2")
    tvoc  = current_metrics.get("tvoc")
    press = current_metrics.get("pressure")
    motion = current_metrics.get("motion")

    r1c1, r1c2, r1c3 = st.columns(3)
    with r1c1:
        st.metric("🌡 Temperature", f"{round(temp,1)} °C" if temp is not None else "—")
        if not df_sparklines.empty and "temperature" in df_sparklines: 
            sparkline(df_sparklines["temperature"].dropna().tail(60), "#EF4444")
        st.caption(current_metrics.get("comfort_level", "Sensor offline") if not is_online else current_metrics.get("comfort_level", "Normal comfort"))

    with r1c2:
        st.metric("💧 Humidity", f"{round(hum,0):.0f} %" if hum is not None else "—")
        if not df_sparklines.empty and "humidity" in df_sparklines: 
            sparkline(df_sparklines["humidity"].dropna().tail(60), "#10B981")
        if not is_online: st.caption("Sensor offline")
        elif hum is not None: st.caption("🟡 Needs Attention" if hum < THRESH["hum_low_warn"] or hum > THRESH["hum_high_warn"] else "🟢 Optimal level")

    with r1c3:
        st.metric("💨 eCO2 Level", f"{int(eco2)} ppm" if eco2 is not None else "—")
        if not df_sparklines.empty and "eco2" in df_sparklines: 
            sparkline(df_sparklines["eco2"].dropna().tail(60), "#F59E0B")
        if not is_online: st.caption("Sensor offline")
        elif eco2 is not None: st.caption("🟡 Ventilation recommended" if eco2 > THRESH["eco2_warning"] else "🟢 Good air quality")

    st.write("")

    r2c1, r2c2, r2c3 = st.columns(3)
    with r2c1:
        st.metric("⚗️ TVOC", f"{int(tvoc)} ppb" if tvoc is not None else "—")
        if not is_online: st.caption("Sensor offline")
        elif tvoc is not None: st.caption("🔴 Danger" if tvoc > THRESH["tvoc_danger"] else ("🟡 Moderate" if tvoc > THRESH["tvoc_warning"] else "🟢 Good"))

    with r2c2:
        st.metric("📊 Air Pressure", f"{int(press)} hPa" if press is not None else "—")
        if not is_online: st.caption("Sensor offline")
        elif press is not None: st.caption("🟢 Stable" if 980 < press < 1040 else "🟡 Unusual")

    with r2c3:
        motion = (current_metrics.get("motion") if is_online else None)
        st.metric("🚶 Motion Status", "Detected" if motion else ("Clear" if is_online else "—"))
        st.caption("Sensor offline" if not is_online else ("Active" if motion else "No movement in area"))
        
    return current_metrics, is_online

current_metrics, is_online = render_live_dashboard()


# ── 2. Context & Multi-Filter Anomalies Panel ─────────────────────────────────

df_daily  = get_daily_aggregates(7)
col_out, col_anom = st.columns([1, 2], gap="large")

with col_out:
    st.markdown('<div class="section-label">Outdoor Context</div>', unsafe_allow_html=True)
    
    location_str = fetch_ip_location()
    forecast_data = fetch_flask_forecast()
    today_fc = df_daily.iloc[-1] if not df_daily.empty else None

    if forecast_data and len(forecast_data) > 0:
        today_w = forecast_data[0]
        out_t = current_metrics.get("outdoor_temp")
        if out_t is None:
            out_t = today_w.get("feels_like")
        
        out_desc = str(today_w.get("description", "")).title()
        feels_like = today_w.get("feels_like", "—")
        out_hum = today_w.get("humidity", "—")
        out_wind = today_w.get("wind", "—") 
        t_min = today_w.get("temp_min", "—")
        t_max = today_w.get("temp_max", "—")
    else:
        out_t = current_metrics.get("outdoor_temp")
        out_desc = (current_metrics.get("outdoor_desc") or "").title()
        feels_like = current_metrics.get("outdoor_feels_like", "—")
        out_hum = current_metrics.get("outdoor_humidity", "—")
        out_wind = current_metrics.get("outdoor_wind_speed", "—")
        t_min = today_fc.get("temp_min", "—") if today_fc is not None else "—"
        t_max = today_fc.get("temp_max", "—") if today_fc is not None else "—"

    if out_t is not None:
        st.caption(f"📍 {location_str} • Updated just now")
        
        w_col1, w_col2 = st.columns([1.2, 1])
        with w_col1:
            # 完美对齐的主温度：大数字 + 小单位 (Baseline Aligned)
            st.markdown(
                f"""
                <div style="display: flex; align-items: baseline; margin-top: 5px;">
                    <span style="font-size: 4.2rem; font-weight: 800; color: #111827; line-height: 1;">{round(float(out_t))}</span>
                    <span style="font-size: 1.6rem; font-weight: 600; color: #6B7280; margin-left: 4px;">°C</span>
                </div>
                <div style="font-size: 1.1rem; color: #4B5563; margin-top: 8px; font-weight: 500;">
                    🌥️ {out_desc}
                </div>
                """, 
                unsafe_allow_html=True
            )
            
        with w_col2:
            str_min = round(float(t_min), 1) if t_min != "—" else "—"
            str_max = round(float(t_max), 1) if t_max != "—" else "—"
            str_feels = round(float(feels_like), 1) if feels_like != "—" else "—"
            
            st.markdown(
                f"""
                <div style="text-align: left; margin-top: 5px;">
                    <div style="color: #6c757d; font-size: 0.85rem;">Today's Range</div>
                    <div style="font-weight: 600; color: #374151; margin-bottom: 8px;">{str_min}° ~ {str_max}°</div>
                    <div style="color: #6c757d; font-size: 0.85rem;">Feels Like</div>
                    <div style="font-weight: 600; color: #374151;">{str_feels} °C</div>
                </div>
                """, 
                unsafe_allow_html=True
            )

        st.markdown("<hr style='margin: 15px 0;'>", unsafe_allow_html=True)

        m1, m2 = st.columns(2)
        
        # 自定义渲染湿度，替换掉笨重的 st.metric
        val_hum = f"{out_hum}" if out_hum != "—" else "—"
        unit_hum = "%" if out_hum != "—" else ""
        with m1:
            st.markdown(
                f"""
                <div style="color: #4B5563; font-size: 0.9rem; margin-bottom: 4px;">Humidity</div>
                <div style="display: flex; align-items: baseline;">
                    <span style="font-size: 2.2rem; font-weight: 700; color: #111827; line-height: 1;">{val_hum}</span>
                    <span style="font-size: 1.1rem; font-weight: 600; color: #6B7280; margin-left: 2px;">{unit_hum}</span>
                </div>
                """, unsafe_allow_html=True
            )

        # 自定义渲染风速，同样做基线对齐
        val_wind = f"{out_wind}" if out_wind != "—" else "—"
        unit_wind = "km/h" if out_wind != "—" else ""
        with m2:
            st.markdown(
                f"""
                <div style="color: #4B5563; font-size: 0.9rem; margin-bottom: 4px;">Wind</div>
                <div style="display: flex; align-items: baseline;">
                    <span style="font-size: 2.2rem; font-weight: 700; color: #111827; line-height: 1;">{val_wind}</span>
                    <span style="font-size: 1.1rem; font-weight: 600; color: #6B7280; margin-left: 4px;">{unit_wind}</span>
                </div>
                """, unsafe_allow_html=True
            )
        
        st.write("") 
        
        temp = current_metrics.get("indoor_temp")
        if temp:
            diff = round(float(temp) - float(out_t), 1)
            sign = "+" if diff > 0 else ""
            word = 'warmer' if diff > 0 else 'cooler'
            st.info(f"🏠 **Indoor is {sign}{diff} °C {word}** than outside", icon="💡")
    else:
        st.markdown("<div style='color:#6c757d; font-size: 14px; margin-top: 10px;'>🌥️ Weather API is currently unreachable.</div>", unsafe_allow_html=True)


with col_anom:
    st.markdown('<div class="section-label">System Anomalies & Alerts</div>', unsafe_allow_html=True)
    
    filter_c1, filter_c2, filter_c3 = st.columns(3)
    with filter_c1:
        filter_type = st.selectbox("Type", ["All", "CO2", "TVOC", "Humidity"])
    with filter_c2:
        filter_level = st.selectbox("Level", ["All", "🔴 Danger", "🟡 Warning"])
    with filter_c3:
        anom_range = st.selectbox("Period", ["Today", "7d", "30d", "Custom"])
    
    df_raw_anom = pd.DataFrame()
    valid_custom_range = True

    if anom_range == "Custom":
        with st.container(border=True):
            tc1, tc2 = st.columns(2)
            hours_options = [f"{i:02d}:00" for i in range(24)]
            
            with tc1:
                st.markdown("<div style='font-size: 11px; font-weight: 600; color: #888; margin-bottom: 4px;'>START RANGE</div>", unsafe_allow_html=True)
                start_d = st.date_input("Start Date", value=datetime.date.today(), label_visibility="collapsed")
                start_h_str = st.selectbox("Start Hour", hours_options, index=0, label_visibility="collapsed", key="sh")
            with tc2:
                st.markdown("<div style='font-size: 11px; font-weight: 600; color: #888; margin-bottom: 4px;'>END RANGE</div>", unsafe_allow_html=True)
                end_d = st.date_input("End Date", value=datetime.date.today(), label_visibility="collapsed")
                end_h_str = st.selectbox("End Hour", hours_options, index=23, label_visibility="collapsed", key="eh")

        start_h = int(start_h_str[:2])
        end_h = int(end_h_str[:2])
        start_dt = datetime.datetime.combine(start_d, datetime.time(start_h, 0, 0))
        end_dt = datetime.datetime.combine(end_d, datetime.time(end_h, 59, 59))

        if start_dt >= end_dt:
            st.error("⚠️ Chronological Error: End time must occur after start time.")
            valid_custom_range = False
        else:
            df_raw_anom = get_anomalies_by_dates(start_dt, end_dt)
    else:
        anom_days = {"Today": 1, "7d": 7, "30d": 30}[anom_range]
        df_raw_anom = get_anomalies(anom_days)

    if valid_custom_range and not df_raw_anom.empty:
        if filter_type != "All":
            df_raw_anom = df_raw_anom[df_raw_anom["type"].str.contains(filter_type, case=False, na=False)]
        if filter_level != "All":
            level_mapping = {"🔴 Danger": "danger", "🟡 Warning": "warning"}
            df_raw_anom = df_raw_anom[df_raw_anom["level"] == level_mapping[filter_level]]

    if valid_custom_range:
        if df_raw_anom.empty:
            if is_online:
                st.markdown("<div style='color:#10B981; font-size: 14px; margin-top: 15px;'>✅ No anomalies found matching the current filters.</div>", unsafe_allow_html=True)
            else:
                st.markdown("<div style='color:#6c757d; font-size: 14px; margin-top: 15px;'>📴 No anomaly records available for this filtered context.</div>", unsafe_allow_html=True)
        else:
            danger_count  = len(df_raw_anom[df_raw_anom["level"] == "danger"])
            warning_count = len(df_raw_anom[df_raw_anom["level"] == "warning"])
            st.markdown(f"<div style='font-size: 13px; color: #555; margin-top: 10px;'>Filtered Result: <b>{danger_count}</b> critical and <b>{warning_count}</b> warnings out of {len(df_raw_anom)} events.</div>", unsafe_allow_html=True)

            page_size = 4  
            total_pages = max(1, (len(df_raw_anom) + page_size - 1) // page_size)
            if "anom_page" not in st.session_state: st.session_state.anom_page = 0
            if st.session_state.anom_page >= total_pages: st.session_state.anom_page = 0

            start = st.session_state.anom_page * page_size
            page_df = df_raw_anom.iloc[start:start + page_size]

            for _, row in page_df.iterrows():
                ts = pd.to_datetime(row["timestamp"])
                ts_str = ts.strftime("%H:%M:%S") if anom_range == "Today" else ts.strftime("%b %d, %H:%M:%S")
                    
                css  = "anomaly-danger" if row["level"] == "danger" else "anomaly-warning"
                icon = "🚨" if row["level"] == "danger" else "⚠️"
                st.markdown(
                    f'<div class="{css}"><b>{icon} {row["type"]}</b> : {row["value"]}'
                    f'<span style="float:right; opacity:0.7; font-family: monospace;">{ts_str}</span></div>',
                    unsafe_allow_html=True
                )

            if total_pages > 1:
                p1, p2, p3 = st.columns([1, 2, 1])
                with p1:
                    if st.button("← Prev", disabled=st.session_state.anom_page == 0, use_container_width=True):
                        st.session_state.anom_page -= 1; st.rerun()
                with p2:
                    st.markdown(f"<div style='text-align:center; color:#888; margin-top:8px;'>Page {st.session_state.anom_page + 1} / {total_pages}</div>", unsafe_allow_html=True)
                with p3:
                    if st.button("Next →", disabled=st.session_state.anom_page >= total_pages - 1, use_container_width=True):
                        st.session_state.anom_page += 1; st.rerun()

# ── 3. Trend Analysis ─────────────────────────────────────────────────────────

trend_col1, trend_col2 = st.columns([3, 1])
with trend_col1:
    st.markdown('<div class="section-label" style="margin-top: 0;">Trend Analysis</div>', unsafe_allow_html=True)
with trend_col2:
    trend_range = st.radio("Trend Time range", ["1h", "24h", "7d"], horizontal=True, label_visibility="collapsed", index=1, key="trend_radio")

trend_hours = {"1h": 1, "24h": 24, "7d": 168}[trend_range]
df_hist = get_history(trend_hours)

ch1, ch2 = st.columns(2)
with ch1:
    st.plotly_chart(temp_humidity_chart(df_hist), use_container_width=True, config={"displayModeBar": False}, key="th_c")

with ch2:
    st.plotly_chart(co2_tvoc_chart(df_hist), use_container_width=True, config={"displayModeBar": False}, key="c2_c")

# ── 4. Long-term Insights ─────────────────────────────────────────────────────

df_motion = get_motion_heatmap(7)

st.markdown('<div class="section-label">Historical Insights (7 Days)</div>', unsafe_allow_html=True)

if df_daily.empty and df_motion.empty:
    st.info("📴 **Not enough data for historical insights.** The sensor appears to have been offline, disconnected, or unconfigured for the entire past week.")
else:
    h1, h2 = st.columns(2)
    with h1:
        st.plotly_chart(daily_temp_chart(df_daily), use_container_width=True, config={"displayModeBar": False}, key="dt_c")
    with h2:
        st.plotly_chart(motion_heatmap_chart(df_motion), use_container_width=True, config={"displayModeBar": False}, key="mh_c")