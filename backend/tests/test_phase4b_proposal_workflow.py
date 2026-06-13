"""Tests for Jarvis Phase 4B patch proposal workflow."""

from __future__ import annotations

import ast
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.api.routes_jarvis import router as jarvis_router
from app.database import (
    ensure_jarvis_execution_log_table,
    ensure_jarvis_investigations_table,
    ensure_jarvis_task_approvals_table,
    ensure_jarvis_task_runs_table,
)
from app.jarvis.artifacts.storage import load_artifact_content
from app.jarvis.execution import audit as audit_mod
from app.jarvis.execution import persistence as persist_mod
from app.jarvis.investigations.investigation_report import InvestigationReport
from app.jarvis.investigations.investigation_types import InvestigationStatus
from app.jarvis.investigations.persistence import get_investigation, save_investigation
from app.jarvis.proposals.patch_generator import generate_patch_for_template, is_fix_already_present
from app.jarvis.proposals.proposal_service import (
    PHASE4B_ARTIFACT_NAMES,
    WORKFLOW_TYPE,
    ProposalWorkflowError,
    submit_patch_proposal,
)
from app.services._paths import workspace_root

TRIGGER_ROOT_CAUSE = "Trigger order API failure blocks cache updates"
TRIGGER_RECOMMENDED_FIX = (
    "Allow regular open orders to update cache independently when trigger-order sync fails."
)


def _sample_report(**overrides) -> InvestigationReport:
    values = {
        "investigation_id": "inv-proposal-1",
        "objective": "Why does dashboard show zero open orders?",
        "category": "orders",
        "template_id": "generic",
        "status": InvestigationStatus.COMPLETED,
        "summary": "Trigger order sync failure.",
        "evidence": [{"source": "sync", "reference": "meta", "detail": "50001", "confidence": "high"}],
        "root_cause": TRIGGER_ROOT_CAUSE,
        "confidence": 75.0,
        "ranked_causes": [],
        "impact": "Dashboard mismatch.",
        "recommended_fix": TRIGGER_RECOMMENDED_FIX,
        "verification_steps": ["Re-run reconcile after fix."],
        "next_action": "Propose patch.",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    values.update(overrides)
    return InvestigationReport(**values)


@pytest.fixture()
def proposal_db(monkeypatch, tmp_path):
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
    from app.jarvis import artifacts as artifacts_pkg

    monkeypatch.setattr(artifacts_pkg.storage, "_ARTIFACTS_DIR", tmp_path)
    yield engine
    engine.dispose()


@pytest.fixture()
def proposal_client(proposal_db, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_4B_PROPOSALS_ENABLED", "true")
    import app.database as db_mod

    monkeypatch.setattr(db_mod, "engine", proposal_db)
    from app.jarvis import artifacts as artifacts_pkg

    monkeypatch.setattr(artifacts_pkg.storage, "_ARTIFACTS_DIR", tmp_path)
    app = FastAPI()
    app.include_router(jarvis_router)
    return TestClient(app)


def _persist(report: InvestigationReport) -> None:
    assert save_investigation(report) is True


class TestProposalWorkflowService:
    def test_flag_disabled_raises_403(self, proposal_db, monkeypatch):
        monkeypatch.delenv("JARVIS_4B_PROPOSALS_ENABLED", raising=False)
        _persist(_sample_report())
        with pytest.raises(ProposalWorkflowError) as exc:
            submit_patch_proposal("inv-proposal-1")
        assert exc.value.status_code == 403

    def test_ineligible_investigation_raises_409(self, proposal_db, monkeypatch):
        monkeypatch.setenv("JARVIS_4B_PROPOSALS_ENABLED", "true")
        _persist(_sample_report(status=InvestigationStatus.INSUFFICIENT_EVIDENCE))
        with pytest.raises(ProposalWorkflowError) as exc:
            submit_patch_proposal("inv-proposal-1")
        assert exc.value.status_code == 409
        assert "investigation_not_completed" in exc.value.reasons

    def test_forbidden_recommended_fix_blocked(self, proposal_db, monkeypatch):
        monkeypatch.setenv("JARVIS_4B_PROPOSALS_ENABLED", "true")
        _persist(_sample_report(recommended_fix="Deploy to production immediately"))
        with pytest.raises(ProposalWorkflowError) as exc:
            submit_patch_proposal("inv-proposal-1")
        assert exc.value.status_code == 409
        assert "forbidden_recommended_fix" in exc.value.reasons

    def test_eligible_investigation_creates_task(self, proposal_db, monkeypatch):
        monkeypatch.setenv("JARVIS_4B_PROPOSALS_ENABLED", "true")
        _persist(_sample_report())
        detail = submit_patch_proposal("inv-proposal-1")
        assert detail["task_id"]
        assert detail["workflow_type"] == WORKFLOW_TYPE
        assert detail["source_investigation_id"] == "inv-proposal-1"
        assert detail["fix_template_id"] == "orders.trigger_50001_cache_independent"
        assert detail["plan"]["workflow_type"] == WORKFLOW_TYPE
        assert detail["plan"]["source_investigation_id"] == "inv-proposal-1"

    def test_artifacts_created(self, proposal_db, monkeypatch):
        monkeypatch.setenv("JARVIS_4B_PROPOSALS_ENABLED", "true")
        _persist(_sample_report(investigation_id="inv-artifacts"))
        detail = submit_patch_proposal("inv-artifacts")
        names = {a.get("standard_name") for a in detail.get("artifacts") or []}
        assert names == PHASE4B_ARTIFACT_NAMES

        patch_art = next(a for a in detail["artifacts"] if a["standard_name"] == "patch.diff")
        review_art = next(a for a in detail["artifacts"] if a["standard_name"] == "review.md")
        ctx_art = next(a for a in detail["artifacts"] if a["standard_name"] == "investigation_context.json")
        tests_art = next(a for a in detail["artifacts"] if a["standard_name"] == "tests.json")

        ctx = json.loads(load_artifact_content(ctx_art))
        assert ctx["investigation_id"] == "inv-artifacts"
        assert ctx["fix_template_id"] == "orders.trigger_50001_cache_independent"

        review = load_artifact_content(review_art)
        assert "Root cause" in review
        assert "Sandbox result" in review

        tests = json.loads(load_artifact_content(tests_art))
        assert "applicable" in tests

        patch_body = load_artifact_content(patch_art)
        assert patch_body

    def test_investigation_proposal_linkage_updated(self, proposal_db, monkeypatch):
        monkeypatch.setenv("JARVIS_4B_PROPOSALS_ENABLED", "true")
        _persist(_sample_report(investigation_id="inv-link"))
        detail = submit_patch_proposal("inv-link")
        row = get_investigation("inv-link")
        assert row is not None
        assert row["proposal_task_id"] == detail["task_id"]
        assert row["proposal_status"] in ("waiting_for_approval", "no_fix_required", "failed")

    def test_no_phase5_imports_in_proposal_modules(self):
        module_paths = [
            Path("app/jarvis/proposals/proposal_service.py"),
            Path("app/jarvis/proposals/patch_generator.py"),
            Path("app/jarvis/proposals/sandbox_validation.py"),
        ]
        backend = Path(__file__).resolve().parents[1]
        forbidden = (
            "app.jarvis.change_execution",
            "change_execution.service",
            "apply_patch_in_sandbox",
            "phase5",
        )
        for rel in module_paths:
            source = (backend / rel).read_text(encoding="utf-8")
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert not any(f in alias.name for f in forbidden), alias.name
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    assert not any(f in mod for f in forbidden), mod

    def test_known_template_noop_when_fix_present(self, proposal_db, monkeypatch):
        monkeypatch.setenv("JARVIS_4B_PROPOSALS_ENABLED", "true")
        repo = workspace_root()
        assert is_fix_already_present(repo, "orders.trigger_50001_cache_independent")
        result = generate_patch_for_template("orders.trigger_50001_cache_independent", repo_root=repo)
        assert result.is_noop is True
        assert result.fix_already_present is True
        assert "fix already present" in result.patch_content.lower() or "no-op" in result.patch_content.lower()

        _persist(_sample_report(investigation_id="inv-noop"))
        detail = submit_patch_proposal("inv-noop")
        assert detail["status"] == "completed"
        row = get_investigation("inv-noop")
        assert row["proposal_status"] == "no_fix_required"
        tests_art = next(a for a in detail["artifacts"] if a["standard_name"] == "tests.json")
        tests = json.loads(load_artifact_content(tests_art))
        assert tests["skipped"] is True
        assert tests["applicable"] is False

    def test_known_template_generates_real_patch_when_fix_missing(self, tmp_path):
        # Minimal pre-fix tree: exchange_sync without unified fetch, no unified module
        pre_fix = tmp_path / "repo"
        pre_fix.mkdir()
        exchange = pre_fix / "backend/app/services"
        exchange.mkdir(parents=True)
        (exchange / "exchange_sync.py").write_text(
            "def sync_open_orders():\n    response = trade_client.get_open_orders()\n",
            encoding="utf-8",
        )
        tests_dir = pre_fix / "backend/tests"
        tests_dir.mkdir(parents=True)
        (tests_dir / "test_crypto_com_sync_status.py").write_text("def test_placeholder(): pass\n", encoding="utf-8")

        assert not is_fix_already_present(pre_fix, "orders.trigger_50001_cache_independent")
        result = generate_patch_for_template("orders.trigger_50001_cache_independent", repo_root=pre_fix)
        assert result.is_noop is False
        assert "unified_open_orders_fetch" in result.patch_content


class TestProposalWorkflowAPI:
    def test_api_flag_disabled_403(self, proposal_client, proposal_db, monkeypatch):
        monkeypatch.delenv("JARVIS_4B_PROPOSALS_ENABLED", raising=False)
        _persist(_sample_report(investigation_id="inv-api-off"))
        resp = proposal_client.post("/api/jarvis/investigations/inv-api-off/propose-patch")
        assert resp.status_code == 403

    def test_api_ineligible_409(self, proposal_client):
        _persist(_sample_report(investigation_id="inv-api-bad", confidence=10.0))
        resp = proposal_client.post("/api/jarvis/investigations/inv-api-bad/propose-patch")
        assert resp.status_code == 409
        body = resp.json()
        assert "confidence_below_threshold" in str(body)

    def test_api_eligible_creates_task(self, proposal_client):
        _persist(_sample_report(investigation_id="inv-api-ok"))
        resp = proposal_client.post("/api/jarvis/investigations/inv-api-ok/propose-patch")
        assert resp.status_code == 200
        body = resp.json()
        assert body["task_id"]
        assert body["source_investigation_id"] == "inv-api-ok"
        assert body["fix_template_id"] == "orders.trigger_50001_cache_independent"
        assert body["workflow_type"] == WORKFLOW_TYPE
        assert len(body.get("artifacts") or []) == 4
        assert body.get("sandbox_summary") is not None

    def test_api_forbidden_recommended_fix_409(self, proposal_client):
        _persist(
            _sample_report(
                investigation_id="inv-api-forbidden",
                recommended_fix="Execute order on BTC-USD",
            )
        )
        resp = proposal_client.post("/api/jarvis/investigations/inv-api-forbidden/propose-patch")
        assert resp.status_code == 409

    def test_task_row_has_workflow_type(self, proposal_client, proposal_db):
        _persist(_sample_report(investigation_id="inv-db-row"))
        resp = proposal_client.post("/api/jarvis/investigations/inv-db-row/propose-patch")
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]
        with proposal_db.connect() as conn:
            row = conn.execute(
                text("SELECT plan_json, status FROM jarvis_task_runs WHERE task_id = :id"),
                {"id": task_id},
            ).fetchone()
        plan = json.loads(row[0])
        assert plan["workflow_type"] == "phase4b_patch_proposal"
        assert plan["source_investigation_id"] == "inv-db-row"

    def test_sandbox_failure_marks_failed(self, proposal_db, monkeypatch):
        monkeypatch.setenv("JARVIS_4B_PROPOSALS_ENABLED", "true")
        _persist(_sample_report(investigation_id="inv-sandbox-fail"))

        fail_sandbox = {
            "applicable": False,
            "skipped": False,
            "apply_check_passed": False,
            "tests_ran": False,
            "tests_passed": None,
            "error": "git apply --check failed: corrupt patch",
        }
        with patch(
            "app.jarvis.proposals.proposal_service.generate_patch_for_template"
        ) as mock_gen, patch(
            "app.jarvis.proposals.proposal_service.validate_patch_in_sandbox",
            return_value=fail_sandbox,
        ):
            from app.jarvis.proposals.patch_generator import PatchGenerationResult

            mock_gen.return_value = PatchGenerationResult(
                fix_template_id="orders.trigger_50001_cache_independent",
                patch_content="diff --git a/foo b/foo\n",
                is_noop=False,
                files_affected=["backend/app/services/exchange_sync.py"],
            )
            detail = submit_patch_proposal("inv-sandbox-fail")

        assert detail["status"] == "failed"
        row = get_investigation("inv-sandbox-fail")
        assert row["proposal_status"] == "failed"
