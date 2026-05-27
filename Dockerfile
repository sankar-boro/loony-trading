FROM python:3.11-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Create runtime directories
RUN mkdir -p logs data/cache models

# Expose Streamlit dashboard port
EXPOSE 8501

# Default: run the trading bot in paper mode
CMD ["python", "main.py", "--mode", "paper"]
