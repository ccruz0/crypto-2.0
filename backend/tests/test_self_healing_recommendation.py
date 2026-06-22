"""Tests for the Jarvis Self-Healing Advisor (Phase 7).

Validates that Jarvis can turn a completed investigation into a safe, advisory
fix recommendation, optionally prepare an ACW task when confidence is high and the
domain is safe, and that it NEVER applies, merges, deploys, trades, or executes
fixes automatically. Human approval remains mandatory.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.api.routes_jarvis import router as jarvis_router
from app.database import (
    ensure_jarvis_execution_log_table,
    ensure_jarvis_investigations_table,
    ensure_jarvis_task_approvals_table,
    ensure_jarvis_task_runs_table,
)
from app.jarvis.execution import audit as audit_mod
from app.jarvis.execution import persistence as persist_mod
from app.jarvis.investigations.investigation_report import InvestigationReport
from app.jarvis.investigations.investigation_types import InvestigationStatus
from app.jarvis.investigations.persistence import save_investigation
from app.jarvis.self_healing.assessment import assess_root_cause
from app.jarvis.self_healing.safety_rules import evaluate_self_healing_safety
from app.jarvis.self_healing.service import (
    SelfHealingError,
    attach_self_healing,
    build_recommendation,
    create_acw_task_from_recommendation,
    generate_recommendation_for_investigation,
    record_decision,
)

DASHBOARD_ROOT_CAUSE = "Database has open orders but dashboard cache is empty"
DASHBOARD_FIX = "Use DB fallback for dashboard counts and refresh open_orders_cache."

AUTH_ROOT_CAUSE = "Duplicated API secret in runtime.env causes Crypto.com auth failure (40101)"
AUTH_FIX = "Deduplicate runtime.env entries and verify the key/secret pair."


def _report(**overrides) -> InvestigationReport:
    values = {
        "investigation_id": "inv-sh-1",
        "objective": "Why is the dashboard open-order count different from the database?",
        "category": "dashboard",
        "template_id": "generic",
        "status": InvestigationStatus.COMPLETED,
        "summary": "DB has open orders, dashboard cache empty.",
        "evidence": [
            {"source": "database", "reference": "orders", "detail": "db rows=3", "confidence": "high"},
            {"source": "cache", "reference": "open_orders", "detail": "cache=0", "confidence": "high"},
        ],
        "root_cause": DASHBOARD_ROOT_CAUSE,
        "confidence": 82.0,
        "ranked_causes": [],
        "impact": "Dashboard understates open orders.",
        "recommended_fix": DASHBOARD_FIX,
        "verification_steps": ["Confirm DB fallback populates dashboard."],
        "next_action": "Recommend fix.",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    values.update(overrides)
    return InvestigationReport(**values)


def _to_dict(report: InvestigationReport) -> dict:
    return report.to_dict()


@pytest.fixture()
def healing_db(monkeypatch, tmp_path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    ensure_jarvis_task_runs_table(engine)
    ensure_jarvis_execution_log_table(engine)
    ensure_jarvis_task_approvals_table(engine)
    ensure_jarvis_investigations_table(engine)
    monkeypatch.setattr(persist_mod, "engine", engine)
    monkeypatch.setattr(audit_mod, "engine", engine)
    monkeypatch.setattr("app.jarvis.investigations.persistence.engine", engine)
    monkeypatch.setattr("app.database.engine", engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def enabled(monkeypatch):
    monkeypatch.setenv("JARVIS_SELF_HEALING_ENABLED", "true")
    monkeypatch.setenv("JARVIS_SELF_HEALING_ACW_THRESHOLD", "70")
    yield


@pytest.fixture()
def healing_client(healing_db, enabled, monkeypatch):
    import app.database as db_mod

    monkeypatch.setattr(db_mod, "engine", healing_db)
    app = FastAPI()
    app.include_router(jarvis_router)
    return TestClient(app)


# --------------------------------------------------------------------------- #
# Pure recommendation logic
# --------------------------------------------------------------------------- #


class TestRecommendationEngine:
    def test_high_confidence_safe_fix_is_acw_ready(self, enabled):
        rec = build_recommendation(_to_dict(_report()))
        assert rec["acw_ready"] is True
        assert rec["safety"]["allowed"] is True
        assert rec["recommendation"]["affected_files"]  # non-empty
        assert rec["recommendation"]["fix_template_id"] == "dashboard.cache_db_mismatch"
        assert rec["estimated_risk"] in ("low", "medium", "high")
        assert rec["acw"]["proposed_objective"]
        assert rec["acw"]["expected_files"] == rec["recommendation"]["affected_files"]
        assert "create_acw_task" in rec["available_actions"]

    def test_recommendation_includes_affected_files(self, enabled):
        rec = build_recommendation(_to_dict(_report()))
        assert "affected_files" in rec
        assert all(isinstance(f, str) for f in rec["affected_files"])

    def test_recommendation_includes_risk_assessment(self, enabled):
        rec = build_recommendation(_to_dict(_report()))
        assert rec["assessment"]["severity"] in ("low", "medium", "high", "critical")
        assert rec["assessment"]["blast_radius"] in ("isolated", "service", "system", "unknown")
        assert rec["estimated_risk"] in ("low", "medium", "high")

    def test_low_confidence_not_acw_ready(self, enabled):
        rec = build_recommendation(_to_dict(_report(confidence=40.0)))
        assert rec["acw_ready"] is False
        assert "confidence_below_threshold" in rec["acw"]["reasons"]

    def test_disabled_flag_blocks_acw_but_still_recommends(self, monkeypatch):
        monkeypatch.delenv("JARVIS_SELF_HEALING_ENABLED", raising=False)
        rec = build_recommendation(_to_dict(_report()))
        assert rec["enabled"] is False
        assert rec["acw_ready"] is False
        assert "self_healing_disabled" in rec["acw"]["reasons"]
        # advisory content still produced
        assert rec["recommendation"]["proposed_fix"]

    def test_no_template_match_is_advisory_only(self, enabled):
        rec = build_recommendation(
            _to_dict(
                _report(
                    category="api",
                    objective="Investigate an unusual generic latency spike on the api layer",
                    root_cause="Unusual intermittent latency spike on the api layer under load",
                    recommended_fix="Add request timeout and retry budget to the api layer.",
                )
            )
        )
        assert rec["recommendation"]["has_template"] is False
        assert rec["recommendation"]["affected_files"] == []
        assert rec["acw_ready"] is False
        assert "affected_files_unknown" in rec["acw"]["reasons"]
        assert rec["assessment"]["fixability"] == "code_change"


# --------------------------------------------------------------------------- #
# Safety rules
# --------------------------------------------------------------------------- #


class TestSafetyRules:
    def test_credential_secret_domain_is_blocked(self, enabled):
        rec = build_recommendation(
            _to_dict(
                _report(
                    investigation_id="inv-auth",
                    category="authentication",
                    objective="Investigate Crypto.com 40101 authentication failures",
                    root_cause=AUTH_ROOT_CAUSE,
                    recommended_fix=AUTH_FIX,
                    confidence=92.0,
                )
            )
        )
        assert rec["safety"]["allowed"] is False
        assert "secrets" in rec["safety"]["blocked_domains"]
        assert rec["acw_ready"] is False
        assert rec["assessment"]["fixability"] == "manual"
        assert "create_acw_task" not in rec["available_actions"]

    def test_trading_execution_objective_blocked(self):
        result = evaluate_self_healing_safety(
            objective="Place a market order to rebalance BTC",
            recommended_fix="execute trade on exchange",
        )
        assert result.allowed is False
        assert "trading_execution" in result.blocked_domains

    def test_wallet_operations_blocked(self):
        result = evaluate_self_healing_safety(root_cause="wallet withdrawal stuck")
        assert result.allowed is False
        assert "wallet_operations" in result.blocked_domains

    def test_safe_dashboard_fix_allowed(self):
        result = evaluate_self_healing_safety(
            objective="dashboard open orders mismatch",
            recommended_fix=DASHBOARD_FIX,
            affected_files=["backend/app/services/open_orders_cache.py"],
        )
        assert result.allowed is True
        assert result.blocked_domains == []


# --------------------------------------------------------------------------- #
# Assessment heuristics
# --------------------------------------------------------------------------- #


class TestAssessment:
    def test_missing_root_cause_is_not_fixable(self):
        a = assess_root_cause({"root_cause": "", "confidence": 10}, affected_files=[], has_template=False)
        assert a.fixability == "not_fixable"
        assert a.has_meaningful_root_cause is False

    def test_system_blast_radius_for_exchange_sync(self):
        a = assess_root_cause(
            {"root_cause": "exchange sync blocked", "category": "orders", "confidence": 80},
            affected_files=["backend/app/services/exchange_sync.py"],
            has_template=True,
        )
        assert a.blast_radius == "system"

    def test_isolated_blast_radius_for_frontend(self):
        a = assess_root_cause(
            {"root_cause": "websocket disconnect", "category": "websocket", "confidence": 60},
            affected_files=["frontend/src/lib/priceStreamWsUrl.ts"],
            has_template=True,
        )
        assert a.blast_radius == "isolated"


# --------------------------------------------------------------------------- #
# Service: investigation loading + ACW creation (no auto-execution)
# --------------------------------------------------------------------------- #


class TestService:
    def test_generate_requires_completed(self, healing_db, enabled):
        save_investigation(_report(status=InvestigationStatus.INSUFFICIENT_EVIDENCE))
        with pytest.raises(SelfHealingError) as exc:
            generate_recommendation_for_investigation("inv-sh-1")
        assert exc.value.status_code == 409

    def test_generate_not_found(self, healing_db, enabled):
        with pytest.raises(SelfHealingError) as exc:
            generate_recommendation_for_investigation("missing")
        assert exc.value.status_code == 404

    def test_create_acw_task_calls_workflow_with_expected_files(self, healing_db, enabled):
        save_investigation(_report())
        fake_task = {"task_id": "acw-123", "status": "waiting_for_approval"}
        with patch(
            "app.jarvis.self_healing.service._submit_acw_task",
            return_value=fake_task,
        ) as mock_submit:
            result = create_acw_task_from_recommendation("inv-sh-1", actor_id="tester")
        assert result["acw_task"]["task_id"] == "acw-123"
        kwargs = mock_submit.call_args.kwargs
        assert kwargs["target_files"]  # expected files passed through
        assert "Apply safe fix" in kwargs["objective"]

    def test_create_acw_task_disabled_raises_403(self, healing_db, monkeypatch):
        monkeypatch.delenv("JARVIS_SELF_HEALING_ENABLED", raising=False)
        save_investigation(_report())
        with pytest.raises(SelfHealingError) as exc:
            create_acw_task_from_recommendation("inv-sh-1")
        assert exc.value.status_code == 403

    def test_create_acw_task_blocked_for_credentials(self, healing_db, enabled):
        save_investigation(
            _report(
                investigation_id="inv-auth",
                category="authentication",
                root_cause=AUTH_ROOT_CAUSE,
                recommended_fix=AUTH_FIX,
                confidence=92.0,
            )
        )
        with patch("app.jarvis.self_healing.service._submit_acw_task") as mock_submit:
            with pytest.raises(SelfHealingError) as exc:
                create_acw_task_from_recommendation("inv-auth")
        assert exc.value.status_code == 403
        mock_submit.assert_not_called()

    def test_generate_does_not_create_any_task(self, healing_db, enabled):
        """Generating a recommendation must not create execution tasks (read-only)."""
        save_investigation(_report())
        from app.jarvis.execution.persistence import list_execution_tasks

        generate_recommendation_for_investigation("inv-sh-1")
        assert list_execution_tasks(limit=50) == []

    def test_record_decision_ignore(self, healing_db, enabled):
        save_investigation(_report())
        result = record_decision("inv-sh-1", "ignore")
        assert result["decision"] == "ignore"

    def test_record_decision_investigate_further(self, healing_db, enabled):
        save_investigation(_report())
        result = record_decision("inv-sh-1", "investigate_further")
        assert result["decision"] == "investigate_further"
        assert "suggested_objective" in result


# --------------------------------------------------------------------------- #
# attach_self_healing (investigation report extensions)
# --------------------------------------------------------------------------- #


class TestAttachSelfHealing:
    def test_disabled_returns_unchanged(self, monkeypatch):
        monkeypatch.delenv("JARVIS_SELF_HEALING_ENABLED", raising=False)
        row = _to_dict(_report())
        assert "self_healing" not in attach_self_healing(row)

    def test_enabled_completed_adds_fields(self, enabled):
        row = attach_self_healing(_to_dict(_report()))
        assert "self_healing" in row
        assert "proposed_fix" in row
        assert "affected_files" in row
        assert "estimated_risk" in row
        assert "acw_ready" in row

    def test_not_completed_returns_unchanged(self, enabled):
        row = _to_dict(_report(status=InvestigationStatus.INSUFFICIENT_EVIDENCE))
        assert "self_healing" not in attach_self_healing(row)


# --------------------------------------------------------------------------- #
# HTTP API
# --------------------------------------------------------------------------- #


class TestApi:
    def test_safety_status(self, healing_client):
        resp = healing_client.get("/api/jarvis/self-healing/safety-status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["self_healing_enabled"] is True
        assert body["auto_execution"] is False
        assert body["auto_merge"] is False
        assert body["auto_deploy"] is False
        assert body["human_approval_required"] is True

    def test_get_recommendation(self, healing_client):
        save_investigation(_report())
        resp = healing_client.get("/api/jarvis/self-healing/recommendation/inv-sh-1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["acw_ready"] is True
        assert body["recommendation"]["affected_files"]
        assert body["safety"]["allowed"] is True

    def test_get_recommendation_not_found(self, healing_client):
        resp = healing_client.get("/api/jarvis/self-healing/recommendation/none")
        assert resp.status_code == 404

    def test_get_recommendation_not_completed(self, healing_client):
        save_investigation(_report(status=InvestigationStatus.INSUFFICIENT_EVIDENCE))
        resp = healing_client.get("/api/jarvis/self-healing/recommendation/inv-sh-1")
        assert resp.status_code == 409

    def test_create_acw_task_endpoint(self, healing_client):
        save_investigation(_report())
        fake_task = {"task_id": "acw-xyz", "status": "waiting_for_approval"}
        with patch(
            "app.jarvis.self_healing.service._submit_acw_task",
            return_value=fake_task,
        ):
            resp = healing_client.post("/api/jarvis/self-healing/inv-sh-1/create-acw-task", json={})
        assert resp.status_code == 200
        assert resp.json()["acw_task"]["task_id"] == "acw-xyz"

    def test_create_acw_task_endpoint_blocked_for_credentials(self, healing_client):
        save_investigation(
            _report(
                investigation_id="inv-auth",
                category="authentication",
                root_cause=AUTH_ROOT_CAUSE,
                recommended_fix=AUTH_FIX,
                confidence=92.0,
            )
        )
        resp = healing_client.post("/api/jarvis/self-healing/inv-auth/create-acw-task", json={})
        assert resp.status_code == 403

    def test_decision_endpoint(self, healing_client):
        save_investigation(_report())
        resp = healing_client.post(
            "/api/jarvis/self-healing/inv-sh-1/decision", json={"decision": "ignore"}
        )
        assert resp.status_code == 200
        assert resp.json()["decision"] == "ignore"

    def test_investigation_detail_includes_self_healing(self, healing_client):
        save_investigation(_report())
        resp = healing_client.get("/api/jarvis/investigations/inv-sh-1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["acw_ready"] is True
        assert body["self_healing"]["recommendation"]["affected_files"]
