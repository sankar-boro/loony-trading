"""Tests for the Phase 9 portfolio risk dashboard (spec §46/§47): exposure,
sector concentration, correlation, and threshold warnings."""
from __future__ import annotations
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.backend.routers import portfolio_risk


@pytest.fixture()
def client(tmp_path, monkeypatch):
    state_file = tmp_path / "live_positions.json"
    daily_file = tmp_path / "daily_pnl.jsonl"
    monkeypatch.setattr(portfolio_risk, "_STATE_FILE", state_file)
    monkeypatch.setattr(portfolio_risk, "_DAILY_FILE", daily_file)
    # Correlation requires live/demo price fetches — stub it so tests are
    # fast and deterministic; correlation logic itself is tested separately.
    monkeypatch.setattr(portfolio_risk, "_correlation_matrix", lambda symbols: {})

    app = FastAPI()
    app.include_router(portfolio_risk.router, prefix="/api")
    return TestClient(app)


def _write_state(path, positions, cash=100_000.0, initial_capital=500_000.0):
    path.write_text(json.dumps({
        "positions": positions, "cash": cash, "initial_capital": initial_capital,
    }))


def test_empty_state_returns_zeros_and_no_warnings(client):
    resp = client.get("/api/portfolio/risk")
    assert resp.status_code == 200
    body = resp.json()
    assert body["capital"] == 500_000.0
    assert body["open_positions"] == 0
    assert body["market_value"] == 0
    assert body["warnings"] == []


def test_missing_state_file_defaults_gracefully(client):
    resp = client.get("/api/portfolio/risk")
    assert resp.status_code == 200


def test_market_value_and_unrealized_pnl_sum_positions(client, tmp_path):
    _write_state(portfolio_risk._STATE_FILE, [
        {"symbol": "HDFCBANK", "size": 10, "current_price": 1700, "entry_price": 1650,
         "unrealised_pnl": 500, "stop_loss": 1600},
        {"symbol": "TCS", "size": 5, "current_price": 4100, "entry_price": 4000,
         "unrealised_pnl": 500, "stop_loss": 3900},
    ])
    body = client.get("/api/portfolio/risk").json()
    assert body["open_positions"] == 2
    assert body["market_value"] == pytest.approx(10 * 1700 + 5 * 4100)
    assert body["unrealized_pnl"] == pytest.approx(1000)


def test_max_loss_is_sum_of_stop_distance_times_size(client):
    _write_state(portfolio_risk._STATE_FILE, [
        {"symbol": "HDFCBANK", "size": 10, "current_price": 1700, "entry_price": 1650,
         "unrealised_pnl": 500, "stop_loss": 1600},
    ])
    body = client.get("/api/portfolio/risk").json()
    assert body["max_loss"] == pytest.approx((1650 - 1600) * 10)


def test_sector_concentration_warning_fires_above_threshold(client):
    # HDFCBANK + ICICIBANK are both Banking — 200,000 / 500,000 capital = 40% > 35%
    _write_state(portfolio_risk._STATE_FILE, [
        {"symbol": "HDFCBANK", "size": 60, "current_price": 1700, "entry_price": 1650,
         "unrealised_pnl": 0, "stop_loss": 1600},
        {"symbol": "ICICIBANK", "size": 76, "current_price": 1200, "entry_price": 1150,
         "unrealised_pnl": 0, "stop_loss": 1100},
    ])
    body = client.get("/api/portfolio/risk").json()
    assert body["sector_exposure_pct"]["Banking"] > 35.0
    sector_warnings = [w for w in body["warnings"] if w["type"] == "sector_concentration"]
    assert len(sector_warnings) == 1
    assert "Banking" in sector_warnings[0]["message"]


def test_sector_concentration_no_warning_when_diversified(client):
    _write_state(portfolio_risk._STATE_FILE, [
        {"symbol": "HDFCBANK", "size": 5, "current_price": 1700, "entry_price": 1650,
         "unrealised_pnl": 0, "stop_loss": 1600},
        {"symbol": "TCS", "size": 5, "current_price": 4100, "entry_price": 4000,
         "unrealised_pnl": 0, "stop_loss": 3900},
    ])
    body = client.get("/api/portfolio/risk").json()
    assert not any(w["type"] == "sector_concentration" for w in body["warnings"])


def test_total_exposure_warning_above_portfolio_risk_limit(client):
    # 130,000 / 500,000 = 26% > default max_portfolio_risk 20%
    _write_state(portfolio_risk._STATE_FILE, [
        {"symbol": "HDFCBANK", "size": 25, "current_price": 5200, "entry_price": 5100,
         "unrealised_pnl": 0, "stop_loss": 5000},
    ])
    body = client.get("/api/portfolio/risk").json()
    assert any(w["type"] == "total_exposure" for w in body["warnings"])


def test_daily_loss_limit_warning_combines_realised_and_unrealized(client):
    portfolio_risk._DAILY_FILE.write_text(json.dumps({"date": "2026-08-11", "realised": -20_000}) + "\n")
    _write_state(portfolio_risk._STATE_FILE, [
        {"symbol": "HDFCBANK", "size": 10, "current_price": 1500, "entry_price": 1650,
         "unrealised_pnl": -10_000, "stop_loss": 1600},
    ])
    body = client.get("/api/portfolio/risk").json()
    # realised -20,000 + unrealized -10,000 = -30,000, which exceeds
    # -500,000 * 0.05 = -25,000 default max daily drawdown
    assert body["daily_pnl"] == pytest.approx(-30_000)
    assert any(w["type"] == "daily_loss_limit" for w in body["warnings"])


def test_high_correlation_warning(client, monkeypatch):
    monkeypatch.setattr(portfolio_risk, "_correlation_matrix", lambda symbols: {
        "HDFCBANK": {"HDFCBANK": 1.0, "ICICIBANK": 0.85},
        "ICICIBANK": {"HDFCBANK": 0.85, "ICICIBANK": 1.0},
    })
    _write_state(portfolio_risk._STATE_FILE, [
        {"symbol": "HDFCBANK", "size": 1, "current_price": 1700, "entry_price": 1650,
         "unrealised_pnl": 0, "stop_loss": 1600},
        {"symbol": "ICICIBANK", "size": 1, "current_price": 1200, "entry_price": 1150,
         "unrealised_pnl": 0, "stop_loss": 1100},
    ])
    body = client.get("/api/portfolio/risk").json()
    corr_warnings = [w for w in body["warnings"] if w["type"] == "high_correlation"]
    assert len(corr_warnings) == 1
    assert "HDFCBANK" in corr_warnings[0]["message"] and "ICICIBANK" in corr_warnings[0]["message"]
