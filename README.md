# AuraSense 🌬️
> *See the air you breathe. An end-to-end IoT indoor air quality monitoring and AI advice system.*

[![Firmware](https://img.shields.io/badge/Firmware-UIFlow2.0_V2.4.4--CORE2-00BFFF.svg)](https://m5stack.com/)
[![Runtime](https://img.shields.io/badge/Runtime-MicroPython-yellow.svg)](https://micropython.org/)
[![Backend](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-Deployed-2496ED.svg?logo=docker)](https://www.docker.com/)
[![GCP](https://img.shields.io/badge/GCP-Compute_Engine-4285F4.svg?logo=google-cloud)](https://cloud.google.com/)
[![AI Brain](https://img.shields.io/badge/AI_Brain-Google_Gemini-8E75B2.svg)](https://aistudio.google.com/)

---

### 🌟 Quick Links

[![YouTube Demo](https://img.shields.io/badge/YouTube-Watch_Demo-C4302B?style=for-the-badge&logo=youtube&logoColor=white)](https://www.youtube.com/watch?v=83zbSBvbl1c)
[![GitHub Repo](https://img.shields.io/badge/GitHub-View_Source-24292E?style=for-the-badge&logo=github&logoColor=white)](https://github.com/embarky/AuraSense-M5StackCore2)
[![Live Dashboard](https://img.shields.io/badge/Live_Dashboard-Streamlit-E66465?style=for-the-badge&logo=streamlit&logoColor=white)](http://34.62.132.20:8501/)
[![User Manual](https://img.shields.io/badge/User_Manual-Download-1B9AAA?style=for-the-badge&logo=gitbook&logoColor=white)](assets/AuraSense_User_Manual.pdf)

---

## 1. Project Overview

AuraSense is a comprehensive IoT solution designed to monitor, analyze, and visualize indoor air quality in real-time. Built with an edge-to-cloud architecture, it utilizes an M5Stack Core2 device to collect environmental data (eCO2, TVOC, Temperature, Humidity, Motion) and transmits it to a containerized Google Cloud Platform (GCP) backend.

Beyond simple data logging, AuraSense integrates contextual outdoor weather data and dynamic voice announcements to provide actionable, human-centric advice for a healthier living environment.

---

![AuraSense Device Demo](assets/online.gif)

---

![AuraSense Dashboard Demo](assets/dashboard_devic_online.gif)

---

## 2. System Architecture & Tech Stack

AuraSense implements a decoupled architecture, separating edge telemetry acquisition from cloud-based analytics.

### 🔌 Edge Layer (M5Stack Core2)

![AuraSense Hardware Setup](assets/AuraSense.png)

* **Main Controller:** [M5Stack Core2 for AWS Edukit](https://docs.m5stack.com/en/core/core2_for_aws) (ESP32-D0WDQ6-V3, Touch Screen, integrated SPM1423 microphone, SK6812 RGB LED strip)
* **Firmware & Runtime:** UIFlow2.0 V2.4.4-CORE2 executing MicroPython
* **Hardware Port Mapping:**

  | Port | Sensor | Measures |
  |------|--------|----------|
  | Port A (I2C) | SGP30 TVOC/eCO2 Gas Sensor | eCO2, TVOC |
  | Port B (GPIO) | AS312 PIR Motion Sensor | Motion detection |
  | Port C (I2C) | ENV III Unit (SHT30 + QMP6988) | Temperature, Humidity, Pressure |

### ☁️ Cloud & Analytics Layer (GCP)

| Component | Technology | Role |
|-----------|-----------|------|
| Backend | Python / Flask | API server, AI orchestration |
| Data Lake | Google BigQuery | Time-series sensor persistence |
| Dashboard | Streamlit | Real-time analytics UI |
| AI Engine | Google Gemini API | Advice generation, voice assistant |
| TTS | Edge TTS | Speech synthesis |
| Weather | OpenWeatherMap API | Outdoor context |
| Infrastructure | Docker Compose on GCP | Containerized deployment |

---

## 3. Key Features

* 📡 **Edge Telemetry** — Real-time data ingestion every 3 seconds, upload every 30 seconds
* 🧠 **Context-Aware AI Advice** — Analyzes indoor/outdoor differentials to suggest physical actions
* 🎙️ **Voice Assistant** — Push-to-talk with Gemini-powered multi-turn conversation
* 🚨 **Smart Hardware Alerts** — RGB LED strip with threshold-based warning/danger states
* 🌦️ **Weather Fusion** — IP-based geolocation with 5-day OpenWeatherMap forecast
* 📊 **Live Dashboard** — Sparklines, anomaly log, trend analysis and AI recommendations
* 🔇 **Offline Mode** — Full sensor monitoring and LED alerts without WiFi

---

## 4. Feature Specifications

### LED Alert Strategy (IO25 / SK6812 RGB)

| State | Color | Interval | Condition |
|-------|-------|----------|-----------|
| Normal | OFF | — | All values within safe range |
| Warning | 🟡 Yellow | 500ms flash | eCO2 > 800 ppm OR TVOC > 220 ppb OR humidity < 30% / > 65% |
| Critical | 🔴 Red | 250ms flash | eCO2 > 1500 ppm OR TVOC > 660 ppb OR humidity < 20% / > 75% |

### Screen Policy

| State | Brightness | Trigger |
|-------|-----------|---------|
| Active | 100% | Motion detected / button / touch |
| Dimmed | 20% | 60 seconds of no motion |
| Off | 0% | 120 seconds of no motion |

### Upload Intervals

| Mode | Interval | Trigger |
|------|----------|---------|
| Standard | 30 seconds | Normal operation |
| Burst | 5 seconds | Warning/danger state active |
| Immediate | Instant | Critical anomaly initialized |

### Voice Alerts

* Triggered when Critical threshold persists for > **10 seconds**
* Repeats every **30 seconds** while danger persists
* Fires even when screen is off — overnight safety guaranteed

---

## 5. Run It

### ▶️ Quick start — no hardware, API keys or cloud account

```bash
git clone https://github.com/embarky/AuraSense-M5StackCore2.git
cd AuraSense-M5StackCore2
docker compose up --build
```

Open **http://localhost:8501**. A virtual device backfills 7 days of history and then streams live readings every 10 seconds, so every dashboard panel is populated within about a minute.

| Part | Local demo | Cloud deployment |
|------|-----------|------------------|
| Device | `simulator/` — physics-based virtual room | M5Stack Core2 |
| Storage | SQLite (Docker volume) | Google BigQuery |
| AI advice & voice | Rule-based offline mock | Google Gemini |
| Weather | Synthetic forecast | OpenWeatherMap |
| Speech | Chime | Edge TTS |

The **simulator** models one room: a CO₂ mass balance driven by a two-person weekday/weekend routine, ventilation and window opening, cooking-related TVOC, heating set-points and humidity sources. It also reproduces a property of the real sensor: the SGP30 reports *estimated* eCO₂, which is biased upward by VOCs. Scenarios: `mixed` (default), `normal`, `stuffy`, `dry` — set `SIM_SCENARIO` in `.env`. To export a CSV without running the stack:

```bash
python simulator/aurasense_sim.py export --days 7 --out readings.csv
```

Each provider can also be switched individually (for example `AI_PROVIDER=gemini` with `GEMINI_API_KEY`); see `.env.example`.

### ☁️ Cloud deployment with the real device

**Required services:**

| Service | Purpose | Where to get |
|---------|---------|--------------|
| Google Gemini API | AI advice + voice assistant | [aistudio.google.com](https://aistudio.google.com/) |
| OpenWeatherMap API | Outdoor weather context | [openweathermap.org](https://openweathermap.org/api) |
| GCP service account | BigQuery read/write access | GCP Console → IAM |
| Google BigQuery | Sensor data persistence | GCP Console |

**Server:**

1. Copy `.env.example` to `.env` and fill in every value under "Cloud deployment"
2. Run:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.gcp.yml up -d --build
   ```
3. Open ports **5001** and **8501** in your firewall. For any public deployment, put the backend behind an HTTPS reverse proxy.

**Device:**

1. Flash **UIFlow2.0 V2.4.4-CORE2** via [M5Burner](https://m5stack.com/pages/download)
2. Copy `device/config.example.py` to `device/config.py` and set `SERVER_HOST`, `API_KEY` (same value as `AURASENSE_API_KEY`) and `DEVICE_ID`. WiFi credentials can be entered later through the QR-code setup page.
3. Upload all files from `device/` to `/flash/` using Thonny
4. Set the device to run `main.py` on startup via M5Burner

> **Security:** every API endpoint except `GET /health` requires the `X-API-Key` header. `config.py`, `config.json`, `.env` and key files are gitignored and excluded from Docker images; install the [gitleaks](https://github.com/gitleaks/gitleaks) pre-commit hook with `pip install pre-commit && pre-commit install`.

---

## 6. Data Persistence

* **SQLite** (local demo) or **Google BigQuery** (cloud) behind one storage interface (`backend/storage/`)
* **Timezone:** All timestamps normalized to `Europe/Zurich`
* **Schema:** `timestamp`, `temperature`, `humidity`, `pressure`, `eco2`, `tvoc`, `motion_detected`, `timezone`
* **Query windows:** 1h / 24h / 7d / custom range supported

---

## Individual Contributions

| Member | Contributions |
|--------|--------------|
| **Hang Yang** | Device firmware (MicroPython) — sensor integration, LED alert system, screen management, voice assistant, WiFi stability and network resilience. Flask backend — API design, Gemini AI integration, TTS pipeline, BigQuery persistence, weather service, Docker deployment on GCP. |
| **Yi Huang** | Streamlit dashboard — real-time overview, sparkline charts, outdoor weather card, anomaly log panel, trend analysis, historical insights, AI advice integration, online/offline detection. |

---

## Made by

**Hang Yang & Yi Huang** — University of Lausanne, Cloud and Advanced Analytics 2026

---

*AuraSense — See the air you breathe.*