"""
dashboard/charts.py — Plotly chart factory functions.
"""
from __future__ import annotations
import pandas as pd
import plotly.graph_objects as go

# ── Color palette ─────────────────────────────────────────────────────────────
C_BLUE   = "#378ADD"
C_GREEN  = "#1D9E75"
C_AMBER  = "#EF9F27"
C_TEAL   = "#5DCAA5"
C_RED    = "#E24B4A"
C_GRID   = "rgba(0,0,0,0.06)"

def create_offline_placeholder(height: int = 220) -> go.Figure:
    """
    Generates a placeholder chart with an explicit offline watermark 
    when no data is available in the selected time range.
    """
    fig = go.Figure()
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0.02)", # Slight gray tint to indicate inactivity
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
    if df.empty or "timestamp" not in df:
        return create_offline_placeholder(height=220)

    fig = go.Figure()
    x_vals = df["timestamp"]

    if "temperature" in df:
        y_temp = df["temperature"].astype(float).round(1).tolist()
        fig.add_trace(go.Scatter(
            x=x_vals, y=y_temp,
            name="Temp (°C)", line=dict(color=C_BLUE, width=2),
            connectgaps=False,  # Break line on missing data
            hovertemplate="%{y}°C<extra></extra>", yaxis="y1"
        ))
        
    if "humidity" in df:
        y_hum = df["humidity"].astype(float).round(1).tolist()
        fig.add_trace(go.Scatter(
            x=x_vals, y=y_hum,
            name="Humidity (%)", line=dict(color=C_GREEN, width=2, dash="dot"),
            connectgaps=False,  # Break line on missing data
            hovertemplate="%{y}%<extra></extra>", yaxis="y2"
        ))

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="system-ui, sans-serif", size=12),
        margin=dict(l=0, r=50, t=24, b=0), height=220,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        xaxis=dict(showgrid=False, zeroline=False),
        yaxis=dict(title="°C", showgrid=True, gridcolor=C_GRID, zeroline=False, side="left"),
        yaxis2=dict(title="%", showgrid=False, zeroline=False, overlaying="y", side="right"),
    )
    return fig


def co2_tvoc_chart(df: pd.DataFrame) -> go.Figure:
    if df.empty or "eco2" not in df or "tvoc" not in df or "timestamp" not in df:
        return create_offline_placeholder(height=220)

    fig = go.Figure()

    # Threshold reference lines
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
        margin=dict(l=0, r=50, t=24, b=0), height=220,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        xaxis=dict(showgrid=False, zeroline=False),
        yaxis=dict(title="ppm", showgrid=True, gridcolor=C_GRID, zeroline=False, side="left", range=[eco2_min, eco2_max]),
        yaxis2=dict(title="ppb", showgrid=False, zeroline=False, overlaying="y", side="right", range=[tvoc_min, tvoc_max]),
    )
    return fig


def daily_temp_chart(df: pd.DataFrame) -> go.Figure:
    if df.empty or "date" not in df:
        return create_offline_placeholder(height=220)
        
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
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="system-ui, sans-serif", size=12),
        margin=dict(l=30, r=0, t=24, b=0), height=220,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        xaxis=dict(showgrid=False, zeroline=False, type="category"),
        yaxis=dict(showgrid=True, gridcolor=C_GRID, zeroline=False, title=dict(text="°C", font=dict(size=11))),
    )
    return fig


def motion_heatmap_chart(df: pd.DataFrame) -> go.Figure:
    if df.empty or "day" not in df or "hour" not in df:
        return create_offline_placeholder(height=200)

    day_order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    hours = list(range(24))
    grid = {d: {h: 0 for h in hours} for d in day_order}
    
    clean_df = df.dropna(subset=["day", "hour"])
    for _, row in clean_df.iterrows():
        d_raw = str(row["day"])
        d = d_raw[:3].capitalize()
        try:
            h = int(float(row["hour"]))
            count = int(float(row.get("motion_count", 0)))
            if d in grid and h in grid[d]:
                grid[d][h] = max(grid[d][h], count)
        except (ValueError, TypeError):
            continue

    z = [[grid[d][h] for h in hours] for d in day_order]

    fig = go.Figure(go.Heatmap(
        z=z,
        x=[f"{h:02d}:00" for h in hours],
        y=day_order,
        colorscale=[[0, "#F1EFE8"], [0.25, "#B5D4F4"],
                    [0.5, "#85B7EB"], [0.75, "#378ADD"], [1, "#185FA5"]],
        showscale=False,
        hovertemplate="%{y} %{x}: %{z} detections<extra></extra>"
    ))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="system-ui, sans-serif", size=12),
        margin=dict(l=40, r=0, t=8, b=30), height=200,
        yaxis=dict(autorange="reversed", showgrid=False, zeroline=False),
        xaxis=dict(showgrid=False, zeroline=False, tickvals=[f"{h:02d}:00" for h in range(0, 24, 4)])
    )
    return fig