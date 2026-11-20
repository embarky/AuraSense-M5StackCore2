# Changelog

## Unreleased

### Added
- Device setup guide (docs/device-setup.md): flashing UIFlow 2, configuration, upload, troubleshooting
- 70-second product video on YouTube, linked at the top of the README; replaces the 7-minute course demo video

### Fixed
- Air-pressure card labelled normal readings at Lausanne's altitude as "Unusual"; it now shows the 3-hour trend
- Edge TTS provider failed on Python 3.13 (audioop removed); backend tests now run on 3.11 and 3.13

## v2.0 — November 2026

Post-course improvements (Hang Yang).

### Security
- API-key authentication on every endpoint except `/health`; rate limits on endpoints that call paid APIs; generic error responses
- Secrets removed from the repository and its history (keys revoked); `.gitignore`, `.dockerignore` and a gitleaks scan in pre-commit and CI
- Configuration through `.env` / environment variables; nothing project-specific hard-coded in Compose files

### Fixed
- Dashboard could show the device offline: live state was split across two gunicorn workers
- One conversation history was shared by every user; now per device and thread-safe
- Device clock was one hour off outside summer time (hard-coded UTC+2)
- A quote in a WiFi password could write an invalid `config.py` and stop the device booting
- WAV header diagnostics never worked (`getsSpampwidth` typo)
- SQL built by string formatting and unbounded time windows; now query parameters with limits
- Private-IP detection treated public `172.x` addresses as Docker-internal
- Dashboard date-range filter interpreted Zurich time as UTC
- Dashboard weather card failed once API authentication was enabled

### Added
- Pluggable providers: SQLite or BigQuery, Gemini or rule-based AI, OpenWeatherMap or synthetic weather, Edge TTS or chime
- One-command local demo (`docker compose up`) with a physics-based device simulator
- Batch ingestion endpoint and optional measurement timestamps
- 77 tests (backend, dashboard, simulator, MicroPython firmware) and GitHub Actions CI with a Docker end-to-end check
- Design document, operations guide, new README with real device media

### Changed
- Pinned dependency versions
- Logging instead of print statements

## v1.0 — May 2026

Course project for *Cloud and Advanced Analytics*, University of Lausanne (Hang Yang, Yi Huang): M5Stack Core2 firmware with offline mode, LED and voice alerts and a voice assistant; Flask backend with Gemini, Edge TTS, OpenWeatherMap and BigQuery; Streamlit dashboard; Docker deployment on Google Cloud.
