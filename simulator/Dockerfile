# Dockerfile — AuraSense virtual device (standard library only)
FROM python:3.11-slim

WORKDIR /app
COPY aurasense_sim.py .

# Backfill 7 days of history (skipped if data exists), then stream live readings
ENTRYPOINT ["python", "-u", "aurasense_sim.py"]
CMD ["run"]
