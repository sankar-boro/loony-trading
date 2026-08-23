#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# scripts/upstox_login.sh — Upstox login (bash port of upstox_login.py)
#
# Handles three authentication methods:
#
# Method 1 — Standard OAuth 2.0 (default):
#   Browser login with mobile / PIN / TOTP → local callback → ~24h token.
#   Also saves the extended_token (1-year read-only) if returned.
#
# Method 2 — Access Token Request API (--token-request):
#   No browser, no TOTP. Upstox sends a WhatsApp + in-app push notification.
#   You tap Approve on your phone → script receives the token via a local
#   webhook.
#   Pre-requisite: configure Notifier URL in your app settings to
#     http://localhost:<PORT>/callback
#
# Method 3 — Sandbox token (--sandbox):
#   Sandbox tokens are portal-generated. No OAuth needed.
#   Steps: account.upstox.com/developer/apps#sandbox → Generate → paste below.
#
# Requires: bash, curl, jq, nc (OpenBSD netcat), base64, date, awk, sed
#
# Usage:
#   bash scripts/upstox_login.sh                  # Method 1: OAuth
#   bash scripts/upstox_login.sh --token-request   # Method 2: WhatsApp/in-app
#   bash scripts/upstox_login.sh --sandbox         # Method 3: Sandbox token
#   bash scripts/upstox_login.sh --force           # force re-auth
#   bash scripts/upstox_login.sh --no-browser      # print URL, paste manually
#   bash scripts/upstox_login.sh --env .env        # specify env file
#   bash scripts/upstox_login.sh --port 3561       # callback/webhook port
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for bin in curl jq nc base64 date awk sed; do
  command -v "$bin" >/dev/null 2>&1 || { echo "[ERROR] required command not found: $bin" >&2; exit 1; }
done

banner() {
  echo
  echo "============================================================"
  echo "  $1"
  echo "============================================================"
}

usage() {
  sed -n '2,26p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

# ── args ─────────────────────────────────────────────────────────────────────
ENV_FILE=".env"
FORCE=false
NO_BROWSER=false
TOKEN_REQUEST=false
SANDBOX=false
PORT=3561

while [[ $# -gt 0 ]]; do
  case "$1" in
    --force)         FORCE=true; shift ;;
    --env)            ENV_FILE="$2"; shift 2 ;;
    --port)            PORT="$2"; shift 2 ;;
    --no-browser)     NO_BROWSER=true; shift ;;
    --token-request)  TOKEN_REQUEST=true; shift ;;
    --sandbox)        SANDBOX=true; shift ;;
    -h|--help)        usage; exit 0 ;;
    *) echo "[ERROR] unknown argument: $1" >&2; usage; exit 1 ;;
  esac
done

# ── env loading ────────────────────────────────────────────────────────────
load_env() {
  local env_path="$ROOT/$ENV_FILE"
  [[ -f "$env_path" ]] || return 0
  local line key val
  while IFS= read -r line; do
    [[ -z "$line" || "$line" == \#* || "$line" != *=* ]] && continue
    key="${line%%=*}"
    val="${line#*=}"
    key="$(echo -n "$key" | xargs)"
    val="${val%\"}"; val="${val#\"}"
    val="${val%\'}"; val="${val#\'}"
    if [[ -n "$key" && -z "${!key:-}" ]]; then
      export "$key=$val"
    fi
  done < "$env_path"
}

require_env() {
  local key="$1" label="$2" val="${!1:-}"
  if [[ -z "$val" ]]; then
    read -r -p "  Enter ${label} (${key}): " val
    if [[ -z "$val" ]]; then
      echo "[ERROR] ${label} is required." >&2
      exit 1
    fi
  fi
  printf '%s' "$val"
}

load_env

# ── token file helpers ───────────────────────────────────────────────────────
load_existing_token() {
  # usage: load_existing_token <file>; sets ACCESS_TOKEN / TOKEN_AGE_H
  local token_file="$1"
  ACCESS_TOKEN=""; TOKEN_AGE_H=""
  [[ -f "$token_file" ]] || return 1
  local obtained_at
  obtained_at=$(jq -r '.obtained_at // 0' "$token_file" 2>/dev/null) || return 1
  [[ "$obtained_at" == "null" || -z "$obtained_at" ]] && obtained_at=0
  local age_h is_fresh
  age_h=$(awk -v now="$(date +%s)" -v obtained="$obtained_at" 'BEGIN{printf "%.1f", (now-obtained)/3600}')
  is_fresh=$(awk -v a="$age_h" 'BEGIN{print (a<23)?1:0}')
  [[ "$is_fresh" == "1" ]] || return 1
  ACCESS_TOKEN=$(jq -r '.access_token // empty' "$token_file")
  TOKEN_AGE_H="$age_h"
  [[ -n "$ACCESS_TOKEN" ]] || return 1
  return 0
}

save_token() {
  # usage: save_token <file> <json>
  local token_file="$1" json="$2"
  mkdir -p "$(dirname "$token_file")"
  echo "$json" | jq --argjson t "$(date +%s)" '. + {obtained_at: $t}' > "$token_file"
  echo "  Token saved → ${token_file}"
}

update_env_key() {
  local file="$1" key="$2" value="$3"
  [[ -f "$file" ]] || return 0
  local esc_value
  esc_value=$(printf '%s' "$value" | sed -e 's/[&/\]/\\&/g')
  if grep -q "^${key}=" "$file"; then
    sed -i "s|^${key}=.*|${key}=${esc_value}|" "$file"
  else
    printf '%s=%s\n' "$key" "$value" >> "$file"
  fi
  echo "  .env updated: ${key} written"
}

# ── OAuth / API helpers ───────────────────────────────────────────────────────
build_auth_url() {
  local api_key="$1" redirect_uri="$2" enc_redirect
  enc_redirect=$(jq -rn --arg v "$redirect_uri" '$v|@uri')
  echo "https://api.upstox.com/v2/login/authorization/dialog?response_type=code&client_id=${api_key}&redirect_uri=${enc_redirect}"
}

exchange_code_for_token() {
  local code="$1" api_key="$2" api_secret="$3" redirect_uri="$4"
  local resp http_code body
  resp=$(curl -s -w '\n%{http_code}' -X POST "https://api.upstox.com/v2/login/authorization/token" \
    -H "Content-Type: application/x-www-form-urlencoded" -H "Accept: application/json" \
    --data-urlencode "code=${code}" \
    --data-urlencode "client_id=${api_key}" \
    --data-urlencode "client_secret=${api_secret}" \
    --data-urlencode "redirect_uri=${redirect_uri}" \
    --data-urlencode "grant_type=authorization_code")
  http_code=$(echo "$resp" | tail -n1)
  body=$(echo "$resp" | sed '$d')
  if [[ "$http_code" != "200" ]]; then
    echo "" >&2
    echo "[ERROR] Token exchange failed (${http_code}):" >&2
    echo "  ${body}" >&2
    exit 1
  fi
  printf '%s' "$body"
}

# Captures one inbound HTTP request via nc, without depending on any
# flags beyond `-l` + a positional port — that combination is the one
# thing every nc variant (OpenBSD, GNU netcat-traditional, BSD/macOS,
# ncat) agrees on. `-p`/`-q` support varies enough between them that
# relying on either silently breaks the listener on some machines: nc
# exits immediately, the port never gets bound, and the browser's
# redirect just hangs with nothing to show for it.
#
# Trade-off: since we don't feed a response back through the same nc
# process, the browser tab is left hanging once we have what we need
# (we kill nc as soon as the code/body is captured) — cosmetic only,
# the terminal is the source of truth. Prints a heartbeat every ~15s so
# a real stall is distinguishable from normal waiting.
_capture_http_request() {
  local port="$1" timeout="$2" capture_file="$3"
  : > "$capture_file"
  ( exec nc -l "$port" > "$capture_file" 2>/dev/null ) &
  local nc_pid=$!
  local deadline=$(( $(date +%s) + timeout ))
  local last_heartbeat=$(date +%s)
  while [[ $(date +%s) -lt $deadline ]]; do
    if ! kill -0 "$nc_pid" 2>/dev/null; then
      # nc exited on its own — either it captured a request (success:
      # fall through and let the caller inspect the file) or it failed
      # to bind (capture_file stays empty and the caller reports that).
      break
    fi
    if [[ -s "$capture_file" ]]; then
      # Give the client a beat to finish writing, then stop the listener.
      sleep 0.2
      break
    fi
    local now=$(date +%s)
    if (( now - last_heartbeat >= 15 )); then
      echo "  ... still waiting ($(( now - (deadline - timeout) ))s elapsed)" >&2
      last_heartbeat=$now
    fi
    sleep 0.3
  done
  # SIGKILL, fire-and-forget — never `wait` on it. If the kill doesn't land
  # (sandboxing, a stuck syscall, whatever), a blocking wait here would hang
  # this function forever regardless of whether we already have what we
  # came for. Worst case on a real machine: nc lingers a moment before the
  # OS reaps it, which does not block anything downstream.
  kill -9 "$nc_pid" 2>/dev/null
  disown "$nc_pid" 2>/dev/null
}

wait_for_callback() {
  local port="$1" timeout="${2:-300}"
  echo "  Listening for OAuth callback on http://localhost:${port}/callback ..." >&2
  local capture_file
  capture_file=$(mktemp)
  _capture_http_request "$port" "$timeout" "$capture_file"
  if [[ ! -s "$capture_file" ]]; then
    rm -f "$capture_file"
    return 1
  fi
  local first_line
  first_line=$(head -n1 "$capture_file" | tr -d '\r')
  rm -f "$capture_file"
  if [[ "$first_line" =~ code=([^&[:space:]]+) ]]; then
    printf '%s' "${BASH_REMATCH[1]}"
    return 0
  fi
  return 1
}

# Method-2 webhook: same capture helper, but the payload we care about is
# the POST body (JSON), which arrives after the blank line separating
# headers from body.
wait_for_webhook() {
  local port="$1" timeout="${2:-300}"
  local capture_file
  capture_file=$(mktemp)
  _capture_http_request "$port" "$timeout" "$capture_file"
  if [[ ! -s "$capture_file" ]]; then
    rm -f "$capture_file"
    return 1
  fi
  local body
  body=$(awk 'f{print} /^\r?$/{f=1}' "$capture_file")
  rm -f "$capture_file"
  if [[ -n "$body" ]] && echo "$body" | jq -e '.access_token' >/dev/null 2>&1; then
    printf '%s' "$body"
    return 0
  fi
  return 1
}

verify_token() {
  local token="$1"
  curl -s -G "https://api.upstox.com/v2/market-quote/ltp" \
    --data-urlencode "instrument_key=NSE_INDEX|Nifty 50" \
    -H "Authorization: Bearer ${token}" -H "Accept: application/json" \
    | jq -r 'if .status == "success" then (.data // {}) else empty end'
}

get_profile() {
  local token="$1"
  curl -s "https://api.upstox.com/v2/user/profile" \
    -H "Authorization: Bearer ${token}" -H "Accept: application/json" \
    | jq -r 'if .status == "success" then (.data // {}) else empty end'
}

decode_jwt_expiry() {
  local token="$1" payload_b64 rem pad payload exp sub
  payload_b64=$(echo "$token" | cut -d. -f2)
  [[ -z "$payload_b64" || "$payload_b64" == "$token" ]] && return 0
  rem=$(( ${#payload_b64} % 4 )); pad=""
  [[ $rem -eq 2 ]] && pad="=="
  [[ $rem -eq 3 ]] && pad="="
  payload=$(printf '%s%s' "$payload_b64" "$pad" | tr '_-' '/+' | base64 -d 2>/dev/null)
  [[ -z "$payload" ]] && return 0
  exp=$(echo "$payload" | jq -r '.exp // empty' 2>/dev/null)
  sub=$(echo "$payload" | jq -r '.sub // empty' 2>/dev/null)
  if [[ -n "$exp" ]]; then
    local exp_str remaining
    exp_str=$(date -d "@${exp}" '+%Y-%m-%d %H:%M' 2>/dev/null || date -r "${exp}" '+%Y-%m-%d %H:%M' 2>/dev/null)
    remaining=$(awk -v e="$exp" -v n="$(date +%s)" 'BEGIN{printf "%.1f", (e-n)/3600}')
    echo "sub=${sub}  exp=${exp_str}  (${remaining}h remaining)"
  elif [[ -n "$sub" ]]; then
    echo "sub=${sub}"
  fi
}

open_browser() {
  local url="$1"
  if command -v xdg-open >/dev/null 2>&1; then xdg-open "$url" >/dev/null 2>&1 && return 0
  elif command -v open >/dev/null 2>&1; then open "$url" >/dev/null 2>&1 && return 0
  fi
  return 1
}

# ══════════════════════════════════════════════════════════════════════════
# Method 3: Sandbox token (portal-generated, paste it in)
# ══════════════════════════════════════════════════════════════════════════
run_sandbox() {
  banner "Upstox Sandbox Token"
  local sb_file="${ROOT}/data/upstox_sandbox_token.json"
  if [[ "${FORCE}" != true && -f "$sb_file" ]]; then
    local age_h tok
    age_h=$(awk -v now="$(date +%s)" -v obtained="$(jq -r '.obtained_at // 0' "$sb_file")" 'BEGIN{printf "%.1f", (now-obtained)/3600}')
    tok=$(jq -r '.access_token // empty' "$sb_file")
    if [[ -n "$tok" ]] && awk -v a="$age_h" 'BEGIN{exit !(a<720)}'; then
      echo
      echo "[OK] Found valid sandbox token (age: ${age_h}h)"
      echo "     Token: ${tok:0:40}..."
      echo
      echo "     Use --force to replace it."
      return 0
    fi
  fi
  echo
  echo "  Sandbox tokens are generated in the Upstox developer portal."
  echo "  No browser or OAuth flow needed."
  echo
  echo "  Steps:"
  echo "    1. Open: https://account.upstox.com/developer/apps#sandbox"
  echo "    2. Open your sandbox app → click  Generate"
  echo "    3. Copy the 30-day token and paste below"
  echo
  local pasted
  read -r -s -p "  Paste sandbox token (input hidden): " pasted
  echo
  if [[ -z "$pasted" ]]; then
    echo "[ERROR] No token provided." >&2
    exit 1
  fi
  save_token "$sb_file" "$(jq -n --arg t "$pasted" '{access_token:$t, token_type:"Bearer"}')"
  update_env_key "${ROOT}/${ENV_FILE}" "UPSTOX_SANDBOX_TOKEN" "$pasted"
  echo
  echo "  Sandbox ready. Run order tests:"
  echo "    python scripts/order.py --sandbox"
  echo "    python scripts/test_upstox.py --sandbox"
}

# ══════════════════════════════════════════════════════════════════════════
# Method 2: Access Token Request API (WhatsApp / in-app notification)
# ══════════════════════════════════════════════════════════════════════════
run_token_request() {
  banner "Upstox Login — Token Request (Method 2)"
  local token_file="${ROOT}/data/upstox_token.json"
  if [[ "${FORCE}" != true ]] && load_existing_token "$token_file"; then
    echo
    echo "[OK] Found valid token (age: ${TOKEN_AGE_H}h). Use --force to re-auth."
    echo
    return 0
  fi

  echo
  echo "[Step 1/3] Loading credentials..."
  local api_key api_secret
  api_key=$(require_env UPSTOX_API_KEY "Upstox API Key")
  api_secret=$(require_env UPSTOX_API_SECRET "Upstox API Secret")
  echo "  API Key: ${api_key:0:8}..."
  echo
  echo "  Pre-requisite: your app's Notifier URL must be set to:"
  echo "    http://localhost:${PORT}/callback"
  echo "  Configure at: account.upstox.com/developer/apps → your app → Settings"
  read -r -p "
  Press Enter once Notifier URL is configured... "

  echo
  echo "[Step 2/3] Sending token request (triggers WhatsApp + in-app push)..."
  local tr_resp tr_code tr_body
  tr_resp=$(curl -s -w '\n%{http_code}' -X POST \
    "https://api.upstox.com/v3/login/auth/token/request/${api_key}" \
    -H "Content-Type: application/json" -H "Accept: application/json" \
    -d "$(jq -n --arg s "$api_secret" '{client_secret:$s}')")
  tr_code=$(echo "$tr_resp" | tail -n1)
  tr_body=$(echo "$tr_resp" | sed '$d')
  if [[ "$tr_code" != "200" ]]; then
    echo
    echo "[ERROR] Token request failed (HTTP ${tr_code}):" >&2
    echo "  ${tr_body:0:300}" >&2
    echo
    echo "  Common errors:"
    echo "    UDAPI100069 — wrong API key / secret"
    echo "    UDAPI1123   — Notifier URL not configured in app settings"
    exit 1
  fi
  echo
  echo "[OK] Token request sent!"
  echo "  Notifier URL: $(echo "$tr_body" | jq -r '.data.notifier_url // "?"')"

  echo
  echo "  Check your phone:"
  echo "    → WhatsApp message from Upstox"
  echo "    → OR in-app notification in the Upstox app"
  echo "    → Tap  Approve  to generate the token"
  echo
  echo "[Step 3/3] Waiting for webhook callback (up to 5 min)..."

  local received
  if ! received=$(wait_for_webhook "$PORT" 300); then
    echo
    echo "[ERROR] No approval received in 5 minutes." >&2
    echo "  Check the Notifier URL in your app settings." >&2
    exit 1
  fi

  local access_token
  access_token=$(echo "$received" | jq -r '.access_token')
  save_token "$token_file" "$received"
  update_env_key "${ROOT}/${ENV_FILE}" "UPSTOX_ACCESS_TOKEN" "$access_token"

  banner "Authentication Successful — Token Request"
  echo
  echo "  Access token: ${access_token:0:40}..."
  local jwt_info
  jwt_info=$(decode_jwt_expiry "$access_token")
  [[ -n "$jwt_info" ]] && echo "  JWT info:     ${jwt_info}"
  local ltp_data nifty
  ltp_data=$(verify_token "$access_token")
  if [[ -n "$ltp_data" && "$ltp_data" != "{}" ]]; then
    nifty=$(echo "$ltp_data" | jq -r '(."NSE_INDEX:Nifty 50".last_price) // "N/A"')
    echo "  Nifty 50 LTP: ₹${nifty}"
  fi
  echo
  echo "  Run tests:  python scripts/test_upstox.py"
}

# ══════════════════════════════════════════════════════════════════════════
# Method 1: Standard OAuth 2.0
# ══════════════════════════════════════════════════════════════════════════
run_oauth() {
  banner "Upstox Login — OAuth (Method 1)"
  local token_file="${ROOT}/data/upstox_token.json"

  if [[ "${FORCE}" != true ]] && load_existing_token "$token_file"; then
    echo
    echo "[OK] Found valid token (age: ${TOKEN_AGE_H}h)"
    echo "     Token: ${ACCESS_TOKEN:0:40}..."
    local ltp_data nifty
    ltp_data=$(verify_token "$ACCESS_TOKEN")
    if [[ -n "$ltp_data" && "$ltp_data" != "{}" ]]; then
      nifty=$(echo "$ltp_data" | jq -r '(."NSE_INDEX:Nifty 50".last_price) // "N/A"')
      echo "     Nifty 50 LTP: ₹${nifty}"
      echo
      echo "[OK] Token is working. No re-authentication needed."
      echo "     Use --force to re-authenticate anyway."
      echo
      return 0
    else
      echo "     Warning: token exists but market data call failed."
      echo "     Proceeding with re-authentication..."
      echo
    fi
  fi

  echo
  echo "[Step 1/3] Loading API credentials..."
  local api_key api_secret redirect_uri
  api_key=$(require_env UPSTOX_API_KEY "Upstox API Key")
  api_secret=$(require_env UPSTOX_API_SECRET "Upstox API Secret")
  redirect_uri="${UPSTOX_REDIRECT_URI:-http://localhost:${PORT}/callback}"

  local callback_port
  callback_port=$(echo "$redirect_uri" | sed -n 's#.*://[^:/]*:\([0-9]\+\).*#\1#p')
  [[ -z "$callback_port" ]] && callback_port="$PORT"

  echo "  API Key:      ${api_key:0:8}..."
  echo "  Redirect URI: ${redirect_uri}"

  local auth_url
  auth_url=$(build_auth_url "$api_key" "$redirect_uri")

  echo
  echo "[Step 2/3] Getting authorization code..."
  echo
  echo "  Upstox requires you to log in via browser."
  echo "  You will need your: mobile number, PIN/password, and TOTP."
  echo
  echo "  TOTP tip: if you want to generate your TOTP code here instead of"
  echo "  using your phone app, run in another terminal:"
  echo "    python scripts/generate_totp.py --secret YOUR_TOTP_SECRET"
  echo

  local code=""
  if [[ "${NO_BROWSER}" == true ]]; then
    echo "  Auth URL (open this in your browser):"
    echo
    echo "  ${auth_url}"
    echo
    echo "  After logging in, you will be redirected to:"
    echo "  ${redirect_uri}?code=XXXXXX"
    local raw
    read -r -p "  Paste the full redirect URL (or just the code): " raw
    if [[ "$raw" == *"code="* ]]; then
      code=$(echo "$raw" | sed -n 's/.*code=\([^&[:space:]]*\).*/\1/p')
    else
      code="$raw"
    fi
  else
    echo "  Starting local callback server..."
    echo "  Opening browser → ${auth_url:0:70}..."
    echo
    if ! open_browser "$auth_url"; then
      echo "  [!] Could not open browser automatically."
      echo "  Open manually: ${auth_url}"
    fi
    code=$(wait_for_callback "$callback_port" 300) || code=""
    if [[ -z "$code" ]]; then
      echo
      echo "  [!] Did not receive callback automatically."
      echo
      echo "  Auth URL: ${auth_url}"
      echo
      local raw
      read -r -p "  After logging in, paste the full redirect URL here: " raw
      if [[ "$raw" == *"code="* ]]; then
        code=$(echo "$raw" | sed -n 's/.*code=\([^&[:space:]]*\).*/\1/p')
      else
        code="$raw"
      fi
    fi
  fi

  if [[ -z "$code" ]]; then
    echo
    echo "[ERROR] No authorization code received. Aborting." >&2
    exit 1
  fi

  echo
  echo "  Auth code received: ${code:0:12}..."

  echo
  echo "[Step 3/3] Exchanging code for access token..."
  local token_data token
  token_data=$(exchange_code_for_token "$code" "$api_key" "$api_secret" "$redirect_uri")
  token=$(echo "$token_data" | jq -r '.access_token // empty')

  if [[ -z "$token" ]]; then
    echo "[ERROR] No access_token in response:" >&2
    echo "$token_data" | jq . >&2
    exit 1
  fi

  save_token "$token_file" "$token_data"

  local extended_token
  extended_token=$(echo "$token_data" | jq -r '.extended_token // empty')
  if [[ -n "$extended_token" ]]; then
    local ext_file="${ROOT}/data/upstox_extended_token.json"
    save_token "$ext_file" "$(jq -n --arg t "$extended_token" '{access_token:$t, token_type:"extended"}')"
    update_env_key "${ROOT}/${ENV_FILE}" "UPSTOX_EXTENDED_TOKEN" "$extended_token"
  fi

  banner "Authentication Successful"
  echo
  echo "  Access token:   ${token:0:40}..."
  local jwt_info
  jwt_info=$(decode_jwt_expiry "$token")
  if [[ -n "$jwt_info" ]]; then
    echo "  JWT info:       ${jwt_info}"
  else
    echo "  Expires:        ~23 hours from now"
  fi
  echo "  Saved to:       ${token_file}"
  if [[ -n "$extended_token" ]]; then
    echo "  Extended token: ${extended_token:0:40}...  (1-year read-only)"
    echo "  Saved to:       ${ROOT}/data/upstox_extended_token.json"
  fi

  echo
  echo "  Verifying token against Upstox API..."
  local ltp_data nifty
  ltp_data=$(verify_token "$token")
  if [[ -n "$ltp_data" && "$ltp_data" != "{}" ]]; then
    nifty=$(echo "$ltp_data" | jq -r '(."NSE_INDEX:Nifty 50".last_price) // "N/A"')
    echo "  [OK] Nifty 50 LTP: ₹${nifty}"
  else
    echo "  [!] Market data check skipped (market may be closed or token is analytics-only)"
  fi

  local profile
  profile=$(get_profile "$token")
  if [[ -n "$profile" && "$profile" != "{}" ]]; then
    echo
    echo "  Account: $(echo "$profile" | jq -r '.user_name // "N/A"') ($(echo "$profile" | jq -r '.email // "N/A"'))"
    echo "  User ID: $(echo "$profile" | jq -r '.user_id // "N/A"')"
  fi

  echo
  echo "  Next steps:"
  echo "    Run tests:       python scripts/test_upstox.py"
  echo "    Start paper bot: python main.py --mode paper"
  echo

  update_env_key "${ROOT}/${ENV_FILE}" "UPSTOX_ACCESS_TOKEN" "$token"
}

# ── dispatch ───────────────────────────────────────────────────────────────
if [[ "${SANDBOX}" == true ]]; then
  run_sandbox
elif [[ "${TOKEN_REQUEST}" == true ]]; then
  run_token_request
else
  run_oauth
fi
