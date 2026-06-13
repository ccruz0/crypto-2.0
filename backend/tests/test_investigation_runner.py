"""Tests for investigation runner orchestration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text

from app.database import ensure_jarvis_investigations_table
from app.jarvis.investigations.investigation_runner import (
    collect_evidence,
    run_investigation,
    search_prior_investigations,
)
from app.jarvis.investigations.investigation_types import InvestigationStatus
from app.jarvis.investigations.persistence import save_investigation
from app.jarvis.investigations.investigation_report import (
    InvestigationReport,
    RootCauseCandidate,
    build_investigation_report,
)


@pytest.fixture()
def inv_db(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:")
    ensure_jarvis_investigations_table(engine)
    monkeypatch.setattr("app.jarvis.investigations.persistence.engine", engine)
    monkeypatch.setattr("app.database.engine", engine)
    return engine


class TestInvestigationRunner:
    @patch("app.jarvis.investigations.investigation_runner.build_default_registry")
    def test_successful_investigation(self, mock_registry_factory, inv_db):
        registry = MagicMock()

        def _execute(name, **kwargs):
            if name == "diagnose_open_orders":
                return MagicMock(
                    ok=True,
                    output={
                        "tool": "diagnose_open_orders",
                        "ok": True,
                        "root_cause": "All sources agree: zero open orders",
                        "evidence": [
                            {
                                "source": "database",
                                "reference": "exchange_orders",
                                "detail": "Open-status count: 0",
                                "confidence": "high",
                            }
                        ],
                        "conclusion": "Dashboard correctly shows zero.",
                        "next_action": "No action required.",
                    },
                )
            return MagicMock(ok=True, output={"tool": name, "ok": True, "matches": []})

        registry.execute.side_effect = _execute
        mock_registry_factory.return_value = registry

        report = run_investigation("Why are open orders empty?", persist=True)
        assert report.investigation_id
        assert report.evidence
        assert report.status in (InvestigationStatus.COMPLETED, InvestigationStatus.INSUFFICIENT_EVIDENCE)
        assert report.recommended_fix

    @patch("app.jarvis.investigations.investigation_runner.build_default_registry")
    def test_insufficient_evidence_when_no_root_cause(self, mock_registry_factory, inv_db):
        registry = MagicMock()
        registry.execute.return_value = MagicMock(
            ok=True,
            output={"tool": "inspect_health", "ok": True, "status": "unknown", "matches": []},
        )
        mock_registry_factory.return_value = registry

        report = run_investigation("Random unknown issue xyz", persist=False)
        assert report.status == InvestigationStatus.INSUFFICIENT_EVIDENCE

    @patch("app.jarvis.investigations.investigation_runner.build_default_registry")
    def test_collect_evidence_merges_sources(self, mock_registry_factory):
        registry = MagicMock()
        registry.execute.return_value = MagicMock(
            ok=True,
            output={
                "tool": "query_database",
                "ok": True,
                "evidence": [
                    {
                        "source": "database",
                        "reference": "exchange_orders",
                        "detail": "count=1",
                        "confidence": "high",
                    }
                ],
            },
        )
        mock_registry_factory.return_value = registry

        evidence, outputs, category, template_id = collect_evidence("Why are open orders empty?")
        assert evidence
        assert category == "orders"
        assert template_id == "open_orders_empty"
        assert outputs

    def test_historical_incident_lookup(self, inv_db):
        report = build_investigation_report(
            investigation_id="hist-001",
            objective="Why are open orders empty?",
            category="orders",
            template_id="open_orders_empty",
            evidence=[
                {
                    "source": "database",
                    "reference": "exchange_orders",
                    "detail": "count=0",
                    "confidence": "high",
                }
            ],
            ranked_causes=[
                RootCauseCandidate(cause="All sources agree: zero open orders", score=85.0)
            ],
            created_at="2026-06-13T12:00:00+00:00",
        )
        save_investigation(report)

        results = search_prior_investigations("open orders empty")
        assert results
        assert results[0]["objective"] == "Why are open orders empty?"

    @patch("app.jarvis.investigations.investigation_runner.build_default_registry")
    def test_dashboard_exchange_mismatch_detects_trigger_failure(self, mock_registry_factory, inv_db):
        registry = MagicMock()

        def _execute(name, **kwargs):
            if name == "reconcile_crypto_com_open_orders":
                return MagicMock(
                    ok=True,
                    output={
                        "tool": "reconcile_crypto_com_open_orders",
                        "ok": True,
                        "counts": {"exchange_live": 1, "database_open": 1, "dashboard_cache": 0},
                        "sources": {
                            "exchange": {
                                "trigger_orders_error_code": 50001,
                                "trigger_orders_error": "Invalid request",
                            }
                        },
                        "root_cause": "Reconciliation found discrepancies",
                    },
                )
            return MagicMock(ok=True, output={"tool": name, "ok": True})

        registry.execute.side_effect = _execute
        mock_registry_factory.return_value = registry

        report = run_investigation(
            "Why was dashboard showing zero orders while exchange had one?",
            persist=False,
        )
        assert report.evidence
        trigger_evidence = [e for e in report.evidence if "50001" in e.get("detail", "")]
        assert trigger_evidence or any("trigger" in (report.root_cause or "").lower() for _ in [1])
