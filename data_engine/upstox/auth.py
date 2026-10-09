"""
Upstox OAuth 2.0 authentication.

Flow:
  1. Call auth_url() → open in browser → user logs in → redirected to redirect_uri?code=XXX
  2. Call exchange_code(code) → stores access_token to token_file
  3. All subsequent API calls use load_token()

The access token is valid for one trading day.
Auto-refresh is attempted at startup if the stored token is expired.
"""
from __future__ import annotations
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from utils.logger import get_logger

logger = get_logger("upstox.auth")

_AUTH_BASE = "https://api.upstox.com/v2"
_AUTH_DIALOG = "https://api.upstox.com/v2/login/authorization/dialog"
_TOKEN_URL = f"{_AUTH_BASE}/login/authorization/token"

_IST = ZoneInfo("Asia/Kolkata")


def token_expires_at(obtained_at: float) -> float:
    """Epoch time at which a daily Upstox access token stops working.

    Tokens are not valid for a fixed number of hours: every token expires at
    03:30 IST the morning after it was issued (or the same morning, if it was
    issued between midnight and 03:30).
    """
    issued = datetime.fromtimestamp(obtained_at, _IST)
    expiry = issued.replace(hour=3, minute=30, second=0, microsecond=0)
    if expiry <= issued:
        expiry += timedelta(days=1)
    return expiry.timestamp()


def token_hours_left(obtained_at: float, now: float | None = None) -> float:
    """Hours until the token expires; zero or negative once it has expired."""
    now = time.time() if now is None else now
    return (token_expires_at(obtained_at) - now) / 3600


class UpstoxAuth:
    """
    Manages Upstox OAuth 2.0 token lifecycle.
    Tokens are persisted to disk so restarts within the same trading day
    don't require re-authentication.
    """

    def __init__(self, api_key: str, api_secret: str, redirect_uri: str,
                 token_file: str = "data/upstox_token.json"):
        self.api_key = api_key
        self.api_secret = api_secret
        self.redirect_uri = redirect_uri
        self.token_file = Path(token_file)
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self._token_data: dict = {}

    # ── Token URL generation ──────────────────────────────────────────────────

    def auth_url(self) -> str:
        """Return the URL the user must visit to authorise the app."""
        params = {
            "response_type": "code",
            "client_id": self.api_key,
            "redirect_uri": self.redirect_uri,
        }
        url = f"{_AUTH_DIALOG}?{urlencode(params)}"
        logger.info(f"Open this URL to authorise: {url}")
        return url

    # ── Code → Token exchange ─────────────────────────────────────────────────

    def exchange_code(self, code: str) -> str:
        """Exchange authorisation code for access token. Returns token string."""
        import requests
        payload = {
            "code": code,
            "client_id": self.api_key,
            "client_secret": self.api_secret,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
        }
        resp = requests.post(_TOKEN_URL, data=payload,
                             headers={"Content-Type": "application/x-www-form-urlencoded",
                                      "Accept": "application/json"})
        resp.raise_for_status()
        data = resp.json()
        data["obtained_at"] = time.time()
        self._token_data = data
        self._save_token(data)
        logger.info("Upstox access token obtained and saved")
        return data["access_token"]

    # ── Token persistence ─────────────────────────────────────────────────────

    def _save_token(self, data: dict) -> None:
        with open(self.token_file, "w") as f:
            json.dump(data, f, indent=2)

    def load_token(self) -> Optional[str]:
        """Load token from disk. Returns None if missing or expired (past 03:30 IST)."""
        if not self.token_file.exists():
            return None
        try:
            with open(self.token_file) as f:
                data = json.load(f)
            age_hours = (time.time() - data.get("obtained_at", 0)) / 3600
            if token_hours_left(data.get("obtained_at", 0)) <= 0:
                logger.warning("Upstox token expired — re-authentication required")
                return None
            self._token_data = data
            token = data.get("access_token")
            logger.info(f"Loaded Upstox token (age: {age_hours:.1f}h)")
            return token
        except Exception as e:
            logger.error(f"Failed to load token: {e}")
            return None

    @property
    def access_token(self) -> Optional[str]:
        return self._token_data.get("access_token")

    @property
    def auth_header(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
        }

    def is_valid(self) -> bool:
        if not self._token_data:
            return False
        return token_hours_left(self._token_data.get("obtained_at", 0)) > 0


class UpstoxAuthServer:
    """
    Tiny local HTTP server to capture the OAuth redirect automatically.
    Starts on localhost, waits for the code, then exchanges it.
    Usage: only needed for automated/headless setups.
    """

    def __init__(self, auth: UpstoxAuth, port: int = 3561):
        self.auth = auth
        self.port = port
        self._code: Optional[str] = None

    def start_and_wait(self, timeout: int = 300) -> Optional[str]:
        """
        Starts a server on localhost:{port}, prints the auth URL,
        waits for the redirect, exchanges the code, returns access_token.
        """
        from http.server import HTTPServer, BaseHTTPRequestHandler
        from urllib.parse import urlparse, parse_qs
        import threading

        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urlparse(self.path)
                params = parse_qs(parsed.query)
                if "code" in params:
                    outer._code = params["code"][0]
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"<h2>Upstox auth complete. Close this tab.</h2>")
                else:
                    self.send_response(400)
                    self.end_headers()

            def log_message(self, *args):
                pass  # suppress server logs

        server = HTTPServer(("localhost", self.port), Handler)
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()

        print(f"\n{'='*60}")
        print("UPSTOX AUTHENTICATION REQUIRED")
        print(f"Open this URL in your browser:\n{self.auth.auth_url()}")
        print(f"{'='*60}\n")

        thread.join(timeout=timeout)
        server.server_close()

        if self._code:
            return self.auth.exchange_code(self._code)
        return None
