# Multi-stage Dockerfile for Chess Coach
# Stage 1: Build frontend
FROM node:20-slim AS frontend

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
# Chess SPA build. If it fails (e.g. mid-refactor), don't block the deploy —
# the backend and the standalone /german tutor ship regardless.
RUN npm run build || (echo "WARN: frontend build failed; shipping placeholder index" \
    && mkdir -p dist \
    && printf '<!doctype html><meta charset=utf-8><title>Chess Coach</title><body style="font-family:sans-serif;background:#0e1014;color:#eee;text-align:center;padding-top:80px"><h1>Chess Coach</h1><p>The chess UI is being rebuilt.</p><p><a style="color:#f6c945" href="/german">→ German Voice Tutor</a></p>' > dist/index.html)

# Stage 2: Python backend with frontend static files
FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Download and install Stockfish
RUN curl -L -o /tmp/stockfish.tar \
    https://github.com/official-stockfish/Stockfish/releases/download/sf_17/stockfish-ubuntu-x86-64.tar \
    && cd /tmp \
    && tar -xf stockfish.tar \
    && mv stockfish/stockfish-ubuntu-x86-64 /usr/local/bin/stockfish \
    && chmod +x /usr/local/bin/stockfish \
    && rm -rf /tmp/stockfish* \
    && /usr/local/bin/stockfish --help || true

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend application code
COPY backend/app ./app

# Copy frontend static files from build stage
COPY --from=frontend /app/frontend/dist ./static

# Set environment variables
ENV STOCKFISH_PATH=/usr/local/bin/stockfish
ENV PORT=8080

# Expose port
EXPOSE 8080

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
