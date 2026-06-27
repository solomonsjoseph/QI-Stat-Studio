# Stage 1: Build frontend
FROM node:20-alpine AS frontend
WORKDIR /web
COPY web/package*.json ./
RUN npm ci
COPY web/ .
RUN npm run build

# Stage 2: Python backend + static frontend
FROM python:3.11-slim

WORKDIR /app

# System deps for spaCy and matplotlib
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m spacy download en_core_web_sm

COPY api/ ./api/
COPY --from=frontend /web/dist ./web/dist

# Serve static frontend from FastAPI
RUN pip install --no-cache-dir aiofiles

EXPOSE 8000

ENV PYTHONPATH=/app

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
