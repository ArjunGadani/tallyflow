# TallyFlow — single Cloud Run image: FastAPI backend + built dashboard.
# Built from the repo ROOT so `gcloud run deploy --source .` picks it up.

# ---- stage 1: build the dashboard (same-origin -> VITE_API_BASE empty) ----
FROM node:20-slim AS dashboard
WORKDIR /dash
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci
COPY dashboard/ ./
ENV VITE_API_BASE="" \
    VITE_DEMO="false"
RUN npm run build                          # -> /dash/dist

# ---- stage 2: backend + bundled dashboard ----
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# opencv-python-headless / pdfplumber runtime libs (kept minimal for cold start).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY pyproject.toml ./pyproject.toml
COPY backend ./backend
COPY --from=dashboard /dash/dist ./dashboard/dist

# Non-root for safety.
RUN useradd -m appuser
USER appuser

# Cloud Run injects $PORT; default 8080 for local docker run.
# --proxy-headers + trusted forwarded IPs so request.client.host is the REAL client
# (Cloud Run terminates TLS upstream) — the chat rate-limiter keys on it.
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips='*'"]
