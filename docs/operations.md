# Operations

## Deploy to Google Cloud

1. Create a BigQuery dataset and table (schema in `backend/storage/bigquery.py`) and a service account with BigQuery Data Editor and Job User roles.
2. On the VM: clone the repository, copy `.env.example` to `.env`, fill in every value under "Cloud deployment", and put the service-account key at `GCP_CREDENTIALS_PATH`.
3. `docker compose -f docker-compose.yml -f docker-compose.gcp.yml up -d --build`
4. Put the backend behind an HTTPS reverse proxy; open only the ports you need.
5. Flash the device with `device/config.py` pointing to the server and containing the same `API_KEY` ([device-setup.md](device-setup.md)).

## Routine tasks

| Task | How |
|---|---|
| Check health | `curl https://<server>/health` |
| Logs | `docker compose logs -f backend` |
| Rotate the API key | Change `AURASENSE_API_KEY` in `.env`, restart, update `API_KEY` on every device |
| Rotate a provider key | Revoke it in the provider console, update `.env`, restart |
| Back up readings | BigQuery: `bq extract` to Cloud Storage or export query results. SQLite: copy the `aurasense-data` volume |

## Decommissioning checklist

Shutting down a cloud deployment deletes its data. Work through this list first.

- [ ] Export all readings (BigQuery → CSV/Parquet) and store them outside the cloud project
- [ ] Save dashboard screenshots and a short recording
- [ ] Revoke API keys (Gemini, OpenWeatherMap) and delete service-account keys
- [ ] Remove the API key from deployed devices or reflash them
- [ ] Stop the VM, then delete the project; note the 30-day recovery window
- [ ] Update the README so it no longer links to the live deployment
