"""Tests for Jarvis AWS Auditor agent (read-only)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.jarvis.mvp.aws_auditor import compile_audit_findings, is_aws_audit_task, run_aws_audit
from app.jarvis.mvp.risk import classify_task_risk


def test_is_aws_audit_task():
    assert is_aws_audit_task("Run AWS infrastructure audit") is True
    assert is_aws_audit_task("check dashboard health") is False


def test_aws_audit_task_is_low_risk():
    assert classify_task_risk("Run AWS infrastructure audit") == "low"


def test_compile_audit_findings_from_mock_tools():
    tool_results = [
        {
            "tool": "get_ec2_inventory",
            "success": True,
            "stopped_count": 2,
            "untagged_count": 1,
        },
        {
            "tool": "get_ebs_inventory",
            "success": True,
            "unattached_count": 3,
            "estimated_monthly_waste_usd": 12.5,
        },
        {
            "tool": "get_eip_inventory",
            "success": True,
            "unattached_count": 1,
            "estimated_monthly_waste_usd": 3.65,
        },
        {
            "tool": "get_security_group_inventory",
            "success": True,
            "risky_count": 1,
        },
    ]
    out = compile_audit_findings(tool_results)
    assert out["estimated_monthly_savings"] == pytest.approx(16.15)
    assert len(out["cost_findings"]) >= 2
    assert len(out["security_findings"]) == 1
    assert out["summary"]["read_only"] is True


@patch("app.jarvis.mvp.aws_auditor.run_aws_auditor_tool")
def test_run_aws_audit_invokes_all_tools(mock_tool):
    mock_tool.return_value = {"tool": "mock", "success": True}
    results, findings = run_aws_audit()
    assert len(results) == 7
    assert mock_tool.call_count == 7
    assert "summary" in findings


def test_aws_audit_service_persists_audit_id(monkeypatch):
    from app.jarvis.mvp.graph import reset_jarvis_graph_cache
    from app.jarvis.mvp.service import run_jarvis_task

    reset_jarvis_graph_cache()
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_DRY_RUN_ONLY", "true")
    monkeypatch.setattr("app.jarvis.mvp.agents.ask_bedrock", lambda _prompt: "")

    mock_findings = {
        "summary": {"read_only": True, "tools_succeeded": 7, "tools_executed": 7},
        "cost_findings": [{"severity": "medium", "finding": "test"}],
        "security_findings": [],
        "resource_findings": [],
        "recommendations": ["Review stopped instances."],
        "estimated_monthly_savings": 10.0,
    }

    with patch("app.jarvis.mvp.agents.run_aws_audit") as mock_audit:
        mock_audit.return_value = ([{"tool": "get_ec2_inventory", "success": True}], mock_findings)
        with patch("app.jarvis.mvp.service.record_task_started"):
            with patch("app.jarvis.mvp.service.record_task_completed"):
                with patch("app.jarvis.mvp.service.record_audit_run", return_value="audit-test-id"):
                    out = run_jarvis_task("Run AWS infrastructure audit", dry_run=True)

    assert out["status"] == "completed"
    assert out["risk_level"] == "low"
    assert out.get("audit_id") == "audit-test-id"
    assert "read-only" in out["final_answer"].lower()
    reset_jarvis_graph_cache()
