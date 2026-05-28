FROM python:3.11-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    build-essential \
    curl \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Build React frontend
COPY dashboard/frontend/package*.json dashboard/frontend/
RUN cd dashboard/frontend && npm ci --silent

COPY dashboard/frontend/ dashboard/frontend/
RUN cd dashboard/frontend && npm run build

# Copy the rest of the source
COPY . .

# Create runtime directories
RUN mkdir -p logs data/cache data/nse_cache models .pids

# Expose FastAPI backend port
EXPOSE 8000

# Default: paper trading bot
CMD ["python", "main.py", "--mode", "paper"]
