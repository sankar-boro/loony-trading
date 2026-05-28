#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# dashboard/stop.sh — stop running dashboard processes
#
# Reads PID files written by start.sh.  Falls back to port-based kill if PIDs
# are stale (e.g. process was killed externally and PID file wasn't cleaned up).
#
# Usage:
#   bash dashboard/stop.sh
#   bash dashboard/stop.sh --force    # kill -9 instead of SIGTERM
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_DIR="$ROOT/.pids"
BACKEND_PID_FILE="$PID_DIR/dashboard_backend.pid"
FRONTEND_PID_FILE="$PID_DIR/dashboard_frontend.pid"

G="\033[92m"; R="\033[91m"; Y="\033[93m"; DIM="\033[2m"; E="\033[0m"

success() { echo -e "${G}✓${E} $*"; }
warn()    { echo -e "${Y}!${E} $*"; }
info()    { echo -e "${DIM}[dash]${E} $*"; }

FORCE=false
for arg in "$@"; do
  [ "$arg" = "--force" ] && FORCE=true
done

SIG="TERM"
$FORCE && SIG="KILL"

_kill_pid_file() {
  local label="$1" pid_file="$2"
  if [ -f "$pid_file" ]; then
    local pid
    pid=$(cat "$pid_file")
    if kill -0 "$pid" 2>/dev/null; then
      kill "-${SIG}" "$pid" 2>/dev/null && success "Stopped ${label} (PID ${pid})" \
        || warn "Could not kill ${label} PID ${pid}"
    else
      warn "${label} PID ${pid} already gone"
    fi
    rm -f "$pid_file"
  fi
}

_kill_by_port() {
  local label="$1" port="$2"
  local pid
  pid=$(lsof -ti tcp:"$port" 2>/dev/null | head -1 || true)
  if [ -n "$pid" ]; then
    kill "-${SIG}" "$pid" 2>/dev/null && success "Stopped ${label} on port ${port} (PID ${pid})" \
      || warn "Could not kill ${label} on port ${port}"
  fi
}

_kill_by_pattern() {
  local label="$1" pattern="$2"
  local pids
  pids=$(pgrep -f "$pattern" 2>/dev/null || true)
  if [ -n "$pids" ]; then
    echo "$pids" | xargs kill "-${SIG}" 2>/dev/null \
      && success "Stopped ${label} (${pids})" \
      || warn "Could not kill ${label}"
  fi
}

echo "Stopping Loony Trading dashboard…"

_kill_pid_file "Backend" "$BACKEND_PID_FILE"
_kill_pid_file "Frontend" "$FRONTEND_PID_FILE"

# Fallback: port-based cleanup
_kill_by_port  "FastAPI"  8000
_kill_by_pattern "Vite dev server" "vite"

echo ""
info "Done. All dashboard processes stopped."
