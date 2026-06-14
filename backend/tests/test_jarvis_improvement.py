"""Tests for Jarvis Phase 4D self-improvement recommendation engine."""

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
from app.jarvis.execution import persistence as persist_mod
from app.jarvis.improvement.recommendation_ranker import (
    compute_priority_score,
    filter_suppressed_recommendations,
    rank_backlog,
    rank_priority,
)
from app.jarvis.improvement.recommendation_engine import (
    get_improvement_quality,
    get_improvement_recommendations,
    get_improvement_templates,
    get_improvement_tools,
    get_improvement_trends,
)
from app.jarvis.improvement.template_gap_analysis import analyze_template_gaps
from app.jarvis.improvement.tool_effectiveness import analyze_tool_effectiveness
from app.jarvis.improvement.quality_trends import analyze_quality_trends
from app.jarvis.analytics.aggregation import aggregate_root_cause_metrics, aggregate_template_metrics, aggregate_tool_metrics
from app.jarvis.investigations.investigation_types import InvestigationStatus


def _now_iso(days_ago: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _insert_investigation(
    conn,
    *,
    investigation_id: str,
    template_id: str = "open_orders_empty",
    status: str = InvestigationStatus.COMPLETED.value,
    root_cause: str = "Trigger order API failure blocks cache updates",
    confidence: float = 75.0,
    category: str = "orders",
    objective: str | None = None,
    proposal_status: str | None = None,
    proposal_task_id: str | None = None,
    created_at: str | None = None,
    evidence: list | None = None,
) -> None:
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
        {
            "investigation_id": investigation_id,
            "objective": objective or f"Investigate trigger order failure {investigation_id}",
            "category": category,
            "template_id": template_id,
            "status": status,
            "summary": "Test summary",
            "root_cause": root_cause,
            "confidence": confidence,
            "evidence_json": json.dumps(
                evidence or [{"source": "db", "reference": "orders", "detail": "count=1", "confidence": "high"}]
            ),
            "recommended_fix": "Apply cache fix",
            "impact": "Dashboard mismatch",
            "ranked_causes_json": "[]",
            "verification_steps_json": "[]",
            "next_action": "Propose patch",
            "proposal_task_id": proposal_task_id,
            "proposal_status": proposal_status,
            "created_at": created_at or _now_iso(),
        },
    )


def _insert_proposal_task(conn, *, task_id: str, investigation_id: str, status: str = "waiting_for_approval") -> None:
    plan = {
        "workflow_type": "phase4b_patch_proposal",
        "source_investigation_id": investigation_id,
        "fix_template_id": "orders.trigger_50001_cache_independent",
    }
    conn.execute(
        text(
            """
            INSERT INTO jarvis_task_runs (
                task_id, task, objective, status, risk_level, dry_run, priority,
                plan_json, artifacts_json, tool_results_json, review_json,
                approval_required, approval_status,
                estimated_cost_usd, actual_cost_usd,
                final_answer, error, started_at, completed_at, created_at
            ) VALUES (
                :task_id, :task, :objective, :status, 'low', 1, 'normal',
                :plan_json, '[]', '[]', '{}',
                1, :approval_status,
                0, 0,
                '', NULL, NULL, NULL, :created_at
            )
            """
        ),
        {
            "task_id": task_id,
            "task": "Proposal task",
            "objective": "Proposal for investigation",
            "status": status,
            "plan_json": json.dumps(plan),
            "approval_status": "pending",
            "created_at": _now_iso(),
        },
    )


@pytest.fixture()
def improvement_db(monkeypatch):
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
    monkeypatch.setattr("app.jarvis.investigations.persistence.engine", engine)
    monkeypatch.setattr(persist_mod, "engine", engine)
    monkeypatch.setattr(audit_mod, "engine", engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def improvement_client(improvement_db, monkeypatch):
    monkeypatch.setattr("app.database.engine", improvement_db)
    app = FastAPI()
    app.include_router(jarvis_router)
    return TestClient(app)


def _seed_improvement_data(engine) -> None:
    """Seed 20 investigations, 10 proposals, 5 failures, 5 insufficient_evidence."""
    with engine.begin() as conn:
        configs = [
            # 5 insufficient_evidence
            ("insuff", InvestigationStatus.INSUFFICIENT_EVIDENCE.value, "generic", "", 10.0, "generic"),
            ("insuff", InvestigationStatus.INSUFFICIENT_EVIDENCE.value, "generic", "", 12.0, "generic"),
            ("insuff", InvestigationStatus.INSUFFICIENT_EVIDENCE.value, "open_orders_empty", "", 8.0, "open_orders_empty"),
            ("insuff", InvestigationStatus.INSUFFICIENT_EVIDENCE.value, "dashboard_exchange_mismatch", "", 15.0, "dashboard_exchange_mismatch"),
            ("insuff", InvestigationStatus.INSUFFICIENT_EVIDENCE.value, "generic", "", 5.0, "generic"),
            # 5 failures (failed + partial_failure)
            ("fail", InvestigationStatus.FAILED.value, "deployment_unhealthy", "All mandatory collectors failed", 5.0, "deployment_unhealthy"),
            ("fail", InvestigationStatus.PARTIAL_FAILURE.value, "open_orders_empty", "Partial collector failure", 40.0, "open_orders_empty"),
            ("fail", InvestigationStatus.FAILED.value, "exchange_auth_failing", "Auth credential mismatch", 10.0, "exchange_auth_failing"),
            ("fail", InvestigationStatus.PARTIAL_FAILURE.value, "generic", "Partial failure on generic", 30.0, "generic"),
            ("fail", InvestigationStatus.FAILED.value, "portfolio_value_incorrect", "Portfolio sync failed", 8.0, "portfolio_value_incorrect"),
            # 10 completed (including false positives and recurring)
            ("ok", InvestigationStatus.COMPLETED.value, "open_orders_empty", "Trigger order API failure blocks cache updates", 80.0, "open_orders_empty"),
            ("ok", InvestigationStatus.COMPLETED.value, "open_orders_empty", "Trigger order API failure blocks cache updates", 75.0, "open_orders_empty"),
            ("ok", InvestigationStatus.COMPLETED.value, "dashboard_exchange_mismatch", "Dashboard correctly shows zero open orders", 90.0, "dashboard_exchange_mismatch"),
            ("ok", InvestigationStatus.COMPLETED.value, "open_orders_empty", "Crypto.com trigger order 50001 error", 70.0, "open_orders_empty"),
            ("ok", InvestigationStatus.COMPLETED.value, "generic", "No active dashboard/exchange mismatch detected", 85.0, "generic"),
            ("ok", InvestigationStatus.COMPLETED.value, "exchange_auth_failing", "Exchange auth credential mismatch", 65.0, "exchange_auth_failing"),
            ("ok", InvestigationStatus.COMPLETED.value, "portfolio_value_incorrect", "Portfolio equity derived from balances", 60.0, "portfolio_value_incorrect"),
            ("ok", InvestigationStatus.COMPLETED.value, "open_orders_empty", "Trigger order API failure blocks cache updates", 72.0, "open_orders_empty"),
            ("ok", InvestigationStatus.COMPLETED.value, "dashboard_exchange_mismatch", "No active dashboard/exchange mismatch detected", 88.0, "dashboard_exchange_mismatch"),
            ("ok", InvestigationStatus.COMPLETED.value, "open_orders_empty", "Missing trigger orders from Crypto.com sync", 68.0, "open_orders_empty"),
        ]

        for idx, (prefix, status, template_id, root, conf, tmpl) in enumerate(configs):
            _insert_investigation(
                conn,
                investigation_id=f"inv-4d-{idx}",
                template_id=template_id,
                status=status,
                root_cause=root,
                confidence=conf,
                category="orders" if "order" in template_id else "deployment" if "deployment" in template_id else "portfolio",
                created_at=_now_iso(days_ago=idx % 12),
            )

        for idx in range(10):
            inv_id = f"inv-proposal-4d-{idx}"
            task_id = f"task-proposal-4d-{idx}"
            proposal_status = [
                "waiting_for_approval",
                "approved",
                "no_fix_required",
                "failed",
                "rejected",
                "waiting_for_approval",
                "approved",
                "no_fix_required",
                "waiting_for_approval",
                "approved",
            ][idx]
            _insert_investigation(
                conn,
                investigation_id=inv_id,
                status=InvestigationStatus.COMPLETED.value,
                proposal_status=proposal_status,
                proposal_task_id=task_id,
                created_at=_now_iso(days_ago=idx),
            )
            _insert_proposal_task(conn, task_id=task_id, investigation_id=inv_id)

    for idx in range(5):
        audit_mod.log_execution_event(
            task_id=f"task-proposal-4d-{idx}",
            agent="executor",
            tool="inspect_repository" if idx % 2 == 0 else "read_logs",
            input_summary="diagnose",
            output_summary="ok" if idx < 3 else "error: timeout",
            duration_ms=1500 + idx * 100,
            metadata={"ok": idx < 3, "error": "timeout" if idx >= 3 else None},
        )


class TestRecommendationRanker:
    def test_priority_score_formula(self):
        score = compute_priority_score(impact="high", frequency=7, confidence=85.0)
        assert score > 0
        assert isinstance(score, float)

    def test_rank_priority_levels(self):
        assert rank_priority(60) == "high"
        assert rank_priority(25) == "medium"
        assert rank_priority(5) == "low"

    def test_backlog_sorted_descending(self):
        items = [
            {"title": "B", "priority_score": 10},
            {"title": "A", "priority_score": 50},
            {"title": "C", "priority_score": 30},
        ]
        ranked = rank_backlog(items)
        assert ranked[0]["priority_score"] == 50
        assert ranked[-1]["priority_score"] == 10

    def test_priority_scores_stable(self):
        s1 = compute_priority_score(impact="high", frequency=7, confidence=85.0)
        s2 = compute_priority_score(impact="high", frequency=7, confidence=85.0)
        assert s1 == s2


class TestTemplateGapAnalysis:
    def test_detects_generic_overuse(self, improvement_db):
        _seed_improvement_data(improvement_db)
        from app.jarvis.analytics.aggregation import fetch_all_investigations

        investigations = fetch_all_investigations()
        template_metrics = aggregate_template_metrics(investigations)
        analysis = analyze_template_gaps(investigations, template_metrics)
        assert analysis["summary"]["generic_investigations"] >= 3
        gap_types = {g["gap_type"] for g in analysis["gaps"]}
        assert "generic_overuse" in gap_types or "high_insufficient_evidence" in gap_types
        assert len(analysis["recommendations"]) >= 1

    def test_detects_trigger_order_gap(self, improvement_db):
        _seed_improvement_data(improvement_db)
        from app.jarvis.analytics.aggregation import fetch_all_investigations

        investigations = fetch_all_investigations()
        template_metrics = aggregate_template_metrics(investigations)
        analysis = analyze_template_gaps(investigations, template_metrics)
        rec_ids = {r["id"] for r in analysis["recommendations"]}
        assert "template-trigger-order-dedicated" in rec_ids or any("trigger" in r["title"].lower() for r in analysis["recommendations"])


class TestToolEffectiveness:
    def test_identifies_tool_metrics(self, improvement_db):
        _seed_improvement_data(improvement_db)
        from app.jarvis.analytics.aggregation import fetch_all_investigations, fetch_execution_logs

        investigations = fetch_all_investigations()
        logs = fetch_execution_logs()
        tool_metrics = aggregate_tool_metrics(logs, investigations)
        analysis = analyze_tool_effectiveness(tool_metrics, investigations)
        assert analysis["summary"]["tools_analyzed"] >= 1
        assert len(analysis["tools"]) >= 1

    def test_low_utility_detection(self, improvement_db):
        _seed_improvement_data(improvement_db)
        from app.jarvis.analytics.aggregation import fetch_all_investigations, fetch_execution_logs

        investigations = fetch_all_investigations()
        logs = fetch_execution_logs()
        tool_metrics = aggregate_tool_metrics(logs, investigations)
        analysis = analyze_tool_effectiveness(tool_metrics, investigations)
        for tool in analysis["tools"]:
            assert "utility_ratio" in tool
            assert "useful_outcomes" in tool
            assert "category" in tool
            assert "assessment_display" in tool
            assert tool["assessment"] in (
                "high_value",
                "low_utility",
                "unreliable",
                "moderate",
                "insufficient_data",
                "workflow_healthy",
                "workflow_active",
                "low_participation",
            )


class TestQualityTrends:
    def test_quality_trend_analysis(self, improvement_db):
        _seed_improvement_data(improvement_db)
        from app.jarvis.analytics.aggregation import fetch_all_investigations, fetch_execution_logs

        investigations = fetch_all_investigations()
        logs = fetch_execution_logs()
        root_causes = aggregate_root_cause_metrics(investigations)
        analysis = analyze_quality_trends(investigations, logs, root_causes)
        assert "overall" in analysis["quality_scores"]
        assert analysis["quality_scores"]["trend_direction"] in ("improving", "declining", "stable")
        assert analysis["open_orders_share_pct"] >= 0

    def test_recurring_incidents_detected(self, improvement_db):
        _seed_improvement_data(improvement_db)
        from app.jarvis.analytics.aggregation import fetch_all_investigations, fetch_execution_logs

        investigations = fetch_all_investigations()
        logs = fetch_execution_logs()
        root_causes = aggregate_root_cause_metrics(investigations)
        analysis = analyze_quality_trends(investigations, logs, root_causes)
        assert len(analysis["recurring_incidents"]) >= 1


class TestRecommendationEngine:
    def test_generates_recommendations(self, improvement_db):
        _seed_improvement_data(improvement_db)
        result = get_improvement_recommendations()
        assert result["read_only"] is True
        assert result["counts"]["total"] >= 1
        assert len(result["recommendations"]) >= 1
        assert len(result["backlog"]) == len(result["recommendations"])

    def test_backlog_ranked_correctly(self, improvement_db):
        _seed_improvement_data(improvement_db)
        result = get_improvement_recommendations()
        backlog = result["backlog"]
        scores = [r["priority_score"] for r in backlog]
        assert scores == sorted(scores, reverse=True)

    def test_all_recommendations_have_required_fields(self, improvement_db):
        _seed_improvement_data(improvement_db)
        result = get_improvement_recommendations()
        for rec in result["recommendations"]:
            assert rec["id"]
            assert rec["title"]
            assert rec["recommendation"]
            assert rec["priority"] in ("high", "medium", "low")
            assert rec["priority_score"] >= 0
            assert rec["expected_benefit"]


class TestImprovementAPI:
    def test_recommendations_route(self, improvement_client, improvement_db):
        _seed_improvement_data(improvement_db)
        resp = improvement_client.get("/api/jarvis/improvement/recommendations")
        assert resp.status_code == 200
        body = resp.json()
        assert body["read_only"] is True
        assert body["counts"]["total"] >= 1
        assert len(body["backlog"]) >= 1

    def test_templates_route(self, improvement_client, improvement_db):
        _seed_improvement_data(improvement_db)
        resp = improvement_client.get("/api/jarvis/improvement/templates")
        assert resp.status_code == 200
        body = resp.json()
        assert body["read_only"] is True
        assert "gaps" in body
        assert "template_metrics" in body

    def test_tools_route(self, improvement_client, improvement_db):
        _seed_improvement_data(improvement_db)
        resp = improvement_client.get("/api/jarvis/improvement/tools")
        assert resp.status_code == 200
        body = resp.json()
        assert body["read_only"] is True
        assert len(body["tools"]) >= 1

    def test_trends_route(self, improvement_client, improvement_db):
        _seed_improvement_data(improvement_db)
        resp = improvement_client.get("/api/jarvis/improvement/trends")
        assert resp.status_code == 200
        body = resp.json()
        assert body["read_only"] is True
        assert "quality_scores" in body
        assert "quality_score_daily" in body

    def test_read_only_all_routes(self, improvement_client, improvement_db):
        _seed_improvement_data(improvement_db)
        for path in (
            "/api/jarvis/improvement/recommendations",
            "/api/jarvis/improvement/templates",
            "/api/jarvis/improvement/tools",
            "/api/jarvis/improvement/trends",
            "/api/jarvis/improvement/quality",
        ):
            resp = improvement_client.get(path)
            assert resp.json().get("read_only") is True

    def test_service_functions(self, improvement_db):
        _seed_improvement_data(improvement_db)
        templates = get_improvement_templates()
        tools = get_improvement_tools()
        trends = get_improvement_trends()
        quality = get_improvement_quality()
        assert templates["read_only"] is True
        assert tools["read_only"] is True
        assert trends["read_only"] is True
        assert quality["read_only"] is True
        assert "quality_score" in quality

    def test_quality_route(self, improvement_client, improvement_db):
        _seed_improvement_data(improvement_db)
        resp = improvement_client.get("/api/jarvis/improvement/quality")
        assert resp.status_code == 200
        body = resp.json()
        assert body["read_only"] is True
        assert "quality_score" in body
        assert "suppressed_recommendations" in body
