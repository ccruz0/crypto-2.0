"""Tests for Jarvis tool classification and orchestration-aware improvement logic."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.api.routes_jarvis import router as jarvis_router
from app.database import (
    ensure_jarvis_execution_log_table,
    ensure_jarvis_investigations_table,
    ensure_jarvis_task_runs_table,
)
from app.jarvis.execution import audit as audit_mod
from app.jarvis.improvement.recommendation_engine import (
    get_improvement_quality,
    get_improvement_recommendations,
)
from app.jarvis.improvement.recommendation_ranker import (
    filter_suppressed_recommendations,
    is_workflow_deprecation_recommendation,
    rank_backlog,
)
from app.jarvis.improvement.tool_classification import (
    classify_tool,
    get_assessment_display,
    is_workflow_measured_tool,
    should_suppress_workflow_recommendation as classify_should_suppress,
)
from app.jarvis.improvement.tool_effectiveness import analyze_tool_effectiveness
from app.jarvis.analytics.aggregation import aggregate_tool_metrics, fetch_all_investigations, fetch_execution_logs
from app.jarvis.investigations.investigation_types import InvestigationStatus


def _now_iso(days_ago: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


_ORCHESTRATION_TOOLS = ("submit", "build_plan", "investigate_objective", "validate_result")


@pytest.fixture()
def classification_db(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    ensure_jarvis_investigations_table(engine)
    ensure_jarvis_task_runs_table(engine)
    ensure_jarvis_execution_log_table(engine)
    monkeypatch.setattr("app.database.engine", engine)
    monkeypatch.setattr(audit_mod, "engine", engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def classification_client(classification_db, monkeypatch):
    monkeypatch.setattr("app.database.engine", classification_db)
    app = FastAPI()
    app.include_router(jarvis_router)
    return TestClient(app)


def _insert_investigation(conn, investigation_id: str, **kwargs) -> None:
    defaults = {
        "investigation_id": investigation_id,
        "objective": f"Investigate {investigation_id}",
        "category": "orders",
        "template_id": "open_orders_empty",
        "status": InvestigationStatus.COMPLETED.value,
        "summary": "Test",
        "root_cause": "Trigger order API failure blocks cache updates",
        "confidence": 75.0,
        "evidence_json": json.dumps([{"source": "db", "detail": "ok"}]),
        "recommended_fix": "Fix",
        "impact": "High",
        "ranked_causes_json": "[]",
        "verification_steps_json": "[]",
        "next_action": "Propose",
        "proposal_task_id": None,
        "proposal_status": None,
        "created_at": _now_iso(),
    }
    defaults.update(kwargs)
    conn.execute(
        text(
            """
            INSERT INTO jarvis_investigations (
                investigation_id, objective, category, template_id, status,
                summary, root_cause, confidence, evidence_json,
                recommended_fix, impact, ranked_causes_json,
                verification_steps_json, next_action,
                proposal_task_id, proposal_status, created_at
            ) VALUES (
                :investigation_id, :objective, :category, :template_id, :status,
                :summary, :root_cause, :confidence, :evidence_json,
                :recommended_fix, :impact, :ranked_causes_json,
                :verification_steps_json, :next_action,
                :proposal_task_id, :proposal_status, :created_at
            )
            """
        ),
        defaults,
    )


def _seed_orchestration_scenario(engine) -> None:
    """Seed investigations plus orchestration tool logs that previously triggered low-utility recs."""
    with engine.begin() as conn:
        for idx in range(12):
            _insert_investigation(
                conn,
                f"inv-orch-{idx}",
                template_id="open_orders_empty" if idx % 2 == 0 else "generic",
                status=InvestigationStatus.COMPLETED.value if idx < 8 else InvestigationStatus.FAILED.value,
                confidence=70.0 if idx < 8 else 20.0,
            )
        for idx in range(5):
            _insert_investigation(
                conn,
                f"inv-insuff-{idx}",
                template_id="generic",
                status=InvestigationStatus.INSUFFICIENT_EVIDENCE.value,
                confidence=10.0,
                root_cause="",
            )

    for idx in range(15):
        task_id = f"task-orch-{idx}"
        for tool in _ORCHESTRATION_TOOLS:
            audit_mod.log_execution_event(
                task_id=task_id,
                agent="service" if tool == "submit" else "planner_agent",
                tool=tool,
                input_summary="objective",
                output_summary="ok" if idx < 12 else "error: timeout",
                duration_ms=100 if tool != "investigate_objective" else 6000,
                metadata={"ok": idx < 12, "error": "timeout" if idx >= 12 else None},
            )


class TestToolClassification:
    def test_orchestration_tools_classified(self):
        assert classify_tool("submit") == "execution"
        assert classify_tool("build_plan") == "orchestration"
        assert classify_tool("investigate_objective") == "orchestration"
        assert classify_tool("validate_result") == "validation"
        assert is_workflow_measured_tool("build_plan")
        assert is_workflow_measured_tool("validate_result")
        assert not is_workflow_measured_tool("diagnose_open_orders")

    def test_diagnostic_and_collector_tools(self):
        assert classify_tool("diagnose_open_orders") == "diagnostic"
        assert classify_tool("read_logs") == "collector"
        assert get_assessment_display("orchestration") == "Workflow Tool"
        assert get_assessment_display("validation") == "Validation Tool"
        assert get_assessment_display("collector") == "Collector"
        assert get_assessment_display("diagnostic") == "Diagnostic Tool"

    def test_unknown_tool_defaults_to_diagnostic(self):
        assert classify_tool("unknown_future_tool") == "diagnostic"


class TestSuppressionRules:
    def test_suppresses_low_utility_workflow_recommendations(self):
        rec = {
            "id": "tool-low-utility-build_plan",
            "category": "tool_effectiveness",
            "title": "Review 'build_plan' tool priority",
            "recommendation": "Lower priority or remove from some templates.",
        }
        assert classify_should_suppress(rec)
        assert is_workflow_deprecation_recommendation(rec)

    def test_keeps_diagnostic_low_utility_recommendations(self):
        rec = {
            "id": "tool-low-utility-search_logs",
            "category": "tool_effectiveness",
            "title": "Review 'search_logs' tool priority",
            "recommendation": "Lower priority or remove from some templates.",
        }
        assert not classify_should_suppress(rec)

    def test_suppresses_read_logs_deprecation(self):
        rec = {
            "id": "tool-low-utility-read_logs",
            "category": "tool_effectiveness",
            "title": "Review 'read_logs' tool priority",
            "recommendation": "Lower priority or remove from some templates.",
        }
        assert classify_should_suppress(rec)

    def test_keeps_workflow_failure_recommendations(self):
        rec = {
            "id": "tool-failure-build_plan",
            "category": "tool_effectiveness",
            "title": "Investigate abnormal failure rate for workflow tool 'build_plan'",
            "recommendation": "Review error handling and retry logic for this mandatory workflow step.",
        }
        assert not classify_should_suppress(rec)

    def test_filter_suppressed_count(self):
        items = [
            {"id": "tool-low-utility-submit", "category": "tool_effectiveness", "recommendation": "remove tool"},
            {"id": "template-gap", "category": "template_gap", "recommendation": "Add template"},
        ]
        kept, suppressed = filter_suppressed_recommendations(items)
        assert len(kept) == 1
        assert suppressed == 1


class TestOrchestrationMetrics:
    def test_workflow_tools_have_orchestration_metrics(self, classification_db):
        _seed_orchestration_scenario(classification_db)
        investigations = fetch_all_investigations()
        logs = fetch_execution_logs()
        tool_metrics = aggregate_tool_metrics(logs, investigations)
        analysis = analyze_tool_effectiveness(tool_metrics, investigations)

        build_plan = next(r for r in analysis["tools"] if r["tool"] == "build_plan")
        assert build_plan["category"] == "orchestration"
        assert build_plan["assessment_display"] == "Workflow Tool"
        assert "workflow_usage_rate" in build_plan
        assert "successful_completion_rate" in build_plan
        assert "failure_association_rate" in build_plan
        assert build_plan["assessment"] != "low_utility"

        diagnose = next((r for r in analysis["tools"] if r["tool"] == "diagnose_open_orders"), None)
        if diagnose:
            assert "utility_ratio" in diagnose
            assert "useful_findings" in diagnose
            assert "false_positive_contribution" in diagnose

    def test_no_deprecation_recs_for_orchestration_tools(self, classification_db):
        _seed_orchestration_scenario(classification_db)
        investigations = fetch_all_investigations()
        logs = fetch_execution_logs()
        tool_metrics = aggregate_tool_metrics(logs, investigations)
        analysis = analyze_tool_effectiveness(tool_metrics, investigations)

        for rec in analysis["recommendations"]:
            tool = rec["id"].replace("tool-low-utility-", "").replace("tool-failure-", "")
            if tool in _ORCHESTRATION_TOOLS:
                assert "remove" not in rec["recommendation"].lower()
                assert "lower priority" not in rec["recommendation"].lower()


class TestRankingBehavior:
    def test_orchestration_tools_not_top_priority(self, classification_db):
        _seed_orchestration_scenario(classification_db)
        result = get_improvement_recommendations()
        backlog = result["backlog"]
        assert len(backlog) >= 1

        top_five = backlog[:5]
        top_titles = " ".join(r["title"].lower() for r in top_five)
        for tool in _ORCHESTRATION_TOOLS:
            assert f"'{tool}'" not in top_titles or "abnormal" in top_titles or "failure" in top_titles

        high_priority = [r for r in backlog if r["priority"] == "high"]
        for rec in high_priority:
            assert "tool-low-utility" not in rec["id"] or not any(
                rec["id"].endswith(t) for t in _ORCHESTRATION_TOOLS
            )

    def test_template_gaps_rank_above_workflow_deprecation(self, classification_db):
        _seed_orchestration_scenario(classification_db)
        result = get_improvement_recommendations()
        backlog = result["backlog"]
        if len(backlog) >= 2:
            template_recs = [r for r in backlog if r["category"] == "template_gap"]
            if template_recs:
                first_template_idx = backlog.index(template_recs[0])
                workflow_deprecation = [
                    r for r in backlog if r["id"].startswith("tool-low-utility-") and any(
                        r["id"].endswith(t) for t in _ORCHESTRATION_TOOLS
                    )
                ]
                for dep in workflow_deprecation:
                    assert backlog.index(dep) > first_template_idx or dep not in backlog


class TestQualityEndpoint:
    def test_quality_service(self, classification_db):
        _seed_orchestration_scenario(classification_db)
        quality = get_improvement_quality()
        assert "quality_score" in quality
        assert quality["recommendation_count"] >= 0
        assert quality["suppressed_recommendations"] >= 0
        assert 0 <= quality["quality_score"] <= 100
        assert quality["read_only"] is True

    def test_quality_api_route(self, classification_client, classification_db):
        _seed_orchestration_scenario(classification_db)
        resp = classification_client.get("/api/jarvis/improvement/quality")
        assert resp.status_code == 200
        body = resp.json()
        assert body["quality_score"] >= 0
        assert "suppressed_recommendations" in body
        assert "evidence_coverage" in body
        assert body["read_only"] is True


class TestDashboardDataShape:
    def test_tools_response_includes_category_and_assessment(self, classification_client, classification_db):
        _seed_orchestration_scenario(classification_db)
        resp = classification_client.get("/api/jarvis/improvement/tools")
        assert resp.status_code == 200
        tools = resp.json()["tools"]
        assert len(tools) >= 1
        for row in tools:
            assert "category" in row
            assert "assessment_display" in row

        build_plan = next((t for t in tools if t["tool"] == "build_plan"), None)
        assert build_plan is not None
        assert build_plan["assessment_display"] == "Workflow Tool"
        assert build_plan.get("workflow_usage_rate") is not None
