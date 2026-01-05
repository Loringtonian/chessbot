# Multi-stage Dockerfile for Chess Coach
# Stage 1: Build frontend
FROM node:20-slim AS frontend

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

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
