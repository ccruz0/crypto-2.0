"""Tests for Jarvis Phase 4C investigation quality analytics."""

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
from app.jarvis.analytics.aggregation import (
    aggregate_investigation_metrics,
    aggregate_proposal_metrics,
    aggregate_template_metrics,
    compute_quality_score,
    is_false_positive,
    is_resolved_investigation,
)
from app.jarvis.execution import audit as audit_mod
from app.jarvis.execution import persistence as persist_mod
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
            "objective": f"Investigate {investigation_id}",
            "category": "orders",
            "template_id": template_id,
            "status": status,
            "summary": "Test summary",
            "root_cause": root_cause,
            "confidence": confidence,
            "evidence_json": json.dumps(evidence or [{"source": "db", "reference": "orders", "detail": "count=1", "confidence": "high"}]),
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
def analytics_db(monkeypatch):
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
def analytics_client(analytics_db, monkeypatch):
    monkeypatch.setattr("app.database.engine", analytics_db)
    app = FastAPI()
    app.include_router(jarvis_router)
    return TestClient(app)


def _seed_analytics_data(engine) -> None:
    with engine.begin() as conn:
        statuses = [
            (InvestigationStatus.COMPLETED.value, "Trigger order API failure blocks cache updates", 80.0),
            (InvestigationStatus.COMPLETED.value, "No active dashboard/exchange mismatch detected", 90.0),
            (InvestigationStatus.INSUFFICIENT_EVIDENCE.value, "", 10.0),
            (InvestigationStatus.PARTIAL_FAILURE.value, "Partial collector failure", 40.0),
            (InvestigationStatus.FAILED.value, "All mandatory collectors failed", 5.0),
            (InvestigationStatus.COMPLETED.value, "Trigger order API failure blocks cache updates", 70.0),
            (InvestigationStatus.COMPLETED.value, "Dashboard correctly shows zero open orders", 85.0),
            (InvestigationStatus.COMPLETED.value, "Exchange auth credential mismatch", 65.0),
            (InvestigationStatus.INSUFFICIENT_EVIDENCE.value, "", 15.0),
            (InvestigationStatus.COMPLETED.value, "Portfolio equity derived from balances", 60.0),
        ]
        templates = [
            "open_orders_empty",
            "dashboard_exchange_mismatch",
            "generic",
            "open_orders_empty",
            "deployment_unhealthy",
            "dashboard_exchange_mismatch",
            "open_orders_empty",
            "exchange_auth_failing",
            "generic",
            "portfolio_value_incorrect",
        ]
        for idx, ((status, root, conf), template_id) in enumerate(zip(statuses, templates)):
            _insert_investigation(
                conn,
                investigation_id=f"inv-analytics-{idx}",
                template_id=template_id,
                status=status,
                root_cause=root,
                confidence=conf,
                created_at=_now_iso(days_ago=idx % 10),
            )

        for idx in range(5):
            inv_id = f"inv-proposal-{idx}"
            task_id = f"task-proposal-{idx}"
            proposal_status = ["waiting_for_approval", "approved", "no_fix_required", "failed", "rejected"][idx]
            _insert_investigation(
                conn,
                investigation_id=inv_id,
                status=InvestigationStatus.COMPLETED.value,
                proposal_status=proposal_status,
                proposal_task_id=task_id,
                created_at=_now_iso(days_ago=idx),
            )
            _insert_proposal_task(conn, task_id=task_id, investigation_id=inv_id)

    audit_mod.log_execution_event(
        task_id="task-proposal-0",
        agent="proposal",
        tool="patch_generator",
        input_summary="generate patch",
        output_summary="patch ok",
        duration_ms=1200,
    )
    audit_mod.log_execution_event(
        task_id="task-proposal-1",
        agent="proposal",
        tool="patch_generator",
        input_summary="generate patch",
        output_summary="error: patch failed",
        duration_ms=800,
        metadata={"ok": False, "error": "patch apply failed"},
    )


class TestAnalyticsAggregation:
    def test_investigation_metrics_totals(self, analytics_db):
        _seed_analytics_data(analytics_db)
        from app.jarvis.analytics.aggregation import fetch_all_investigations

        rows = fetch_all_investigations()
        metrics = aggregate_investigation_metrics(rows)
        assert metrics["total_investigations"] == 15
        assert metrics["completed"] >= 7
        assert metrics["insufficient_evidence"] == 2
        assert metrics["partial_failure"] == 1
        assert metrics["failed"] == 1
        assert metrics["false_positives"] >= 1
        assert metrics["average_duration_ms"] > 0

    def test_template_statistics(self, analytics_db):
        _seed_analytics_data(analytics_db)
        from app.jarvis.analytics.aggregation import fetch_all_investigations

        rows = fetch_all_investigations()
        templates = aggregate_template_metrics(rows)
        assert len(templates) >= 4
        open_orders = next(t for t in templates if t["template_id"] == "open_orders_empty")
        assert open_orders["investigations"] >= 3
        assert 0 <= open_orders["completion_rate_pct"] <= 100
        assert open_orders["average_confidence"] > 0

    def test_proposal_statistics(self, analytics_db):
        _seed_analytics_data(analytics_db)
        from app.jarvis.analytics.aggregation import fetch_all_investigations, fetch_proposal_tasks

        investigations = fetch_all_investigations()
        tasks = fetch_proposal_tasks()
        proposals = aggregate_proposal_metrics(investigations, tasks)
        assert proposals["proposals_generated"] >= 5
        assert proposals["waiting_for_approval"] >= 1
        assert proposals["approved"] >= 1
        assert proposals["no_fix_required"] >= 1

    def test_quality_score_penalties(self):
        rows = [
            {"status": InvestigationStatus.COMPLETED.value},
            {"status": InvestigationStatus.FAILED.value},
            {"status": InvestigationStatus.INSUFFICIENT_EVIDENCE.value},
        ]
        score = compute_quality_score(rows, tool_errors=2)
        # penalties: 0 + 10 + 3 + 2 tool errors = 15 / 3 = 5 per inv => 95
        assert score == 95.0

    def test_quality_score_empty_data(self):
        assert compute_quality_score([]) == 100.0

    def test_resolved_and_false_positive_detection(self):
        resolved_row = {"status": InvestigationStatus.COMPLETED.value, "root_cause": "No active dashboard/exchange mismatch detected"}
        fp_row = {"status": InvestigationStatus.COMPLETED.value, "root_cause": "Dashboard correctly shows zero open orders", "confidence": 85, "evidence_json": []}
        assert is_resolved_investigation(resolved_row) is True
        assert is_false_positive(fp_row) is True


class TestAnalyticsAPI:
    def test_overview_route(self, analytics_client, analytics_db):
        _seed_analytics_data(analytics_db)
        resp = analytics_client.get("/api/jarvis/analytics/overview")
        assert resp.status_code == 200
        body = resp.json()
        assert body["investigations"]["total_investigations"] == 15
        assert "quality_score" in body
        assert body["quality_score"]["overall_score"] <= 100
        assert len(body["trends"]["last_7_days"]) == 7

    def test_templates_route(self, analytics_client, analytics_db):
        _seed_analytics_data(analytics_db)
        resp = analytics_client.get("/api/jarvis/analytics/templates")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] >= 4
        template_ids = {t["template_id"] for t in body["templates"]}
        assert "open_orders_empty" in template_ids
        ranked = body["templates"]
        assert ranked[0]["completion_rate_pct"] >= ranked[-1]["completion_rate_pct"] or ranked[0]["investigations"] >= ranked[-1]["investigations"]

    def test_tools_route(self, analytics_client, analytics_db):
        _seed_analytics_data(analytics_db)
        resp = analytics_client.get("/api/jarvis/analytics/tools")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] >= 1
        patch_tool = next((t for t in body["tools"] if t["tool"] == "patch_generator"), None)
        assert patch_tool is not None
        assert patch_tool["executions"] >= 1

    def test_proposals_route(self, analytics_client, analytics_db):
        _seed_analytics_data(analytics_db)
        resp = analytics_client.get("/api/jarvis/analytics/proposals")
        assert resp.status_code == 200
        body = resp.json()
        assert body["proposals"]["proposals_generated"] >= 5
        assert body["proposal_tasks"] == 5

    def test_root_causes_route(self, analytics_client, analytics_db):
        _seed_analytics_data(analytics_db)
        resp = analytics_client.get("/api/jarvis/analytics/root-causes")
        assert resp.status_code == 200
        body = resp.json()
        assert body["unique_root_causes"] >= 3
        assert len(body["most_common_root_causes"]) >= 1
        recurring = body["recurring_incidents"]
        assert any(r["occurrences"] >= 2 for r in recurring)

    def test_read_only_flag(self, analytics_client, analytics_db):
        _seed_analytics_data(analytics_db)
        for path in (
            "/api/jarvis/analytics/overview",
            "/api/jarvis/analytics/templates",
            "/api/jarvis/analytics/tools",
            "/api/jarvis/analytics/proposals",
            "/api/jarvis/analytics/root-causes",
        ):
            resp = analytics_client.get(path)
            assert resp.json().get("read_only") is True
