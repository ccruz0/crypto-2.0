"""Tests for Jarvis LangGraph MVP task endpoint and risk classification."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes_jarvis import router as jarvis_router
from app.jarvis.mvp.graph import reset_jarvis_graph_cache
from app.jarvis.mvp.risk import classify_task_risk
from app.jarvis.mvp.service import run_jarvis_task


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
        ("check dashboard health and summarize status", "low"),
        ("read runtime status for the backend", "low"),
        ("estimate aws cost for last week", "low"),
        ("summarize recent application logs", "low"),
        ("propose restart for the backend service", "medium"),
        ("propose config changes to runtime env", "medium"),
        ("propose deployment changes to production", "medium"),
        ("delete the s3 bucket resource", "high"),
        ("terminate the ec2 instance immediately", "high"),
        ("execute a real trade order now", "high"),
        ("modify IAM policy for production role", "high"),
        ("change secrets in production", "high"),
        ("delete old AWS resources and terminate stopped instances", "high"),
    ],
)
def test_classify_task_risk(task: str, expected: str):
    assert classify_task_risk(task) == expected


def test_high_risk_task_requires_approval(client, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_DRY_RUN_ONLY", "true")
    monkeypatch.setattr("app.jarvis.mvp.agents.ask_bedrock", lambda _prompt: "")

    response = client.post(
        "/api/jarvis/task",
        json={"task": "terminate the ec2 instance in production", "dry_run": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "requires_approval"
    assert body["risk_level"] == "high"
    assert body["plan"] == []
    assert body["tool_results"] == []
    assert "approval" in body["final_answer"].lower()


def test_low_risk_task_completes_with_readonly_tools(client, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_DRY_RUN_ONLY", "true")
    monkeypatch.setattr("app.jarvis.mvp.agents.ask_bedrock", lambda _prompt: "")

    response = client.post(
        "/api/jarvis/task",
        json={"task": "check dashboard health and runtime status", "dry_run": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["risk_level"] == "low"
    assert len(body["plan"]) >= 1
    assert len(body["tool_results"]) >= 1
    assert body["estimated_cost_usd"] >= 0.0
    assert body["review"]["approved"] is True


def test_jarvis_disabled_returns_failed(monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "false")
    out = run_jarvis_task("check health", dry_run=True)
    assert out["status"] == "failed"
    assert "disabled" in out["final_answer"].lower()


def test_dry_run_only_blocks_non_dry_run(monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_DRY_RUN_ONLY", "true")
    out = run_jarvis_task("check health", dry_run=False)
    assert out["status"] == "requires_approval"


def test_readonly_tool_allowlist(monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_DRY_RUN_ONLY", "true")
    monkeypatch.setattr("app.jarvis.mvp.agents.ask_bedrock", lambda _prompt: "")

    with patch("app.jarvis.mvp.agents.run_readonly_tool") as mock_tool:
        mock_tool.return_value = {"success": True, "tool": "get_runtime_status"}
        out = run_jarvis_task("read runtime status", dry_run=True)
    assert out["status"] == "completed"
    called_tools = [call.args[0] for call in mock_tool.call_args_list]
    assert all(tool in {"get_runtime_status", "check_dashboard_health"} or tool for tool in called_tools)
