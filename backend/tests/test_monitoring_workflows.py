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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

