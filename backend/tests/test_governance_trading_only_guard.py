"""Governance API trading-only route guard."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes_governance import router as governance_router


def _governance_app() -> FastAPI:
    fa = FastAPI()
    fa.include_router(governance_router, prefix="/api")
    return fa


def test_governance_routes_blocked_when_trading_only(monkeypatch) -> None:
    monkeypatch.setenv("ATP_TRADING_ONLY", "1")
    client = TestClient(_governance_app())
    r = client.get("/api/governance/resolve")
    assert r.status_code == 403
    detail = r.json()["detail"]
    assert detail["error"] == "governance_api_disabled"
    assert detail["reason"] == "ATP_TRADING_ONLY=1"


def test_governance_routes_not_blocked_when_trading_only_off(monkeypatch) -> None:
    monkeypatch.delenv("ATP_TRADING_ONLY", raising=False)
    monkeypatch.setenv("GOVERNANCE_API_TOKEN", "guard-test-token")
    client = TestClient(_governance_app())
    r = client.get(
        "/api/governance/resolve",
        headers={"Authorization": "Bearer guard-test-token"},
    )
    assert r.status_code == 400
    assert "Provide exactly one query param" in r.json()["detail"]
