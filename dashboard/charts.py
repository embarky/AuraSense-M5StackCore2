"""
dashboard/charts.py — Plotly chart factory functions.
"""
from __future__ import annotations
import pandas as pd
import plotly.graph_objects as go

# ── Color Palette ─────────────────────────────────────────────────────────────
C_BLUE   = "#378ADD"
C_GREEN  = "#1D9E75"
C_AMBER  = "#EF9F27"
C_TEAL   = "#5DCAA5"
C_RED    = "#E24B4A"
C_GRID   = "rgba(0,0,0,0.06)"

# -- Activity Colorscale --
# Maps zero activity to a light gray tint, and increasing activity to shades of blue.
COLORSCALE_BLUE_ACTIVE = [
    [0.0, "rgba(241, 239, 232, 1)"], # Zero Activity - Light gray tint
    [0.2, "rgba(181, 212, 244, 1)"], # Low Activity
    [0.5, "rgba(133, 183, 235, 1)"], # Moderate Activity
    [0.8, "rgba(55, 138, 221, 1)"],  # High Activity
    [1.0, "rgba(24, 95, 165, 1)"]    # Critical Activity
]

def create_offline_placeholder(height: int = 220) -> go.Figure:
    """
    Generates a placeholder chart with an explicit offline watermark 
    when no data is available in the selected time range.
    """
    fig = go.Figure()
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0.02)", 
        height=height,
        margin=dict(l=0, r=0, t=24, b=0),
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        annotations=[dict(
            text="📴 Device Offline<br><span style='font-size:12px;color:#888'>No data recorded during this period</span>",
            xref="paper", yref="paper",
            x=0.5, y=0.5,
            showarrow=False,
            font=dict(size=16, color="#A0A0A0"),
            align="center"
        )]
    )
    return fig


def temp_humidity_chart(df: pd.DataFrame) -> go.Figure:
    """Generates a multi-axis line chart for indoor temperature and humidity."""
    if df.empty or "timestamp" not in df:
        return create_offline_placeholder(height=220)

    fig = go.Figure()
    x_vals = df["timestamp"]

    if "temperature" in df:
        y_temp = df["temperature"].astype(float).round(1).tolist()
        fig.add_trace(go.Scatter(
            x=x_vals, y=y_temp,
            name="Temp (°C)", line=dict(color=C_BLUE, width=2),
            connectgaps=False,  
            hovertemplate="%{y}°C<extra></extra>", yaxis="y1"
        ))
        
    if "humidity" in df:
        y_hum = df["humidity"].astype(float).round(1).tolist()
        fig.add_trace(go.Scatter(
            x=x_vals, y=y_hum,
            name="Humidity (%)", line=dict(color=C_GREEN, width=2, dash="dot"),
            connectgaps=False,  
            hovertemplate="%{y}%<extra></extra>", yaxis="y2"
        ))

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="system-ui, sans-serif", size=12),
        margin=dict(l=0, r=50, t=50, b=0), height=220,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        xaxis=dict(showgrid=False, zeroline=False),
        yaxis=dict(title="°C", showgrid=True, gridcolor=C_GRID, zeroline=False, side="left"),
        yaxis2=dict(title="%", showgrid=False, zeroline=False, overlaying="y", side="right"),
    )
    return fig


def co2_tvoc_chart(df: pd.DataFrame) -> go.Figure:
    """Generates a multi-axis line chart for Air Quality (eCO2 and TVOC)."""
    if df.empty or "eco2" not in df or "tvoc" not in df or "timestamp" not in df:
        return create_offline_placeholder(height=220)

    fig = go.Figure()

    for y_line, color, label in [(1500, C_RED, "Danger 1500"), (800, C_AMBER, "Warning 800")]:
        fig.add_hline(y=y_line, line=dict(color=color, width=1, dash="dot"),
                      annotation_text=label, annotation_position="top right",
                      annotation_font_size=10)

    s_eco2 = df["eco2"].astype(float)
    s_tvoc = df["tvoc"].astype(float)
    valid_eco2 = s_eco2.dropna()
    valid_tvoc = s_tvoc.dropna()
    
    eco2_min = max(0, float(valid_eco2.min()) * 0.9) if not valid_eco2.empty else 0
    eco2_max = max(float(valid_eco2.max()) * 1.1, 1600) if not valid_eco2.empty else 1600
    tvoc_min = 0
    tvoc_max = max(float(valid_tvoc.max()) * 1.2, 50) if not valid_tvoc.empty else 50

    fig.add_trace(go.Scatter(
        x=df["timestamp"], y=s_eco2.round(0).tolist(),
        name="eCO2 (ppm)", line=dict(color=C_BLUE, width=2),
        connectgaps=False, 
        hovertemplate="%{y} ppm<extra></extra>", yaxis="y1"
    ))
    fig.add_trace(go.Scatter(
        x=df["timestamp"], y=s_tvoc.round(0).tolist(),
        name="TVOC (ppb)", line=dict(color=C_TEAL, width=2, dash="dot"),
        connectgaps=False,
        hovertemplate="%{y} ppb<extra></extra>", yaxis="y2"
    ))
    
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="system-ui, sans-serif", size=12),
        margin=dict(l=0, r=50, t=50, b=0), height=220,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        xaxis=dict(showgrid=False, zeroline=False),
        yaxis=dict(title="ppm", showgrid=True, gridcolor=C_GRID, zeroline=False, side="left", range=[eco2_min, eco2_max]),
        yaxis2=dict(title="ppb", showgrid=False, zeroline=False, overlaying="y", side="right", range=[tvoc_min, tvoc_max]),
    )
    return fig

def daily_temp_chart(df: pd.DataFrame) -> go.Figure:
    """Generates a scatter chart showing daily max, average, and min temperature extremes."""
    if df.empty or "date" not in df:
        return create_offline_placeholder(height=280)
        
    fig = go.Figure()
    dates = pd.to_datetime(df["date"])
    labels = dates.dt.strftime("%a %d/%m")

    fig.add_trace(go.Scatter(
        x=labels, y=df["temp_max"].astype(float).tolist(),
        name="Max", mode="markers",
        marker=dict(color="#185FA5", size=8, symbol="circle"),
        hovertemplate="%{y}°C<extra>Max</extra>",
    ))
    fig.add_trace(go.Scatter(
        x=labels, y=df["temp_avg"].astype(float).tolist(),
        name="Avg", mode="markers+lines",
        marker=dict(color=C_BLUE, size=8, symbol="circle"),
        line=dict(color=C_BLUE, width=1.5, dash="dot"),
        hovertemplate="%{y}°C<extra>Avg</extra>",
    ))
    fig.add_trace(go.Scatter(
        x=labels, y=df["temp_min"].astype(float).tolist(),
        name="Min", mode="markers",
        marker=dict(color="#B5D4F4", size=8, symbol="circle"),
        hovertemplate="%{y}°C<extra>Min</extra>",
    ))

    fig.update_layout(
        title=dict(text="Daily Temperature Extremes", font=dict(size=14, color="#6c757d")),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="system-ui, sans-serif", size=12),
        margin=dict(l=40, r=20, t=50, b=80), height=280,  
        legend=dict(orientation="h", yanchor="top", y=-0.25, xanchor="center", x=0.5),
        xaxis=dict(showgrid=False, zeroline=False, type="category"),
        yaxis=dict(showgrid=True, gridcolor=C_GRID, zeroline=False, title=dict(text="°C", font=dict(size=11))),
    )
    return fig


def motion_heatmap_chart(df: pd.DataFrame) -> go.Figure:
    """Generates a weekly motion activity heatmap synchronized with left chart layout."""
    if df.empty or ("day" not in df and "date" not in df) or "hour" not in df:
        return create_offline_placeholder(height=280)

    today = pd.Timestamp.now().normalize()
    dates = [today - pd.Timedelta(days=i) for i in range(6, -1, -1)]
    hours = list(range(24))
    
    grid = {d.strftime("%Y-%m-%d"): {h: 0 for h in hours} for d in dates}
    
    clean_df = df.dropna(subset=["hour"])
    for _, row in clean_df.iterrows():
        try:
            h = int(float(row["hour"]))
            count = int(float(row.get("motion_count", 0)))
            
            if "date" in row and pd.notna(row["date"]):
                d_str = str(row["date"])[:10]
            elif "day" in row and pd.notna(row["day"]):
                d_name = str(row["day"])[:3].capitalize()
                matched_date = next((d for d in dates if d.strftime("%a") == d_name), None)
                if not matched_date:
                    continue
                d_str = matched_date.strftime("%Y-%m-%d")
            else:
                continue
                
            if d_str in grid and h in grid[d_str]:
                grid[d_str][h] = max(grid[d_str][h], count)
        except (ValueError, TypeError):
            continue

    y_labels = []
    for d in dates:
        if d == today:
            y_labels.append("Today")
        else:
            y_labels.append(d.strftime("%a %d/%m"))

    z = [[grid[d.strftime("%Y-%m-%d")][h] for h in hours] for d in dates]
    x_labels = [f"{h}h" for h in hours]

    max_z = max([max(row) for row in z]) if z else 0
    max_z = max(1, max_z) 

    fig = go.Figure(go.Heatmap(
        z=z,
        x=x_labels,
        y=y_labels,
        colorscale=COLORSCALE_BLUE_ACTIVE,
        zmin=0,
        zmax=max_z,
        showscale=True, 
        colorbar=dict(
            title="",
            orientation="h",
            yanchor="top",
            y=-0.25, 
            x=0.5,
            xanchor="center",
            thickness=10,
            len=0.5,
            tickmode="array",
            tickvals=[0, max_z],
            ticktext=["None", "Active"],
            outlinewidth=0,
            tickfont=dict(size=12, color="#6c757d")
        ),
        xgap=2, ygap=2,
        hovertemplate="%{y} %{x}: %{z} detections<extra></extra>"
    ))
    
    fig.update_layout(
        title=dict(text="Motion Activity & Occupancy", font=dict(size=14, color="#6c757d")),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="system-ui, sans-serif", size=12),
        # 共享完全一致的 margin 和 height
        margin=dict(l=40, r=20, t=50, b=80), height=280,
        xaxis=dict(showgrid=False, zeroline=False, tickvals=["0h", "6h", "12h", "18h"]),
    )
    # 【对齐修复】强行锁死 y 轴比例为 1:1，保证每个单元格都是绝对的正方形
    fig.update_layout(
        yaxis=dict(scaleanchor="x", scaleratio=1, autorange="reversed", showgrid=False, zeroline=False)
    )
    
    return fig