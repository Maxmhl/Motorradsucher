# ---------------------------------------------------------------------------
# Stufe 1: Frontend bauen
# ---------------------------------------------------------------------------
FROM node:22-alpine AS frontend

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# Stufe 2: Backend - das Playwright-Image bringt Chromium und alle
# Systembibliotheken für die JS-lastigen Seiten bereits mit.
# ---------------------------------------------------------------------------
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data

WORKDIR /app

# Abhängigkeiten zuerst - bleiben bei Code-Änderungen im Build-Cache.
COPY backend/pyproject.toml ./
RUN pip install --no-cache-dir . && python -m playwright install chromium

COPY backend/app ./app

# app/main.py erwartet das gebaute Frontend unter <repo>/frontend/dist;
# von /app/app aus sind das zwei Ebenen hoch, also /frontend/dist.
COPY --from=frontend /build/dist /frontend/dist

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/api/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
