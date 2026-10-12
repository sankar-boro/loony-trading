#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# auto_login.sh — Daily Upstox token renewal for headless / cron use
#
# Intended crontab entry (08:45 AM IST = 03:15 UTC, weekdays only):
#   15 3 * * 1-5 /home/sankar/ai_projects/loony-trading/scripts/auto_login.sh \
#                >> /home/sankar/ai_projects/loony-trading/logs/auto_login.log 2>&1
#
# The script:
#   1. Activates the project virtualenv (edit VENV_PATH below)
#   2. Runs upstox_login.py in --paste-token mode (prompts in terminal) OR
#      --force for fully automated OAuth if redirect is reachable
#   3. Restarts the bot if managed by systemd (edit SERVICE_NAME below)
#
# Usage:
#   bash scripts/auto_login.sh              # interactive (paste token)
#   bash scripts/auto_login.sh --force      # trigger full OAuth browser flow
#   bash scripts/auto_login.sh --check-only # just report token age, no renewal
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Configuration — edit these ────────────────────────────────────────────────
BOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PATH="${BOT_DIR}/.venv"              # virtualenv directory (or "system" to skip)
SERVICE_NAME=""                           # systemd service to restart after login, e.g. "loony-trading"
TOKEN_FILE="${BOT_DIR}/data/upstox_token.json"
LOG_FILE="${BOT_DIR}/logs/auto_login.log"
WARN_HOURS_LEFT=3                         # warn when the token expires within this many hours
# ─────────────────────────────────────────────────────────────────────────────

mkdir -p "${BOT_DIR}/logs"
NOW=$(date '+%Y-%m-%d %H:%M:%S')
echo ""
echo "════════════════════════════════════════"
echo "  Loony Trading — auto_login.sh"
echo "  ${NOW}"
echo "════════════════════════════════════════"

# ── Activate virtualenv ───────────────────────────────────────────────────────
if [[ "${VENV_PATH}" != "system" && -f "${VENV_PATH}/bin/activate" ]]; then
    # shellcheck source=/dev/null
    source "${VENV_PATH}/bin/activate"
    echo "  venv: ${VENV_PATH}"
else
    echo "  venv: system python (${VENV_PATH} not found)"
fi

PYTHON=$(command -v python3 || command -v python)
echo "  python: $("${PYTHON}" --version 2>&1)"

# ── Check current token age ───────────────────────────────────────────────────
check_token_age() {
    if [[ ! -f "${TOKEN_FILE}" ]]; then
        echo "  token: NOT FOUND (${TOKEN_FILE})"
        return 1
    fi

    OBTAINED_AT=$(python3 -c "
import json, sys
try:
    d = json.load(open('${TOKEN_FILE}'))
    print(d.get('obtained_at', 0))
except Exception as e:
    print(0)
")
    AGE_H=$(python3 -c "
import time
obtained = float('${OBTAINED_AT}')
if obtained == 0:
    print(-1)
else:
    print(round((time.time() - obtained) / 3600, 1))
")

    if [[ "${AGE_H}" == "-1" ]]; then
        echo "  token: found but obtained_at missing — treating as expired"
        return 1
    fi

    echo "  token: age = ${AGE_H}h"

    # Upstox tokens die at 03:30 IST the morning after issue, not N hours
    # after it — use the same rule as the Python code (data_engine/upstox/auth.py).
    # Return non-zero if expired.
    (cd "${BOT_DIR}" && python3 -c "
import sys
from data_engine.upstox.auth import token_hours_left
left = token_hours_left(float('${OBTAINED_AT}'))
if left <= 0:
    print('  token: EXPIRED (03:30 IST)')
    sys.exit(1)
elif left <= ${WARN_HOURS_LEFT}:
    print(f'  token: WARNING — expires in {left:.1f}h')
    sys.exit(0)
else:
    print(f'  token: OK — {left:.1f}h remaining')
    sys.exit(0)
")
}

# ── Parse arguments ───────────────────────────────────────────────────────────
MODE="paste"   # default: paste-token mode (non-interactive headless)
for arg in "$@"; do
    case "${arg}" in
        --force)       MODE="force" ;;
        --check-only)  MODE="check" ;;
        --paste-token) MODE="paste" ;;
    esac
done

if [[ "${MODE}" == "check" ]]; then
    check_token_age
    exit $?
fi

# Only renew if the token has expired (check_token_age fails) or --force
if [[ "${MODE}" != "force" ]] && check_token_age; then
    echo "  Token still valid — skipping renewal."
    exit 0
fi

# ── Run login ─────────────────────────────────────────────────────────────────
echo ""
echo "  Renewing token (mode: ${MODE})..."
cd "${BOT_DIR}"

case "${MODE}" in
    force)
        "${PYTHON}" scripts/upstox_login.py --force
        ;;
    paste)
        # --sandbox is wrong here; we want production token via paste
        "${PYTHON}" scripts/upstox_login.py --paste-token
        ;;
esac

LOGIN_EXIT=$?
if [[ "${LOGIN_EXIT}" -ne 0 ]]; then
    echo "  ERROR: upstox_login.py exited with code ${LOGIN_EXIT}"
    exit "${LOGIN_EXIT}"
fi

echo ""
echo "  Token renewed successfully."

# ── Restart bot service ───────────────────────────────────────────────────────
if [[ -n "${SERVICE_NAME}" ]]; then
    if command -v systemctl &>/dev/null && systemctl is-active --quiet "${SERVICE_NAME}" 2>/dev/null; then
        echo "  Restarting service: ${SERVICE_NAME}"
        systemctl restart "${SERVICE_NAME}"
        echo "  Service restarted."
    else
        echo "  Service '${SERVICE_NAME}' not found or not running — skipping restart."
    fi
fi

echo ""
echo "  Done: $(date '+%Y-%m-%d %H:%M:%S')"
echo "════════════════════════════════════════"
