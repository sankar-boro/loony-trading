#!/usr/bin/env python
"""
Upstox Login Script
===================

Handles three authentication methods:

Method 1 — Standard OAuth 2.0 (default):
  Browser login with mobile / PIN / TOTP → local callback → 24h token.
  Also saves the extended_token (1-year read-only) if returned.

Method 2 — Access Token Request API (--token-request):
  No browser, no TOTP. Upstox sends a WhatsApp + in-app push notification.
  You tap Approve on your phone → script receives token via local webhook.
  Pre-requisite: configure Notifier URL in your app settings to
    http://localhost:<PORT>/callback

Method 3 — Sandbox token (--sandbox):
  Sandbox tokens are portal-generated. No OAuth needed.
  Steps: account.upstox.com/developer/apps#sandbox → Generate → paste below.

Usage:
    python scripts/upstox_login.py                   # Method 1: OAuth
    python scripts/upstox_login.py --token-request   # Method 2: WhatsApp/in-app
    python scripts/upstox_login.py --sandbox         # Method 3: Sandbox token
    python scripts/upstox_login.py --force           # force re-auth
    python scripts/upstox_login.py --no-browser      # print URL, paste manually
    python scripts/upstox_login.py --env .env        # specify env file
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs

# ── project root on path ──────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load_env(env_file: str = ".env") -> None:
    """Load .env file into os.environ."""
    env_path = ROOT / env_file
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


def _require_env(key: str, label: str) -> str:
    val = os.environ.get(key, "").strip()
    if not val:
        val = input(f"  Enter {label} ({key}): ").strip()
        if not val:
            print(f"[ERROR] {label} is required.")
            sys.exit(1)
    return val


def _banner(text: str) -> None:
    print("\n" + "=" * 60)
    print(f"  {text}")
    print("=" * 60)


# ── Token helpers ─────────────────────────────────────────────────────────────

def load_existing_token(token_file: Path) -> tuple[str | None, dict]:
    """Returns (token_string, token_data) if valid, else (None, {})."""
    if not token_file.exists():
        return None, {}
    try:
        with open(token_file) as f:
            data = json.load(f)
        age_hours = (time.time() - data.get("obtained_at", 0)) / 3600
        if age_hours < 23:
            return data.get("access_token"), data
    except Exception:
        pass
    return None, {}


def save_token(token_file: Path, data: dict) -> None:
    token_file.parent.mkdir(parents=True, exist_ok=True)
    with open(token_file, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Token saved → {token_file}")


# ── OAuth flow ────────────────────────────────────────────────────────────────

def build_auth_url(api_key: str, redirect_uri: str) -> str:
    params = {
        "response_type": "code",
        "client_id": api_key,
        "redirect_uri": redirect_uri,
    }
    return f"https://api.upstox.com/v2/login/authorization/dialog?{urlencode(params)}"


def exchange_code_for_token(
    code: str,
    api_key: str,
    api_secret: str,
    redirect_uri: str,
) -> dict:
    """POST authorization code → returns full token response dict."""
    import requests

    resp = requests.post(
        "https://api.upstox.com/v2/login/authorization/token",
        data={
            "code": code,
            "client_id": api_key,
            "client_secret": api_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        timeout=15,
    )
    if resp.status_code != 200:
        print(f"\n[ERROR] Token exchange failed ({resp.status_code}):")
        print(f"  {resp.text}")
        sys.exit(1)
    data = resp.json()
    data["obtained_at"] = time.time()
    return data


# ── Local callback server ─────────────────────────────────────────────────────

class _CallbackHandler(BaseHTTPRequestHandler):
    captured_code: str | None = None

    def do_GET(self):
        params = parse_qs(urlparse(self.path).query)
        code = params.get("code", [None])[0]
        error = params.get("error", [None])[0]

        if code:
            _CallbackHandler.captured_code = code
            html = b"""
            <html><body style="font-family:sans-serif;padding:40px">
            <h2 style="color:green">&#10003; Upstox Authentication Successful</h2>
            <p>You can close this tab and return to the terminal.</p>
            </body></html>
            """
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(html)
        else:
            msg = f"Error: {error or 'no code received'}".encode()
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"<h2>Authentication failed.</h2><p>" + msg + b"</p>")

    def log_message(self, *args):
        pass  # suppress server access logs


def wait_for_callback(port: int, timeout: int = 300) -> str | None:
    """Start callback server and wait for the auth code. Returns code or None."""
    _CallbackHandler.captured_code = None
    server = HTTPServer(("localhost", port), _CallbackHandler)
    server.timeout = timeout

    print(f"  Listening for OAuth callback on http://localhost:{port}/callback ...")

    deadline = time.time() + timeout
    while time.time() < deadline and _CallbackHandler.captured_code is None:
        server.handle_request()

    server.server_close()
    return _CallbackHandler.captured_code


# ── Verification ──────────────────────────────────────────────────────────────

def verify_token(token: str) -> dict:
    """Hit the LTP endpoint to confirm the token is accepted. Returns LTP data."""
    import requests

    r = requests.get(
        "https://api.upstox.com/v2/market-quote/ltp",
        params={"instrument_key": "NSE_INDEX%7CNifty%2050"},
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=10,
    )
    if r.status_code == 200:
        return r.json().get("data", {})
    return {}


def get_profile(token: str) -> dict:
    """Fetch user profile (requires trading-scope token)."""
    import requests

    r = requests.get(
        "https://api.upstox.com/v2/user/profile",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=10,
    )
    if r.status_code == 200:
        return r.json().get("data", {})
    return {}


# ── Main ──────────────────────────────────────────────────────────────────────

def _decode_jwt_expiry(token: str) -> str:
    """Decode JWT payload and return expiry info (no signature verification)."""
    import base64
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return ""
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64).decode("utf-8"))
        exp = payload.get("exp")
        sub = payload.get("sub", "")
        if exp:
            import datetime
            exp_dt = datetime.datetime.fromtimestamp(exp)
            remaining = (exp_dt - datetime.datetime.now()).total_seconds() / 3600
            return f"sub={sub}  exp={exp_dt.strftime('%Y-%m-%d %H:%M')}  ({remaining:.1f}h remaining)"
        return f"sub={sub}"
    except Exception:
        return ""


def _save_sandbox_token(token: str, env_file: str) -> None:
    """Save a portal-generated sandbox token."""
    sb_file = ROOT / "data" / "upstox_sandbox_token.json"
    save_token(sb_file, {"access_token": token, "token_type": "Bearer",
                         "obtained_at": time.time()})
    _update_env_key(env_file, "UPSTOX_SANDBOX_TOKEN", token)
    print(f"  Sandbox token saved → {sb_file}")


def _update_env_key(env_file: str, key: str, value: str) -> None:
    env_path = ROOT / env_file
    if not env_path.exists():
        return
    with open(env_path) as f:
        lines = f.readlines()
    found = False
    new_lines = []
    for line in lines:
        if line.startswith(f"{key}="):
            new_lines.append(f"{key}={value}\n")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{key}={value}\n")
    with open(env_path, "w") as f:
        f.writelines(new_lines)
    print(f"  .env updated: {key} written")


def main() -> None:
    parser = argparse.ArgumentParser(description="Upstox login (3 methods)")
    parser.add_argument("--force",         action="store_true", help="Force re-auth even if token is valid")
    parser.add_argument("--env",           default=".env",      help="Path to .env file (default: .env)")
    parser.add_argument("--port",          type=int, default=3561, help="Callback/webhook port (default: 3561)")
    parser.add_argument("--no-browser",    action="store_true", help="Print URL instead of auto-opening browser")
    parser.add_argument("--token-request", action="store_true", help="Method 2: WhatsApp/in-app approval")
    parser.add_argument("--sandbox",       action="store_true", help="Method 3: paste sandbox portal token")
    args = parser.parse_args()

    _load_env(args.env)

    # ══════════════════════════════════════════════════════════════════════════
    # Method 3: Sandbox token (portal-generated, paste it in)
    # ══════════════════════════════════════════════════════════════════════════
    if args.sandbox:
        _banner("Upstox Sandbox Token")
        sb_file = ROOT / "data" / "upstox_sandbox_token.json"
        if not args.force and sb_file.exists():
            try:
                d = json.load(open(sb_file))
                age_h = (time.time() - d.get("obtained_at", 0)) / 3600
                tok = d.get("access_token", "")
                if tok and age_h < 720:
                    print(f"\n[OK] Found valid sandbox token (age: {age_h:.1f}h)")
                    print(f"     Token: {tok[:40]}...")
                    print("\n     Use --force to replace it.")
                    return
            except Exception:
                pass
        print("\n  Sandbox tokens are generated in the Upstox developer portal.")
        print("  No browser or OAuth flow needed.\n")
        print("  Steps:")
        print("    1. Open: https://account.upstox.com/developer/apps#sandbox")
        print("    2. Open your sandbox app → click  Generate")
        print("    3. Copy the 30-day token and paste below\n")
        import getpass
        pasted = getpass.getpass("  Paste sandbox token (input hidden): ").strip()
        if not pasted:
            print("[ERROR] No token provided."); sys.exit(1)
        _save_sandbox_token(pasted, args.env)
        print("\n  Sandbox ready. Run order tests:")
        print("    python scripts/order.py --sandbox")
        print("    python scripts/test_upstox.py --sandbox")
        return

    # ══════════════════════════════════════════════════════════════════════════
    # Method 2: Access Token Request API (WhatsApp / in-app notification)
    # ══════════════════════════════════════════════════════════════════════════
    if args.token_request:
        _banner("Upstox Login — Token Request (Method 2)")
        token_file = ROOT / "data" / "upstox_token.json"
        if not args.force:
            token, token_data = load_existing_token(token_file)
            if token:
                age_h = (time.time() - token_data.get("obtained_at", 0)) / 3600
                print(f"\n[OK] Found valid token (age: {age_h:.1f}h). Use --force to re-auth.\n")
                return

        print("\n[Step 1/3] Loading credentials...")
        api_key    = _require_env("UPSTOX_API_KEY", "Upstox API Key")
        api_secret = _require_env("UPSTOX_API_SECRET", "Upstox API Secret")
        print(f"  API Key: {api_key[:8]}...")
        print(f"\n  Pre-requisite: your app's Notifier URL must be set to:")
        print(f"    http://localhost:{args.port}/callback")
        print(f"  Configure at: account.upstox.com/developer/apps → your app → Settings")
        input("\n  Press Enter once Notifier URL is configured... ")

        print("\n[Step 2/3] Sending token request (triggers WhatsApp + in-app push)...")
        import requests as _req
        from http.server import BaseHTTPRequestHandler, HTTPServer as _HTTPServer

        # Start webhook listener for POST /callback
        received: dict = {}

        class _WebhookHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                try:
                    data = json.loads(body)
                    if data.get("access_token"):
                        received["data"] = data
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(b'{"status":"ok"}')
                    else:
                        self.send_response(400); self.end_headers()
                except Exception:
                    self.send_response(400); self.end_headers()
            def do_GET(self):
                self.send_response(200); self.end_headers()
                self.wfile.write(b'{"status":"waiting"}')
            def log_message(self, *a): pass

        srv = _HTTPServer(("localhost", args.port), _WebhookHandler)
        srv.timeout = 1

        # Trigger the request
        try:
            tr = _req.post(
                f"https://api.upstox.com/v3/login/auth/token/request/{api_key}",
                json={"client_secret": api_secret},
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=15,
            )
            if tr.status_code != 200:
                print(f"\n[ERROR] Token request failed (HTTP {tr.status_code}):")
                print(f"  {tr.text[:300]}")
                print("\n  Common errors:")
                print("    UDAPI100069 — wrong API key / secret")
                print("    UDAPI1123   — Notifier URL not configured in app settings")
                sys.exit(1)
            tr_data = tr.json().get("data", {})
            print(f"\n[OK] Token request sent!")
            print(f"  Notifier URL: {tr_data.get('notifier_url', '?')}")
        except Exception as e:
            print(f"\n[ERROR] {e}"); sys.exit(1)

        print("\n  Check your phone:")
        print("    → WhatsApp message from Upstox")
        print("    → OR in-app notification in the Upstox app")
        print("    → Tap  Approve  to generate the token")
        print(f"\n[Step 3/3] Waiting for webhook callback (up to 5 min)...")

        deadline = time.time() + 300
        while time.time() < deadline and not received:
            srv.handle_request()
            elapsed = int(time.time() - (deadline - 300))
            if elapsed % 30 == 0 and elapsed > 0:
                print(f"  ... {elapsed}s elapsed")

        srv.server_close()

        if not received:
            print("\n[ERROR] No approval received in 5 minutes.")
            print("  Check the Notifier URL in your app settings.")
            sys.exit(1)

        data = received["data"]
        access_token = data.get("access_token", "")
        data["obtained_at"] = time.time()
        save_token(token_file, data)
        _update_env_key(args.env, "UPSTOX_ACCESS_TOKEN", access_token)

        _banner("Authentication Successful — Token Request")
        print(f"\n  Access token: {access_token[:40]}...")
        jwt_info = _decode_jwt_expiry(access_token)
        if jwt_info:
            print(f"  JWT info:     {jwt_info}")
        ltp_data = verify_token(access_token)
        if ltp_data:
            nifty = ltp_data.get("NSE_INDEX:Nifty 50", {})
            print(f"  Nifty 50 LTP: ₹{nifty.get('last_price', 'N/A')}")
        print("\n  Run tests:  python scripts/test_upstox.py\n")
        return

    # ══════════════════════════════════════════════════════════════════════════
    # Method 1: Standard OAuth 2.0
    # ══════════════════════════════════════════════════════════════════════════
    _banner("Upstox Login — OAuth (Method 1)")

    token_file = ROOT / "data" / "upstox_token.json"

    # ── Step 1: Check existing token ──────────────────────────────────────────
    if not args.force:
        token, token_data = load_existing_token(token_file)
        if token:
            age_h = (time.time() - token_data.get("obtained_at", 0)) / 3600
            print(f"\n[OK] Found valid token (age: {age_h:.1f}h)")
            print(f"     Token: {token[:40]}...")

            # Quick market data check
            ltp_data = verify_token(token)
            if ltp_data:
                nifty = ltp_data.get("NSE_INDEX:Nifty 50", {})
                print(f"     Nifty 50 LTP: ₹{nifty.get('last_price', 'N/A')}")
                print("\n[OK] Token is working. No re-authentication needed.")
                print("     Use --force to re-authenticate anyway.\n")
                return
            else:
                print("     Warning: token exists but market data call failed.")
                print("     Proceeding with re-authentication...\n")

    # ── Step 2: Load credentials ──────────────────────────────────────────────
    print("\n[Step 1/3] Loading API credentials...")
    api_key    = _require_env("UPSTOX_API_KEY", "Upstox API Key")
    api_secret = _require_env("UPSTOX_API_SECRET", "Upstox API Secret")
    redirect_uri = os.environ.get("UPSTOX_REDIRECT_URI", f"http://localhost:{args.port}/callback")

    # Ensure redirect_uri port matches our callback port
    parsed_redirect = urlparse(redirect_uri)
    callback_port = parsed_redirect.port or args.port

    print(f"  API Key:      {api_key[:8]}...")
    print(f"  Redirect URI: {redirect_uri}")

    auth_url = build_auth_url(api_key, redirect_uri)

    # ── Step 3: Get authorization code ───────────────────────────────────────
    print("\n[Step 2/3] Getting authorization code...")
    print()
    print("  Upstox requires you to log in via browser.")
    print("  You will need your: mobile number, PIN/password, and TOTP.")
    print()
    print("  TOTP tip: if you want to generate your TOTP code here instead of")
    print("  using your phone app, run in another terminal:")
    print("    python scripts/generate_totp.py --secret YOUR_TOTP_SECRET")
    print()

    code = None

    if args.no_browser:
        # Manual flow
        print("  Auth URL (open this in your browser):")
        print(f"\n  {auth_url}\n")
        print("  After logging in, you will be redirected to:")
        print(f"  {redirect_uri}?code=XXXXXX")
        raw = input("  Paste the full redirect URL (or just the code): ").strip()
        if "code=" in raw:
            code = parse_qs(urlparse(raw).query).get("code", [None])[0]
        else:
            code = raw or None
    else:
        # Auto-browser + local server
        print("  Starting local callback server...")
        print(f"  Opening browser → {auth_url[:70]}...")
        print()

        opened = webbrowser.open(auth_url)
        if not opened:
            print("  [!] Could not open browser automatically.")
            print(f"  Open manually: {auth_url}")

        code = wait_for_callback(callback_port, timeout=300)

        if not code:
            # Fallback: ask user to paste manually
            print("\n  [!] Did not receive callback automatically.")
            print(f"\n  Auth URL: {auth_url}\n")
            raw = input("  After logging in, paste the full redirect URL here: ").strip()
            if "code=" in raw:
                code = parse_qs(urlparse(raw).query).get("code", [None])[0]
            else:
                code = raw or None

    if not code:
        print("\n[ERROR] No authorization code received. Aborting.")
        sys.exit(1)

    print(f"\n  Auth code received: {code[:12]}...")

    # ── Step 4: Exchange code for token ──────────────────────────────────────
    print("\n[Step 3/3] Exchanging code for access token...")
    token_data = exchange_code_for_token(code, api_key, api_secret, redirect_uri)
    token = token_data.get("access_token", "")

    if not token:
        print("[ERROR] No access_token in response:")
        print(json.dumps(token_data, indent=2))
        sys.exit(1)

    save_token(token_file, token_data)

    # Save extended_token if present (1-year read-only token)
    extended_token = token_data.get("extended_token", "")
    if extended_token:
        ext_file = ROOT / "data" / "upstox_extended_token.json"
        save_token(ext_file, {
            "access_token": extended_token,
            "token_type": "extended",
            "obtained_at": time.time(),
        })
        env_path = ROOT / args.env
        if env_path.exists():
            _update_env_key(args.env, "UPSTOX_EXTENDED_TOKEN", extended_token)

    # ── Summary ───────────────────────────────────────────────────────────────
    _banner("Authentication Successful")
    print(f"\n  Access token:   {token[:40]}...")
    jwt_info = _decode_jwt_expiry(token)
    if jwt_info:
        print(f"  JWT info:       {jwt_info}")
    else:
        print(f"  Expires:        ~23 hours from now (3:30 AM tomorrow)")
    print(f"  Saved to:       {token_file}")
    if extended_token:
        print(f"  Extended token: {extended_token[:40]}...  (1-year read-only)")
        print(f"  Saved to:       {ROOT / 'data' / 'upstox_extended_token.json'}")

    # Verify with a market data call
    print("\n  Verifying token against Upstox API...")
    ltp_data = verify_token(token)
    if ltp_data:
        nifty = ltp_data.get("NSE_INDEX:Nifty 50", {})
        print(f"  [OK] Nifty 50 LTP: ₹{nifty.get('last_price', 'N/A')}")
    else:
        print("  [!] Market data check skipped (market may be closed or token is analytics-only)")

    # Profile (only works with full trading token, not analytics-only)
    profile = get_profile(token)
    if profile:
        print(f"\n  Account: {profile.get('user_name', 'N/A')} ({profile.get('email', 'N/A')})")
        print(f"  User ID: {profile.get('user_id', 'N/A')}")

    print()
    print("  Next steps:")
    print("    Run tests:       python scripts/test_upstox.py")
    print("    Start paper bot: python main.py --mode paper")
    print()

    # Write token to .env as UPSTOX_ACCESS_TOKEN for convenience
    env_file_path = ROOT / args.env
    if env_file_path.exists():
        with open(env_file_path) as f:
            env_contents = f.read()
        if "UPSTOX_ACCESS_TOKEN=" in env_contents:
            lines = []
            for line in env_contents.splitlines():
                if line.startswith("UPSTOX_ACCESS_TOKEN="):
                    lines.append(f"UPSTOX_ACCESS_TOKEN={token}")
                else:
                    lines.append(line)
            with open(env_file_path, "w") as f:
                f.write("\n".join(lines) + "\n")
            print(f"  .env updated: UPSTOX_ACCESS_TOKEN written to {env_file_path}")


if __name__ == "__main__":
    main()
