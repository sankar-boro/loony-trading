#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# dashboard/start.sh — start the Loony Trading dashboard
#
# Usage:
#   bash dashboard/start.sh            # dev mode  (Vite :5173 + FastAPI :8000)
#   bash dashboard/start.sh --prod     # prod mode (build + FastAPI :8000)
#   bash dashboard/start.sh --port 9000   # custom backend port (prod only)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_DIR="$ROOT/.pids"
BACKEND_PID_FILE="$PID_DIR/dashboard_backend.pid"
FRONTEND_PID_FILE="$PID_DIR/dashboard_frontend.pid"
LOG_DIR="$ROOT/logs"
BACKEND_LOG="$LOG_DIR/dashboard_backend.log"
FRONTEND_LOG="$LOG_DIR/dashboard_frontend.log"

G="\033[92m"; R="\033[91m"; Y="\033[93m"; B="\033[1m"; DIM="\033[2m"; E="\033[0m"

info()    { echo -e "${DIM}[dash]${E} $*"; }
success() { echo -e "${G}✓${E} $*"; }
warn()    { echo -e "${Y}!${E} $*"; }
error()   { echo -e "${R}✗${E} $*" >&2; }

PROD=false
PORT=8000

for arg in "$@"; do
  case $arg in
    --prod)   PROD=true ;;
    --port=*) PORT="${arg#*=}" ;;
    --port)   shift; PORT="$1" ;;
  esac
done

mkdir -p "$PID_DIR" "$LOG_DIR"

# ── Load .env ──────────────────────────────────────────────────────────────────
if [ -f "$ROOT/.env" ]; then
  set -a; source "$ROOT/.env"; set +a
fi

# ── Check if already running ──────────────────────────────────────────────────
_is_running() {
  local pid_file="$1"
  [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null
}

if _is_running "$BACKEND_PID_FILE"; then
  warn "Backend already running (PID $(cat "$BACKEND_PID_FILE"))."
  warn "Run: bash dashboard/stop.sh  to stop it first."
  exit 1
fi

# ── Production mode: build then serve ─────────────────────────────────────────
if $PROD; then
  echo -e "${B}Starting dashboard (production)${E}"
  info "Building React frontend…"
  cd "$ROOT/dashboard/frontend"
  npm run build --silent
  success "Frontend built → dist/"

  cd "$ROOT"
  info "Starting FastAPI on port ${PORT}…"
  uvicorn dashboard.backend.main:app --host 0.0.0.0 --port "$PORT" \
    >> "$BACKEND_LOG" 2>&1 &
  BACKEND_PID=$!
  echo "$BACKEND_PID" > "$BACKEND_PID_FILE"

  sleep 2
  if kill -0 "$BACKEND_PID" 2>/dev/null; then
    success "Dashboard running on http://localhost:${PORT}"
    echo -e "  ${DIM}Backend PID: ${BACKEND_PID}  •  Log: ${BACKEND_LOG}${E}"
    echo -e "  ${DIM}Stop with: bash dashboard/stop.sh${E}"
  else
    error "Backend failed to start. Check ${BACKEND_LOG}"
    exit 1
  fi
  exit 0
fi

# ── Dev mode: FastAPI + Vite concurrently ─────────────────────────────────────
echo -e "${B}Starting dashboard (dev mode)${E}"

cd "$ROOT"
info "Starting FastAPI backend on port 8000…"
uvicorn dashboard.backend.main:app --reload --port 8000 \
  >> "$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!
echo "$BACKEND_PID" > "$BACKEND_PID_FILE"

sleep 2
if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
  error "Backend failed to start. Check ${BACKEND_LOG}"
  exit 1
fi
success "Backend running (PID ${BACKEND_PID})"

cd "$ROOT/dashboard/frontend"
info "Starting Vite dev server…"
npm run dev >> "$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!
echo "$FRONTEND_PID" > "$FRONTEND_PID_FILE"

sleep 3
# Extract the actual port Vite picked (it increments if 5173 is busy)
VITE_PORT=$(grep -oP '(?<=Local:   http://localhost:)\d+' "$FRONTEND_LOG" 2>/dev/null | tail -1 || echo "5173")

if kill -0 "$FRONTEND_PID" 2>/dev/null; then
  success "Frontend running on http://localhost:${VITE_PORT}"
else
  warn "Vite may have failed. Check ${FRONTEND_LOG}"
fi

echo ""
echo -e "  ${G}Dashboard:${E}  http://localhost:${VITE_PORT}"
echo -e "  ${G}API:${E}        http://localhost:8000"
echo -e "  ${G}API docs:${E}   http://localhost:8000/api/docs"
echo ""
echo -e "  ${DIM}Backend PID: ${BACKEND_PID}   Frontend PID: ${FRONTEND_PID}${E}"
echo -e "  ${DIM}Stop: bash dashboard/stop.sh  •  Logs: tail -f ${BACKEND_LOG}${E}"
