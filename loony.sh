#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# loony.sh — Loony Trading command-line interface
#
# Usage:
#   ./loony.sh <command> [options]
#
# Commands:
#   start          Start dashboard (dev mode)
#   start --prod   Start dashboard (production mode)
#   stop           Stop all dashboard processes
#   restart        Stop then start dashboard
#   status         Show full system status
#   logs [--errors] [--n N]   Tail logs
#
#   paper          Start paper trading session
#   signals        Run live signal scanner
#   backtest       Run backtester
#   train          Train ML models
#   tune           Tune strategy weights
#   market         Show live market watch
#
#   token          Check / refresh Upstox token
#   health         Run full system health check
#   report         Show strategy performance report
#   journal        Show trade journal
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${PYTHON:-python3}"

G="\033[92m"; R="\033[91m"; Y="\033[93m"; B="\033[1m"; C="\033[96m"; DIM="\033[2m"; E="\033[0m"

_banner() {
  echo -e "${B}${C}"
  echo "  ██╗      ██████╗  ██████╗ ███╗   ██╗██╗   ██╗"
  echo "  ██║     ██╔═══██╗██╔═══██╗████╗  ██║╚██╗ ██╔╝"
  echo "  ██║     ██║   ██║██║   ██║██╔██╗ ██║ ╚████╔╝ "
  echo "  ██║     ██║   ██║██║   ██║██║╚██╗██║  ╚██╔╝  "
  echo "  ███████╗╚██████╔╝╚██████╔╝██║ ╚████║   ██║   "
  echo "  ╚══════╝ ╚═════╝  ╚═════╝ ╚═╝  ╚═══╝   ╚═╝   Trading"
  echo -e "${E}"
}

_help() {
  _banner
  echo -e "${B}Usage:${E}  ./loony.sh <command> [options]"
  echo ""
  echo -e "${B}Dashboard:${E}"
  echo "  start           Start dashboard in dev mode  (API :8000, Vite :5173)"
  echo "  start --prod    Start dashboard in prod mode (API :8000)"
  echo "  stop            Stop dashboard processes"
  echo "  restart         Restart dashboard"
  echo "  status          Show server + bot + market status"
  echo "  logs            Tail backend log (--errors for errors only, --n N for N lines)"
  echo ""
  echo -e "${B}Trading:${E}"
  echo "  paper           Start paper trading session"
  echo "  signals         Run live signal scanner"
  echo "  backtest        Run backtest on default symbols"
  echo "  market          Live market watch (prices + indices)"
  echo ""
  echo -e "${B}Models & Config:${E}"
  echo "  train           Train XGBoost + LightGBM ML models"
  echo "  tune            Tune strategy weights (2-year backtest)"
  echo ""
  echo -e "${B}Reports & Tools:${E}"
  echo "  health          Full system health check"
  echo "  report          Per-strategy performance report"
  echo "  journal         Trade journal (closed trades)"
  echo "  token           Check Upstox token status"
  echo "  token --refresh Refresh Upstox token (OAuth)"
  echo ""
  echo -e "${DIM}Examples:${E}"
  echo "  ./loony.sh start"
  echo "  ./loony.sh paper --symbols RELIANCE,TCS --tick 30"
  echo "  ./loony.sh signals --min-confidence 0.6"
  echo "  ./loony.sh logs --errors"
  echo "  ./loony.sh backtest --symbol RELIANCE --days 730"
}

_require_token() {
  if ! "$PYTHON" scripts/check_token.py 2>/dev/null | grep -q "valid\|ok\|OK"; then
    echo -e "${Y}⚠  Token may be expired — trying to continue anyway.${E}"
  fi
}

CMD="${1:-help}"
shift || true

case "$CMD" in

  # ── Dashboard ───────────────────────────────────────────────────────────────

  start)
    bash "$ROOT/dashboard/start.sh" "$@"
    ;;

  stop)
    bash "$ROOT/dashboard/stop.sh" "$@"
    ;;

  restart)
    echo -e "${Y}Restarting dashboard…${E}"
    bash "$ROOT/dashboard/stop.sh" --force 2>/dev/null || true
    sleep 2
    bash "$ROOT/dashboard/start.sh" "$@"
    ;;

  status)
    echo -e "\n${B}  Loony Trading — System Status${E}"
    echo "  $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""

    # Dashboard backend
    BACKEND_PID_FILE="$ROOT/.pids/dashboard_backend.pid"
    if [ -f "$BACKEND_PID_FILE" ] && kill -0 "$(cat "$BACKEND_PID_FILE")" 2>/dev/null; then
      echo -e "  ${G}●${E} Dashboard backend   running  (PID $(cat "$BACKEND_PID_FILE"))"
    elif lsof -ti tcp:8000 >/dev/null 2>&1; then
      echo -e "  ${G}●${E} Dashboard backend   running  (port 8000, PID unknown)"
    else
      echo -e "  ${R}○${E} Dashboard backend   stopped"
    fi

    # Frontend
    FRONTEND_PID_FILE="$ROOT/.pids/dashboard_frontend.pid"
    if [ -f "$FRONTEND_PID_FILE" ] && kill -0 "$(cat "$FRONTEND_PID_FILE")" 2>/dev/null; then
      echo -e "  ${G}●${E} Dashboard frontend  running  (PID $(cat "$FRONTEND_PID_FILE"))"
    elif pgrep -f "vite" >/dev/null 2>&1; then
      echo -e "  ${G}●${E} Dashboard frontend  running  (Vite)"
    else
      echo -e "  ${R}○${E} Dashboard frontend  stopped"
    fi

    # Paper trade bot (stale if live_positions.json >5min old)
    if [ -f "$ROOT/data/live_positions.json" ]; then
      AGE=$(( $(date +%s) - $(date -r "$ROOT/data/live_positions.json" +%s 2>/dev/null || echo 0) ))
      if [ "$AGE" -lt 300 ]; then
        echo -e "  ${G}●${E} Paper trade bot     running  (last update ${AGE}s ago)"
      else
        echo -e "  ${Y}○${E} Paper trade bot     inactive (last update $((AGE/60))m ago)"
      fi
    else
      echo -e "  ${R}○${E} Paper trade bot     never run"
    fi

    echo ""

    # Token status
    echo -e "  ${B}Token:${E}"
    "$PYTHON" "$ROOT/scripts/check_token.py" 2>/dev/null | head -4 | sed 's/^/    /' || \
      echo -e "    ${R}Unable to check token${E}"

    echo ""

    # Quick equity summary
    if [ -f "$ROOT/data/equity_curve.jsonl" ]; then
      echo -e "  ${B}Last equity snapshot:${E}"
      tail -1 "$ROOT/data/equity_curve.jsonl" 2>/dev/null | \
        "$PYTHON" -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(f'    ₹{d[\"equity\"]:,.0f}  (realised: ₹{d[\"realised\"]:+,.0f}  unrealised: ₹{d[\"unrealised\"]:+,.0f})')
except: pass
" || true
    fi

    echo ""
    ;;

  logs)
    LOG="$ROOT/logs/dashboard_backend.log"
    N=50
    ERRORS_ONLY=false
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --errors|-e) ERRORS_ONLY=true ;;
        --n|-n) shift; N="$1" ;;
        *) LOG="$1" ;;
      esac
      shift
    done
    if [ ! -f "$LOG" ]; then
      echo -e "${Y}Log file not found: $LOG${E}"
      echo "Available logs:"
      ls "$ROOT/logs/"*.log "$ROOT/logs/"*.jsonl 2>/dev/null | sed 's/^/  /' || echo "  (none)"
      exit 0
    fi
    echo -e "${DIM}Tailing $LOG (last $N lines, Ctrl+C to stop)${E}"
    if $ERRORS_ONLY; then
      tail -f "$LOG" | grep -i --line-buffered "error\|exception\|traceback\|critical"
    else
      tail -n "$N" -f "$LOG"
    fi
    ;;

  # ── Trading ─────────────────────────────────────────────────────────────────

  paper)
    _require_token
    cd "$ROOT"
    exec "$PYTHON" scripts/paper_trade.py "$@"
    ;;

  signals|scan)
    _require_token
    cd "$ROOT"
    exec "$PYTHON" scripts/live_signals.py "$@"
    ;;

  backtest|bt)
    _require_token
    cd "$ROOT"
    exec "$PYTHON" scripts/backtest_runner.py "$@"
    ;;

  market|watch)
    _require_token
    cd "$ROOT"
    exec "$PYTHON" scripts/market_watch.py "$@"
    ;;

  # ── Models & Config ─────────────────────────────────────────────────────────

  train)
    _require_token
    cd "$ROOT"
    exec "$PYTHON" scripts/train_ml.py "$@"
    ;;

  tune|tune-weights)
    _require_token
    cd "$ROOT"
    exec "$PYTHON" scripts/tune_weights.py "$@"
    ;;

  # ── Reports & Tools ─────────────────────────────────────────────────────────

  health)
    cd "$ROOT"
    exec "$PYTHON" scripts/health.py "$@"
    ;;

  report|strategy-report)
    cd "$ROOT"
    exec "$PYTHON" scripts/strategy_report.py "$@"
    ;;

  journal)
    cd "$ROOT"
    exec "$PYTHON" scripts/trade_journal.py "$@"
    ;;

  token)
    cd "$ROOT"
    if [[ "${1:-}" == "--refresh" || "${1:-}" == "--force" ]]; then
      exec "$PYTHON" scripts/upstox_login.py --force
    else
      exec "$PYTHON" scripts/check_token.py "$@"
    fi
    ;;

  # ── Help / fallthrough ───────────────────────────────────────────────────────

  help|-h|--help)
    _help
    ;;

  *)
    echo -e "${R}Unknown command: $CMD${E}"
    echo "Run './loony.sh help' for usage."
    exit 1
    ;;

esac
