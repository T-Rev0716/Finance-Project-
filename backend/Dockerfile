# Build context is the repo root (Railway's dockerfilePath, see .railway/railway.ts), so this
# can copy both backend/ and the sibling data/samples/ the app reads by default.
FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt \
    && playwright install --with-deps chromium

COPY backend backend
COPY data data

WORKDIR /app/backend

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
