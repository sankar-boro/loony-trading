#!/usr/bin/env bash
# Start FastAPI backend + Vite dev server concurrently
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Load .env if present
if [ -f "$ROOT/.env" ]; then
  set -a; source "$ROOT/.env"; set +a
fi

# Start FastAPI in background
cd "$ROOT"
uvicorn dashboard.backend.main:app --reload --port 8000 &
BACKEND_PID=$!
echo "Backend PID: $BACKEND_PID"

# Start Vite dev server
cd "$ROOT/dashboard/frontend"
npm run dev

# Cleanup on exit
kill $BACKEND_PID 2>/dev/null || true
