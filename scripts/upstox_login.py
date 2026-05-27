#!/usr/bin/env python
"""
Upstox Login Script
===================

Handles the complete Upstox OAuth 2.0 authentication flow interactively.

How it works:
  1. Checks for an existing valid token (reuses it, no browser needed)
  2. If expired/missing:
     - Builds the authorization URL
     - Starts a local HTTP server on port 8888 to capture the redirect
     - Opens the Upstox login page in your browser
     - You log in with mobile / PIN / TOTP on the Upstox page
     - The redirect code is captured automatically
     - Exchanges the code for an access token and saves it
  3. If browser isn't available (headless server):
     - Prints the URL for you to open manually
     - Asks you to paste the auth code from the redirect URL

TOTP / OTP:
  Upstox asks for a 6-digit TOTP during browser login.
  Use your authenticator app (Google Authenticator, etc.) OR run:
      python scripts/generate_totp.py --secret YOUR_32_CHAR_SECRET

Usage:
    python scripts/upstox_login.py
    python scripts/upstox_login.py --force    # force re-auth even if token is valid
    python scripts/upstox_login.py --env .env # specify env file
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

def main() -> None:
    parser = argparse.ArgumentParser(description="Upstox OAuth login")
    parser.add_argument("--force", action="store_true", help="Force re-auth even if token is valid")
    parser.add_argument("--env", default=".env", help="Path to .env file (default: .env)")
    parser.add_argument("--port", type=int, default=8888, help="Local callback port (default: 8888)")
    parser.add_argument("--no-browser", action="store_true", help="Print URL instead of auto-opening browser")
    args = parser.parse_args()

    _banner("Upstox Login")
    _load_env(args.env)

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

    # ── Summary ───────────────────────────────────────────────────────────────
    _banner("Authentication Successful")
    print(f"\n  Access token: {token[:40]}...")
    print(f"  Expires:      ~23 hours from now")
    print(f"  Saved to:     {token_file}")

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
