"""
Tests for POST /api/risk/probe. No real API calls; mock risk_guard / exchange.
Route exists (not 404); spot returns 200 allowed=true when valid or when equity unavailable; margin over-cap returns 400 RISK_GUARD_BLOCKED.
"""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from fastapi import FastAPI

from app.api.routes_risk_probe import router as risk_probe_router

app = FastAPI()
app.include_router(risk_probe_router, prefix="/api", tags=["risk"])
client = TestClient(app)

PROBE_BODY = {
    "symbol": "BTC_USDT",
    "side": "BUY",
    "price": 50000,
    "quantity": 0.01,
    "is_margin": False,
    "leverage": None,
    "trade_on_margin_from_watchlist": True,
    "account_equity": 10_000.0,
    "total_margin_exposure": 0.0,
    "daily_loss_pct": 0.0,
}

# Spot with NO equity params (verifier sends this)
SPOT_NO_METRICS = {
    "symbol": "BTC_USDT",
    "side": "BUY",
    "price": 50000,
    "quantity": 0.01,
    "is_margin": False,
    "trade_on_margin_from_watchlist": False,
}


def test_risk_probe_route_exists():
    """POST /api/risk/probe returns 200 or 400, not 404."""
    r = client.post("/api/risk/probe", json=PROBE_BODY)
    assert r.status_code in (200, 400), "Route must exist (200 or 400, not 404)"


def test_risk_probe_margin_block():
    """Margin with leverage > cap returns 400 and reason_code RISK_GUARD_BLOCKED."""
    body = {
        **PROBE_BODY,
        "is_margin": True,
        "leverage": 10.0,
        "trade_on_margin_from_watchlist": True,
    }
    r = client.post("/api/risk/probe", json=body)
    assert r.status_code == 400
    data = r.json()
    assert data.get("allowed") is False
    assert data.get("reason_code") == "RISK_GUARD_BLOCKED"


def test_risk_probe_spot_ok_when_metrics_provided():
    """Spot with valid equity metrics returns 200 allowed=true (no exchange call)."""
    r = client.post("/api/risk/probe", json=PROBE_BODY)
    assert r.status_code == 200
    assert r.json().get("allowed") is True


def test_risk_probe_spot_no_metrics_returns_200_when_exchange_unavailable():
    """Spot with NO metrics: when _get_equity_from_exchange fails, return 200 allowed=true (Phase 6)."""
    with patch("app.api.routes_risk_probe._get_equity_from_exchange") as mock_fetch:
        mock_fetch.side_effect = ValueError("exchange unavailable")
        r = client.post("/api/risk/probe", json=SPOT_NO_METRICS)
    assert r.status_code == 200
    data = r.json()
    assert data.get("allowed") is True
    assert data.get("note") == "equity_unavailable_spot_probe_allowed"


def test_risk_probe_margin_no_metrics_returns_400_when_exchange_unavailable():
    """Margin with NO metrics: when _get_equity_from_exchange fails, return 400 (strict)."""
    body = {
        **SPOT_NO_METRICS,
        "is_margin": True,
        "leverage": 5.0,
        "trade_on_margin_from_watchlist": True,
    }
    with patch("app.api.routes_risk_probe._get_equity_from_exchange") as mock_fetch:
        mock_fetch.side_effect = ValueError("exchange unavailable")
        r = client.post("/api/risk/probe", json=body)
    assert r.status_code == 400
    data = r.json()
    assert data.get("allowed") is False
    assert data.get("reason_code") == "RISK_GUARD_BLOCKED"


def test_probe_trade_on_margin_from_watchlist_false_forces_spot_returns_200():
    """trade_on_margin_from_watchlist=false forces spot → allowed."""
    body = {
        **PROBE_BODY,
        "is_margin": True,
        "leverage": 10.0,
        "trade_on_margin_from_watchlist": False,
    }
    r = client.post("/api/risk/probe", json=body)
    assert r.status_code == 200
    assert r.json().get("allowed") is True


def test_probe_global_kill_switch_off_returns_400():
    """GLOBAL_TRADING_ENABLED=false → 400 RISK_GUARD_BLOCKED."""
    with patch("app.services.risk_guard.GLOBAL_TRADING_ENABLED", False):
        r = client.post("/api/risk/probe", json=PROBE_BODY)
    assert r.status_code == 400
    data = r.json()
    assert data.get("allowed") is False
    assert data.get("reason_code") == "RISK_GUARD_BLOCKED"
