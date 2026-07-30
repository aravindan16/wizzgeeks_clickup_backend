FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# System deps (build tools for bcrypt/cryptography if wheels unavailable)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn==22.0.0

COPY . .

EXPOSE 7302

# Production: gunicorn managing a uvicorn worker.
#
# IMPORTANT: run a SINGLE worker. Realtime (notifications + chat) uses an in-process
# connection hub (app/realtime/hub.py) that holds each user's WebSocket in memory.
# With multiple workers, a message handled by one worker can't reach a WebSocket held
# by another worker, so live delivery silently fails (messages only appear on refresh).
# A single async uvicorn worker handles many concurrent connections fine. To scale out
# to multiple workers/instances later, add a pub/sub backplane (Redis or Mongo change
# streams) behind hub.push() and bump this back up.
ENV WEB_CONCURRENCY=1
CMD ["gunicorn", "app.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:7302", \
     "--workers", "1", "--timeout", "120"]
