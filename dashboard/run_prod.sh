#!/usr/bin/env bash
# Build React app and serve via FastAPI (single-port production)
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Load .env if present
if [ -f "$ROOT/.env" ]; then
  set -a; source "$ROOT/.env"; set +a
fi

# Build frontend
cd "$ROOT/dashboard/frontend"
npm run build

# Serve from FastAPI
cd "$ROOT"
uvicorn dashboard.backend.main:app --host 0.0.0.0 --port 8000
