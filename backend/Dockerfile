# Dockerfile — AuraSense Backend
FROM python:3.11-slim

# Install ffmpeg for pydub audio processing
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Expose Flask port
EXPOSE 5001

# Run with gunicorn for production.
# ONE worker on purpose: the latest device snapshot and the per-device
# conversation histories are kept in process memory, so several worker
# processes would each hold a different copy (the dashboard would flicker
# between "online" and "offline"). Threads provide the concurrency instead.
CMD ["gunicorn", "--bind", "0.0.0.0:5001", "--workers", "1", "--threads", "8", "--timeout", "120", "app:create_app()"]