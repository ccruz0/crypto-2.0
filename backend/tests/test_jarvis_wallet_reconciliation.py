"""Tests for Jarvis wallet reconciliation read-only diagnostic tool."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes_jarvis import router as jarvis_router
from app.jarvis.mvp.agents import _fallback_plan
from app.jarvis.mvp.graph import reset_jarvis_graph_cache
from app.jarvis.mvp.tools import READONLY_TOOLS, run_readonly_tool
from app.jarvis.mvp.wallet_reconciliation import (
    is_wallet_reconcile_task,
    reconcile_crypto_wallet_vs_dashboard,
)


@pytest.fixture(autouse=True)
def _reset_graph_cache():
    reset_jarvis_graph_cache()
    yield
    reset_jarvis_graph_cache()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(jarvis_router)
    return TestClient(app)


@pytest.mark.parametrize(
    "task,expected",
    [
        ("reconcile Crypto.com wallet balance with dashboard portfolio balance", True),
        ("wallet mismatch between exchange and dashboard", True),
        ("dashboard balance wrong on portfolio tab", True),
        ("portfolio mismatch investigation", True),
        ("check dashboard health", False),
    ],
)
def test_is_wallet_reconcile_task(task: str, expected: bool):
    assert is_wallet_reconcile_task(task) is expected


def test_fallback_plan_routes_wallet_reconcile_task():
    task = "reconcile Crypto.com wallet balance with dashboard portfolio balance"
    plan = _fallback_plan(task)
    tools = [step.get("tool") for step in plan if step.get("tool")]
    assert "reconcile_crypto_wallet_vs_dashboard" in tools
    assert tools[0] == "reconcile_crypto_wallet_vs_dashboard"


def test_reconcile_tool_in_readonly_allowlist():
    assert "reconcile_crypto_wallet_vs_dashboard" in READONLY_TOOLS


def test_high_crypto_low_dashboard_mismatch():
    account_summary = {
        "accounts": [
            {"currency": "BTC", "balance": "1.0", "market_value": "15000"},
            {"currency": "USD", "balance": "1799.65", "market_value": "1799.65"},
        ],
        "result": {"data": [{"wallet_balance_after_haircut": "16799.65"}]},
    }
    portfolio_summary = {
        "total_usd": 84.91,
        "total_assets_usd": 84.91,
        "total_collateral_usd": 84.91,
        "total_borrowed_usd": 0.0,
        "portfolio_value_source": "derived:collateral_minus_borrowed",
        "balances": [{"currency": "USD", "balance": 84.91, "usd_value": 84.91}],
    }
    quantity_report = {
        "missing_in_portfolio": [{"symbol": "BTC", "live_qty": 1.0, "accounts": ["MARGIN"]}],
        "missing_in_live": [],
        "mismatched_quantities": [],
    }

    mock_db = MagicMock()
    with patch("app.database.SessionLocal", return_value=mock_db), patch(
        "app.jarvis.mvp.wallet_reconciliation._fetch_live_account_summary",
        return_value=(account_summary, None),
    ), patch(
        "app.jarvis.mvp.wallet_reconciliation.get_portfolio_summary",
        return_value=portfolio_summary,
    ), patch(
        "app.jarvis.mvp.wallet_reconciliation.reconcile_portfolio_balances",
        return_value=quantity_report,
    ), patch(
        "app.jarvis.mvp.wallet_reconciliation.get_crypto_prices",
        return_value={"BTC": 15000.0},
    ):
        result = reconcile_crypto_wallet_vs_dashboard()

    assert result["status"] == "mismatch"
    assert result["crypto_com_total_usd"] == 16799.65
    assert result["dashboard_total_usd"] == 84.91
    assert result["difference_usd"] == pytest.approx(16714.74, rel=0.01)
    assert result["read_only"] is True


def test_missing_btc_in_dashboard():
    account_summary = {
        "accounts": [{"currency": "BTC", "balance": "0.5", "market_value": "30000"}],
    }
    portfolio_summary = {
        "total_usd": 0.0,
        "total_assets_usd": 0.0,
        "total_collateral_usd": 0.0,
        "total_borrowed_usd": 0.0,
        "portfolio_value_source": "derived:collateral_minus_borrowed",
        "balances": [],
    }

    mock_db = MagicMock()
    with patch("app.database.SessionLocal", return_value=mock_db), patch(
        "app.jarvis.mvp.wallet_reconciliation._fetch_live_account_summary",
        return_value=(account_summary, None),
    ), patch(
        "app.jarvis.mvp.wallet_reconciliation.get_portfolio_summary",
        return_value=portfolio_summary,
    ), patch(
        "app.jarvis.mvp.wallet_reconciliation.reconcile_portfolio_balances",
        return_value={"missing_in_portfolio": [], "missing_in_live": [], "mismatched_quantities": []},
    ), patch(
        "app.jarvis.mvp.wallet_reconciliation.get_crypto_prices",
        return_value={"BTC": 60000.0},
    ):
        result = reconcile_crypto_wallet_vs_dashboard()

    btc = next(row for row in result["asset_comparison"] if row["coin"] == "BTC")
    assert btc["issue"] == "missing_in_dashboard"


def test_price_mismatch_detection():
    account_summary = {
        "accounts": [{"currency": "ETH", "balance": "10", "market_value": "30000"}],
    }
    portfolio_summary = {
        "total_usd": 10000.0,
        "total_assets_usd": 10000.0,
        "total_collateral_usd": 10000.0,
        "total_borrowed_usd": 0.0,
        "portfolio_value_source": "exchange:wallet_balance",
        "balances": [{"currency": "ETH", "balance": 10.0, "usd_value": 10000.0}],
    }

    mock_db = MagicMock()
    with patch("app.database.SessionLocal", return_value=mock_db), patch(
        "app.jarvis.mvp.wallet_reconciliation._fetch_live_account_summary",
        return_value=(account_summary, None),
    ), patch(
        "app.jarvis.mvp.wallet_reconciliation.get_portfolio_summary",
        return_value=portfolio_summary,
    ), patch(
        "app.jarvis.mvp.wallet_reconciliation.reconcile_portfolio_balances",
        return_value={"missing_in_portfolio": [], "missing_in_live": [], "mismatched_quantities": []},
    ), patch(
        "app.jarvis.mvp.wallet_reconciliation.get_crypto_prices",
        return_value={"ETH": 3000.0},
    ):
        result = reconcile_crypto_wallet_vs_dashboard()

    eth = next(row for row in result["asset_comparison"] if row["coin"] == "ETH")
    assert eth["issue"] == "price_mismatch"


def test_api_failure_returns_failed_safe():
    portfolio_summary = {
        "total_usd": 84.91,
        "total_assets_usd": 187.48,
        "total_collateral_usd": 187.48,
        "total_borrowed_usd": 102.57,
        "portfolio_value_source": "derived:collateral_minus_borrowed",
        "balances": [{"currency": "USD", "balance": 84.91, "usd_value": 84.91}],
    }
    mock_db = MagicMock()
    with patch("app.database.SessionLocal", return_value=mock_db), patch(
        "app.jarvis.mvp.wallet_reconciliation._fetch_live_account_summary",
        return_value=({"skipped": True, "reason": "missing credentials"}, "missing credentials"),
    ), patch(
        "app.jarvis.mvp.wallet_reconciliation.get_portfolio_summary",
        return_value=portfolio_summary,
    ), patch(
        "app.jarvis.mvp.wallet_reconciliation.get_crypto_prices",
        return_value={},
    ):
        result = reconcile_crypto_wallet_vs_dashboard()

    assert result["status"] == "mismatch"
    assert result["dashboard_total_usd"] == 84.91
    assert result["crypto_com_total_usd"] == 187.48
    assert result["live_api_available"] is False
    assert "credentials" in result.get("error", "").lower()


def test_run_readonly_tool_does_not_write():
    with patch(
        "app.jarvis.mvp.tools.reconcile_crypto_wallet_vs_dashboard",
        return_value={"tool": "reconcile_crypto_wallet_vs_dashboard", "status": "pass", "read_only": True},
    ) as mock_reconcile:
        out = run_readonly_tool("reconcile_crypto_wallet_vs_dashboard")
    mock_reconcile.assert_called_once()
    assert out["success"] is True
    assert out["read_only"] is True


def test_jarvis_task_endpoint_routes_wallet_reconcile(client, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_DRY_RUN_ONLY", "true")
    monkeypatch.setattr("app.jarvis.mvp.agents.ask_bedrock", lambda _prompt: "")

    fake_result = {
        "tool": "reconcile_crypto_wallet_vs_dashboard",
        "status": "mismatch",
        "crypto_com_total_usd": 16799.65,
        "dashboard_total_usd": 84.91,
        "difference_usd": 16714.74,
        "difference_pct": 99.49,
        "asset_comparison": [],
        "probable_root_causes": ["BTC missing in dashboard cache"],
        "recommended_next_steps": ["Refresh portfolio cache"],
        "read_only": True,
    }

    with patch("app.jarvis.mvp.tools.reconcile_crypto_wallet_vs_dashboard", return_value=fake_result):
        response = client.post(
            "/api/jarvis/task",
            json={
                "task": "reconcile Crypto.com wallet balance with dashboard portfolio balance",
                "dry_run": True,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert any(
        r.get("tool") == "reconcile_crypto_wallet_vs_dashboard" for r in body.get("tool_results") or []
    )
    assert "16799.65" in body["final_answer"] or "16,799.65" in body["final_answer"]
