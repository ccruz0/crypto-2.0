"""Tests for Jarvis Crypto Auditor agent (read-only)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.jarvis.mvp.crypto_auditor import (
    compile_crypto_audit_findings,
    is_crypto_audit_task,
    run_crypto_audit,
)
from app.jarvis.mvp.risk import classify_task_risk
from app.jarvis.mvp.telegram_crypto_alerts import _should_alert, format_crypto_alert


def test_is_crypto_audit_task():
    assert is_crypto_audit_task("Run crypto audit") is True
    assert is_crypto_audit_task("Audit portfolio") is True
    assert is_crypto_audit_task("Compare exchange and dashboard") is True
    assert is_crypto_audit_task("Run AWS infrastructure audit") is False


def test_crypto_audit_task_is_low_risk():
    assert classify_task_risk("Run crypto audit") == "low"


def test_compile_crypto_audit_findings_mismatch():
    tool_results = [
        {
            "tool": "get_exchange_wallet",
            "success": True,
            "total_usd": 10000.0,
            "assets": [{"currency": "BTC", "balance": 0.5, "value_usd": 10000.0}],
        },
        {
            "tool": "get_dashboard_portfolio",
            "success": True,
            "total_usd": 8000.0,
            "balances": [{"currency": "BTC", "balance": 0.5, "value_usd": 8000.0}],
        },
        {"tool": "get_open_positions", "success": True, "open_position_count": 0},
        {"tool": "get_portfolio_cache", "success": True, "potentially_stale": False},
        {"tool": "get_trade_history_summary", "success": True, "filled_buy_count": 1, "filled_sell_count": 1},
        {"tool": "get_price_feed_status", "success": True, "potentially_stale": False, "symbol_count": 50},
    ]
    out = compile_crypto_audit_findings(tool_results)
    assert out["portfolio_difference_usd"] == pytest.approx(2000.0)
    assert out["portfolio_difference_pct"] == pytest.approx(20.0)
    assert out["summary"]["reconciliation_status"] in ("mismatch", "critical")
    assert len(out["wallet_findings"]) >= 1
    assert out["summary"]["read_only"] is True


def test_compile_crypto_audit_findings_missing_asset():
    tool_results = [
        {
            "tool": "get_exchange_wallet",
            "success": True,
            "total_usd": 500.0,
            "assets": [{"currency": "ETH", "balance": 1.0, "value_usd": 500.0}],
        },
        {
            "tool": "get_dashboard_portfolio",
            "success": True,
            "total_usd": 0.0,
            "balances": [],
        },
        {"tool": "get_open_positions", "success": True},
        {"tool": "get_portfolio_cache", "success": True},
        {"tool": "get_trade_history_summary", "success": True},
        {"tool": "get_price_feed_status", "success": True, "symbol_count": 20},
    ]
    out = compile_crypto_audit_findings(tool_results)
    types = [f.get("type") for f in out["wallet_findings"]]
    assert "missing_asset" in types


@patch("app.jarvis.mvp.crypto_auditor.run_crypto_auditor_tool")
def test_run_crypto_audit_invokes_all_tools(mock_tool):
    mock_tool.return_value = {"tool": "mock", "success": True, "total_usd": 0}
    results, findings = run_crypto_audit()
    assert len(results) == 6
    assert mock_tool.call_count == 6
    assert "summary" in findings


def test_telegram_alert_threshold():
    audit_output = {
        "portfolio_difference_pct": 6.0,
        "portfolio_difference_usd": 600.0,
        "summary": {"exchange_total_usd": 10000, "dashboard_total_usd": 9400, "total_findings": 1},
        "wallet_findings": [],
        "valuation_findings": [],
        "recommendations": ["Review manually."],
    }
    should, reason = _should_alert(audit_output)
    assert should is True
    assert "6.0%" in reason
    message = format_crypto_alert(audit_output)
    assert "CRYPTO AUDITOR ALERT" in message
    assert "Read-only alert" in message


def test_crypto_audit_service_persists_audit_id(monkeypatch):
    from app.jarvis.mvp.graph import reset_jarvis_graph_cache
    from app.jarvis.mvp.service import run_jarvis_task

    reset_jarvis_graph_cache()
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_DRY_RUN_ONLY", "true")
    monkeypatch.setattr("app.jarvis.mvp.agents.ask_bedrock", lambda _prompt: "")

    mock_findings = {
        "summary": {
            "read_only": True,
            "tools_succeeded": 6,
            "tools_executed": 6,
            "exchange_total_usd": 1000.0,
            "dashboard_total_usd": 950.0,
            "reconciliation_status": "mismatch",
            "total_findings": 1,
        },
        "wallet_findings": [{"type": "balance_mismatch", "severity": "high"}],
        "position_findings": [],
        "valuation_findings": [],
        "price_feed_findings": [],
        "recommendations": ["Review cache."],
        "portfolio_difference_usd": 50.0,
        "portfolio_difference_pct": 5.0,
    }

    with patch("app.jarvis.mvp.agents.run_crypto_audit", return_value=([], mock_findings)):
        with patch("app.jarvis.mvp.service.record_crypto_audit_run", return_value="crypto-audit-123"):
            with patch("app.jarvis.mvp.service.send_crypto_audit_alert", return_value=False):
                out = run_jarvis_task("Run crypto audit", dry_run=True)

    assert out.get("crypto_audit_id") == "crypto-audit-123"
    assert out.get("crypto_audit_output") is not None
    assert "crypto portfolio audit" in out.get("final_answer", "").lower()
