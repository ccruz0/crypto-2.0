"""Tests for monitoring workflows API endpoints"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
import sys
import os

# Add backend to path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

from app.main import app

client = TestClient(app)


def test_get_workflows_returns_list():
    """Test that GET /api/monitoring/workflows returns a list of workflows"""
    response = client.get("/api/monitoring/workflows")
    assert response.status_code == 200
    # Ensure monitoring workflow status is never cached by browsers/proxies
    cache_control = (response.headers.get("cache-control") or "").lower()
    pragma = (response.headers.get("pragma") or "").lower()
    expires = (response.headers.get("expires") or "").lower()
    assert "no-store" in cache_control
    assert "no-cache" in cache_control
    assert "no-cache" in pragma
    assert expires in ("0", "")
    data = response.json()
    assert "workflows" in data
    assert isinstance(data["workflows"], list)
    assert len(data["workflows"]) > 0
    
    # Check that watchlist_consistency workflow is present
    watchlist_workflow = next(
        (w for w in data["workflows"] if w["id"] == "watchlist_consistency"),
        None
    )
    assert watchlist_workflow is not None
    assert watchlist_workflow["name"] == "Watchlist Consistency Check"
    assert "last_status" in watchlist_workflow
    assert "last_execution" in watchlist_workflow
    assert "last_report" in watchlist_workflow
    assert "run_endpoint" in watchlist_workflow


def test_get_workflows_includes_status():
    """Test that workflows include status field"""
    response = client.get("/api/monitoring/workflows")
    assert response.status_code == 200
    data = response.json()
    
    for workflow in data["workflows"]:
        assert "last_status" in workflow
        assert workflow["last_status"] in ["success", "error", "running", "unknown"]


def test_run_workflow_watchlist_consistency():
    """Test that POST /api/monitoring/workflows/watchlist_consistency/run returns success"""
    # This test verifies the endpoint structure and response format
    # We don't actually run the workflow in tests to avoid side effects
    import asyncio
    with patch.object(asyncio, "create_task") as mock_create_task:
        # Create a proper mock task object with the methods the endpoint uses
        # The endpoint calls task.add_done_callback() and checks task.done()
        mock_task = MagicMock()
        mock_task.done.return_value = False  # Task is not done yet
        mock_task.add_done_callback.return_value = None  # Callback registration is a no-op
        
        # Mock create_task to return the mock task object
        mock_create_task.return_value = mock_task
        
        response = client.post("/api/monitoring/workflows/watchlist_consistency/run")
        assert response.status_code == 200
        data = response.json()
        assert data["workflow_id"] == "watchlist_consistency"
        assert data["started"] is True
        assert "message" in data
        assert isinstance(data["message"], str)


def test_run_workflow_invalid_id():
    """Test that POST /api/monitoring/workflows/invalid_id/run returns 404"""
    response = client.post("/api/monitoring/workflows/invalid_id/run")
    assert response.status_code == 404
    data = response.json()
    assert "detail" in data
    assert "not found" in data["detail"].lower()


def test_run_workflow_no_endpoint():
    """Test that POST /api/monitoring/workflows/{id}/run returns 400 if workflow has no run_endpoint"""
    # Find a workflow without run_endpoint (like telegram_commands)
    workflows_response = client.get("/api/monitoring/workflows")
    workflows = workflows_response.json()["workflows"]
    
    workflow_without_endpoint = next(
        (w for w in workflows if not w.get("run_endpoint")),
        None
    )
    
    if workflow_without_endpoint:
        response = client.post(f"/api/monitoring/workflows/{workflow_without_endpoint['id']}/run")
        assert response.status_code == 400
        data = response.json()
        assert "detail" in data
        assert "cannot be run" in data["detail"].lower() or "no run endpoint" in data["detail"].lower()


def test_workflow_registry_exists():
    """Test that workflows registry module exists and can be imported"""
    from app.monitoring.workflows_registry import get_all_workflows, get_workflow_by_id
    
    workflows = get_all_workflows()
    assert isinstance(workflows, list)
    assert len(workflows) > 0
    
    # Test get_workflow_by_id
    workflow = get_workflow_by_id("watchlist_consistency")
    assert workflow is not None
    assert workflow["id"] == "watchlist_consistency"
    
    # Test invalid ID
    invalid_workflow = get_workflow_by_id("invalid_id")
    assert invalid_workflow is None


def test_get_workflows_includes_sl_tp_check_report_link():
    """SL/TP Check always exposes the dashboard report path even before first run."""
    response = client.get("/api/monitoring/workflows")
    assert response.status_code == 200
    workflows = response.json()["workflows"]
    sl_tp = next((w for w in workflows if w["id"] == "sl_tp_check"), None)
    assert sl_tp is not None
    assert sl_tp.get("run_endpoint")
    assert sl_tp.get("last_report") == "reports/sl-tp-check"


def test_sl_tp_check_report_not_found_before_run():
    """Latest SL/TP report endpoint returns not_found when cache is empty."""
    import app.api.routes_monitoring as monitoring

    prev = monitoring._sl_tp_check_report_cache
    try:
        monitoring._sl_tp_check_report_cache = None
        response = client.get("/api/monitoring/reports/sl-tp-check/latest")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "not_found"
    finally:
        monitoring._sl_tp_check_report_cache = prev


def test_store_sl_tp_check_report_serializes_entry_order():
    """Report store keeps order_id so Create SL/TP buttons can call create-protection-smart."""
    from app.api.routes_monitoring import (
        store_sl_tp_check_report_from_result,
        SL_TP_CHECK_REPORT_PATH,
    )
    import app.api.routes_monitoring as monitoring

    prev = monitoring._sl_tp_check_report_cache
    try:
        path = store_sl_tp_check_report_from_result(
            {
                "checked_at": "2026-08-04T01:00:00+00:00",
                "total_positions": 2,
                "oco_issues": {},
                "positions_missing_sl_tp": [
                    {
                        "symbol": "ETH_USD",
                        "currency": "ETH",
                        "balance": -0.05,
                        "has_sl": False,
                        "has_tp": True,
                        "order_id": "ord-123",
                        "quantity": 0.05,
                        "side": "SELL",
                        "entry_price": 3000.0,
                        "current_price": 2950.0,
                        "uncovered_qty": 0.05,
                    }
                ],
            },
            reminder_sent=True,
            db=None,
        )
        assert path == SL_TP_CHECK_REPORT_PATH
        response = client.get("/api/monitoring/reports/sl-tp-check/latest")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        report = data["report"]
        assert report["missing_count"] == 1
        assert report["reminder_sent"] is True
        row = report["positions_missing"][0]
        assert row["symbol"] == "ETH_USD"
        assert row["order_id"] == "ord-123"
        assert row["has_sl"] is False
        assert row["has_tp"] is True
        assert row["side"] == "SELL"
        assert row["current_price"] == 2950.0
        assert row["uncovered_qty"] == 0.05
        assert row["entry_price"] == 3000.0
        assert row["balance"] == -0.05
    finally:
        monitoring._sl_tp_check_report_cache = prev


def test_run_workflow_sl_tp_check_starts():
    """POST sl_tp_check/run starts background work without blocking."""
    import asyncio

    with patch.object(asyncio, "create_task") as mock_create_task:
        mock_task = MagicMock()
        mock_task.done.return_value = False
        mock_task.add_done_callback.return_value = None
        mock_create_task.return_value = mock_task

        response = client.post("/api/monitoring/workflows/sl_tp_check/run")
        assert response.status_code == 200
        data = response.json()
        assert data["workflow_id"] == "sl_tp_check"
        assert data["started"] is True
        mock_create_task.assert_called_once()


def test_refresh_sl_tp_check_report_rescans_without_reminder():
    """POST refresh re-runs scanner, stores report, does not send Telegram reminder."""
    import app.api.routes_monitoring as monitoring

    prev = monitoring._sl_tp_check_report_cache
    try:
        monitoring._sl_tp_check_report_cache = {
            "stored_at": "2026-08-05T01:00:00+00:00",
            "report": {
                "workflow": "sl_tp_check",
                "checked_at": "2026-08-05T01:00:00+00:00",
                "total_positions": 1,
                "missing_count": 1,
                "positions_missing": [
                    {
                        "symbol": "ETH_USD",
                        "has_sl": True,
                        "has_tp": False,
                        "order_id": "stale",
                        "uncovered_qty": 0.05,
                    }
                ],
                "oco_issues": {},
                "reminder_sent": True,
                "error": None,
            },
        }

        with patch(
            "app.services.sl_tp_checker.sl_tp_checker_service.check_positions_for_sl_tp"
        ) as mock_check, patch(
            "app.services.sl_tp_checker.sl_tp_checker_service.send_sl_tp_reminder"
        ) as mock_remind:
            mock_check.return_value = {
                "checked_at": "2026-08-05T05:30:00+00:00",
                "total_positions": 2,
                "oco_issues": {},
                "positions_missing_sl_tp": [],
            }
            response = client.post("/api/monitoring/reports/sl-tp-check/refresh")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert data.get("refreshed") is True
            assert data["report"]["missing_count"] == 0
            assert data["report"]["positions_missing"] == []
            assert data["report"]["reminder_sent"] is False
            mock_check.assert_called_once()
            mock_remind.assert_not_called()
    finally:
        monitoring._sl_tp_check_report_cache = prev

