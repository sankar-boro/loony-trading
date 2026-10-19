"""
Dashboard login.

With DASHBOARD_PASSWORD set (in .env or the environment), every /api route
except a few public ones needs a session: log in with the password and the
browser gets an HttpOnly, SameSite=Strict cookie, valid for
DASHBOARD_SESSION_HOURS (12). Scripts can send the same session token as
`Authorization: Bearer <token>` (from POST /api/auth/login).

Without a password, the API answers only requests from this machine
(loopback, with no forwarded remote address) and refuses everything else —
so a dashboard reachable from the network is never open to it.

Sessions are signed with HMAC-SHA256. The key combines a random secret in
data/.dashboard_secret with the password, so changing the password logs
every session out.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .config import ROOT

COOKIE = "loony_session"
SECRET_FILE = ROOT / "data" / ".dashboard_secret"
PUBLIC_PATHS = {"/api/health", "/api/auth/login", "/api/auth/logout", "/api/auth/status"}
_LOOPBACK = {"127.0.0.1", "::1", "localhost", "testclient"}
_MAX_FAILURES, _FAILURE_WINDOW = 5, 300          # login attempts per client per 5 minutes
_failures: dict[str, deque] = defaultdict(deque)

router = APIRouter()


def _password() -> str:
    from config.loader import load_dotenv
    load_dotenv()
    return os.environ.get("DASHBOARD_PASSWORD", "")


def _session_seconds() -> int:
    try:
        return int(float(os.environ.get("DASHBOARD_SESSION_HOURS", "12")) * 3600)
    except ValueError:
        return 12 * 3600


def _secret() -> bytes:
    try:
        return SECRET_FILE.read_bytes()
    except OSError:
        SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
        key = secrets.token_bytes(32)
        SECRET_FILE.write_bytes(key)
        try:
            SECRET_FILE.chmod(0o600)
        except OSError:
            pass
        return key


def _key(password: str) -> bytes:
    return _secret() + hashlib.sha256(password.encode()).digest()


def make_token(password: str, now: float | None = None) -> str:
    exp = int((now or time.time()) + _session_seconds())
    sig = hmac.new(_key(password), str(exp).encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def valid_token(token: str, password: str, now: float | None = None) -> bool:
    try:
        exp_s, sig = token.split(".", 1)
        exp = int(exp_s)
    except (ValueError, AttributeError):
        return False
    if exp < (now or time.time()):
        return False
    good = hmac.new(_key(password), exp_s.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, good)


def is_local(request: Request) -> bool:
    """A request from this machine: loopback peer and no forwarded remote client."""
    host = request.client.host if request.client else ""
    forwarded = request.headers.get("x-forwarded-for", "")
    remote_hops = [h.strip() for h in forwarded.split(",") if h.strip() and h.strip() not in _LOOPBACK]
    return host in _LOOPBACK and not remote_hops


def _request_token(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(COOKIE, "")


def authorised(request: Request) -> bool:
    password = _password()
    if not password:
        return is_local(request)
    return valid_token(_request_token(request), password)


async def middleware(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api") and path not in PUBLIC_PATHS and not authorised(request):
        detail = ("Log in to the dashboard" if _password() else
                  "Set DASHBOARD_PASSWORD to use the dashboard from another machine")
        return JSONResponse({"detail": detail}, status_code=401)
    return await call_next(request)


class LoginRequest(BaseModel):
    password: str


@router.post("/auth/login")
def login(req: LoginRequest, request: Request, response: Response) -> dict:
    password = _password()
    if not password:
        raise HTTPException(400, "No DASHBOARD_PASSWORD is set; the dashboard is local-only")
    client = request.client.host if request.client else "?"
    recent = _failures[client]
    now = time.time()
    while recent and now - recent[0] > _FAILURE_WINDOW:
        recent.popleft()
    if len(recent) >= _MAX_FAILURES:
        raise HTTPException(429, "Too many failed logins — wait a few minutes")
    if not hmac.compare_digest(req.password.encode(), password.encode()):
        recent.append(now)
        raise HTTPException(401, "Wrong password")
    recent.clear()
    token = make_token(password)
    response.set_cookie(COOKIE, token, max_age=_session_seconds(), httponly=True,
                        samesite="strict", secure=request.url.scheme == "https", path="/")
    return {"ok": True, "token": token, "expires_in": _session_seconds()}


@router.post("/auth/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/auth/status")
def status(request: Request) -> dict:
    password = _password()
    return {"password_set": bool(password), "local": is_local(request),
            "authenticated": authorised(request)}
