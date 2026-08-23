import sys, os, json, time, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from data_engine.upstox.auth import UpstoxAuth


@pytest.fixture
def auth(tmp_path):
    return UpstoxAuth(
        api_key="test_key",
        api_secret="test_secret",
        redirect_uri="http://localhost:3561/callback",
        token_file=str(tmp_path / "token.json"),
    )


def test_auth_url_contains_client_id(auth):
    url = auth.auth_url()
    assert "test_key" in url
    assert "response_type=code" in url
    assert "redirect_uri" in url


def test_auth_url_format(auth):
    url = auth.auth_url()
    assert url.startswith("https://api.upstox.com")


def test_load_token_missing_file(auth):
    result = auth.load_token()
    assert result is None


def test_save_and_load_token(auth, tmp_path):
    token_data = {
        "access_token": "my_test_token_abc123",
        "token_type": "bearer",
        "obtained_at": time.time(),
    }
    auth._token_data = token_data
    auth._save_token(token_data)
    loaded = auth.load_token()
    assert loaded == "my_test_token_abc123"


def test_token_expiry_detection(auth, tmp_path):
    old_token = {
        "access_token": "expired_token",
        "obtained_at": time.time() - 90000,  # > 23h old
    }
    auth._token_data = old_token
    auth._save_token(old_token)
    result = auth.load_token()
    assert result is None


def test_is_valid_fresh_token(auth):
    auth._token_data = {"access_token": "x", "obtained_at": time.time()}
    assert auth.is_valid() is True


def test_is_valid_expired_token(auth):
    auth._token_data = {"access_token": "x", "obtained_at": time.time() - 90000}
    assert auth.is_valid() is False


def test_is_valid_no_token(auth):
    auth._token_data = {}
    assert auth.is_valid() is False


def test_auth_header_format(auth):
    auth._token_data = {"access_token": "bearer_xyz", "obtained_at": time.time()}
    header = auth.auth_header
    assert "Authorization" in header
    assert header["Authorization"] == "Bearer bearer_xyz"
    assert header["Accept"] == "application/json"
