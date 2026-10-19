"""Dashboard login (dashboard/backend/auth.py)."""
from __future__ import annotations
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.backend import auth

REMOTE = {"x-forwarded-for": "203.0.113.7"}


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "SECRET_FILE", tmp_path / "secret")
    auth._failures.clear()
    a = FastAPI()
    a.middleware("http")(auth.middleware)
    a.include_router(auth.router, prefix="/api")

    @a.get("/api/positions")
    def positions():
        return {"ok": True}

    @a.get("/api/health")
    def health():
        return {"status": "healthy"}

    @a.get("/")
    def index():
        return {"spa": True}
    return a


def test_without_password_only_this_machine_gets_in(app, monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "")
    c = TestClient(app)
    assert c.get("/api/positions").status_code == 200                       # local
    r = c.get("/api/positions", headers=REMOTE)                             # via a proxy from elsewhere
    assert r.status_code == 401 and "DASHBOARD_PASSWORD" in r.json()["detail"]
    assert c.get("/api/health", headers=REMOTE).status_code == 200          # public
    assert c.get("/", headers=REMOTE).status_code == 200                    # the SPA itself loads
    assert c.post("/api/auth/login", json={"password": "x"}).status_code == 400


def test_password_login_cookie_and_logout(app, monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "s3cret")
    c = TestClient(app)
    assert c.get("/api/positions").status_code == 401                       # even locally
    assert c.get("/api/auth/status").json() == {"password_set": True, "local": True, "authenticated": False}
    assert c.post("/api/auth/login", json={"password": "nope"}).status_code == 401
    r = c.post("/api/auth/login", json={"password": "s3cret"})
    assert r.status_code == 200 and auth.COOKIE in r.cookies
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert c.get("/api/positions", headers=REMOTE).status_code == 200       # session works from anywhere
    c.post("/api/auth/logout")
    c.cookies.clear()
    assert c.get("/api/positions").status_code == 401


def test_bearer_token_for_scripts(app, monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "s3cret")
    token = TestClient(app).post("/api/auth/login", json={"password": "s3cret"}).json()["token"]
    c = TestClient(app)
    assert c.get("/api/positions", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert c.get("/api/positions", headers={"Authorization": "Bearer junk.abc"}).status_code == 401


def test_tokens_expire_and_die_with_a_password_change(app, monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "SECRET_FILE", tmp_path / "secret2")
    tok = auth.make_token("pw", now=1000.0)
    assert auth.valid_token(tok, "pw", now=1001.0)
    assert not auth.valid_token(tok, "pw", now=1000.0 + 13 * 3600)          # past 12 h
    assert not auth.valid_token(tok, "other", now=1001.0)
    assert not auth.valid_token("garbage", "pw")


def test_repeated_failures_are_locked_out(app, monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "s3cret")
    c = TestClient(app)
    for _ in range(5):
        assert c.post("/api/auth/login", json={"password": "bad"}).status_code == 401
    assert c.post("/api/auth/login", json={"password": "s3cret"}).status_code == 429


def test_main_app_is_protected(monkeypatch):
    from dashboard.backend.main import app as main_app
    monkeypatch.setenv("DASHBOARD_PASSWORD", "")
    r = TestClient(main_app).get("/api/positions", headers=REMOTE)
    assert r.status_code == 401
