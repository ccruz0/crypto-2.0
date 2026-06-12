"""Tests for Jarvis automation incident dispatch endpoint."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes_monitoring import router as monitoring_router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(monitoring_router, prefix="/api")
    return TestClient(app)


def test_jarvis_incident_requires_failures(client):
    response = client.post("/api/monitoring/jarvis-incident", json={})
    assert response.status_code == 200
    assert response.json()["ok"] is False


def test_jarvis_incident_creates_task_and_runs_scheduler(client):
    with patch("app.services.notion_tasks.create_incident_task") as mock_create, patch(
        "app.services.notion_tasks.update_notion_task_status"
    ) as mock_promote, patch(
        "app.services.agent_scheduler.run_agent_scheduler_cycle"
    ) as mock_cycle:
        mock_create.return_value = {"id": "task-abc-123"}
        mock_cycle.return_value = {"ok": True, "action": "prepared"}

        response = client.post(
            "/api/monitoring/jarvis-incident",
            json={
                "source": "jarvis-health-check",
                "category": "health_check",
                "failures": [{"name": "backend_ping_fast", "detail": "connection refused"}],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["notion_task_id"] == "task-abc-123"
    mock_create.assert_called_once()
    mock_promote.assert_called_once_with("task-abc-123", "ready-for-investigation")
    mock_cycle.assert_called_once_with(
        project="Infrastructure",
        task_id="task-abc-123",
        investigation_only=True,
    )
