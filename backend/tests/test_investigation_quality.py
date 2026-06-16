"""Tests for investigation evidence quality, synthesis, and validation gates."""

from __future__ import annotations

from app.jarvis.investigations.evidence_model import (
    count_independent_sources,
    evidence_from_tool_output,
    has_direct_evidence,
    identify_missing_evidence,
    is_substantive_evidence,
    merge_evidence,
    normalize_evidence,
)
from app.jarvis.investigations.investigation_report import (
    RootCauseCandidate,
    build_investigation_report,
    build_synthesis,
    validate_investigation_report_fields,
)
from app.jarvis.investigations.investigation_types import (
    InvestigationStatus,
    match_investigation_template,
)


def _db_evidence(**extra: object) -> dict:
    base = {
        "source": "database",
        "reference": "count_open_orders",
        "detail": "table=exchange_orders; row_count=3; order_ids=['abc123']; query=SELECT COUNT(*) FROM exchange_orders",
        "confidence": "high",
        "table": "exchange_orders",
        "row_count": 3,
        "order_ids": ["abc123"],
        "is_direct": True,
    }
    base.update(extra)
    return base


def _exchange_evidence() -> dict:
    return {
        "source": "exchange",
        "reference": "reconciliation_counts",
        "detail": "Exchange=2, DB=2, dashboard=0; checked_at=2026-06-16T00:00:00+00:00",
        "confidence": "high",
        "is_direct": True,
    }


class TestEvidenceExtraction:
    def test_query_database_includes_table_row_count_order_ids(self):
        items = evidence_from_tool_output(
            {
                "tool": "query_database",
                "ok": True,
                "preset": "recent_orders",
                "query_executed": "SELECT id, exchange_order_id FROM exchange_orders LIMIT 50",
                "row_count": 2,
                "rows": [
                    {"id": 1, "exchange_order_id": "ord-1", "created_at": "2026-06-16T10:00:00+00:00"},
                    {"id": 2, "exchange_order_id": "ord-2", "created_at": "2026-06-16T11:00:00+00:00"},
                ],
                "checked_at": "2026-06-16T12:00:00+00:00",
            }
        )
        db_items = [i for i in items if i["source"] == "database"]
        assert db_items
        assert db_items[0]["table"] == "exchange_orders"
        assert db_items[0]["row_count"] == 2
        assert "ord-1" in db_items[0]["order_ids"]

    def test_search_logs_include_container_and_timestamp(self):
        items = evidence_from_tool_output(
            {
                "tool": "search_logs",
                "matches": [
                    {
                        "timestamp": "2026-06-16T09:00:00",
                        "source": "backend-aws",
                        "message": "Crypto.com auth error 40101",
                    }
                ],
                "match_count": 1,
                "keywords": ["40101"],
                "services_searched": ["backend-aws"],
            }
        )
        assert items[0]["log_container"] == "backend-aws"
        assert "40101" in items[0]["detail"]

    def test_search_repository_includes_path_and_line(self):
        items = evidence_from_tool_output(
            {
                "tool": "search_repository",
                "matches": [
                    {
                        "path": "backend/app/api/routes_orders.py",
                        "line": "42",
                        "text": "def get_open_orders",
                        "confidence": "high",
                    }
                ],
                "topics": ["open_orders"],
            }
        )
        assert items[0]["file_path"] == "backend/app/api/routes_orders.py"
        assert items[0]["line_number"] == "42"


class TestEvidenceSufficiency:
    def test_two_independent_sources_accepted(self):
        evidence = merge_evidence(
            [
                {
                    "source": "database",
                    "reference": "count",
                    "detail": "table=exchange_orders; row_count=3; query=SELECT COUNT(*) FROM exchange_orders",
                    "confidence": "high",
                    "table": "exchange_orders",
                    "row_count": 3,
                },
                {
                    "source": "logs",
                    "reference": "sync",
                    "detail": "open_orders_cache write failed during exchange sync at 2026-06-16T10:00:00Z",
                    "confidence": "medium",
                },
            ]
        )
        assert count_independent_sources(evidence) >= 2
        assert not has_direct_evidence(evidence, [])

    def test_direct_evidence_accepted_with_one_source(self):
        evidence = merge_evidence([_db_evidence()])
        tool_outputs = [{"tool": "query_database", "ok": True, "row_count": 3, "query_executed": "SELECT 1"}]
        assert has_direct_evidence(evidence, tool_outputs)

    def test_weak_health_only_not_substantive(self):
        item = normalize_evidence(
            {
                "source": "runtime",
                "reference": "health",
                "detail": "Health check status=pass",
                "confidence": "high",
            }
        )
        assert item is not None
        assert not is_substantive_evidence(item)


class TestValidationGates:
    def test_weak_generic_conclusion_rejected(self):
        status = validate_investigation_report_fields(
            root_cause="unknown",
            evidence=[_db_evidence()],
            confidence=50,
            recommended_fix="fix it",
        )
        assert status == InvestigationStatus.INSUFFICIENT_EVIDENCE

    def test_empty_artifacts_rejected(self):
        status = validate_investigation_report_fields(
            root_cause="Database has open orders but dashboard cache is empty",
            evidence=[],
            confidence=80,
            recommended_fix="Run sync",
        )
        assert status == InvestigationStatus.INSUFFICIENT_EVIDENCE

    def test_irrelevant_health_only_rejected(self):
        status = validate_investigation_report_fields(
            root_cause="Deployment health check failing",
            evidence=[
                normalize_evidence(
                    {
                        "source": "runtime",
                        "reference": "health_endpoint",
                        "detail": "Health check status=pass",
                        "confidence": "high",
                    }
                )
            ],
            confidence=80,
            recommended_fix="Inspect logs",
        )
        assert status == InvestigationStatus.INSUFFICIENT_EVIDENCE

    def test_specific_root_cause_accepted_with_two_sources(self):
        status = validate_investigation_report_fields(
            root_cause="Database has open orders but dashboard cache is empty",
            evidence=merge_evidence(
                [
                    _db_evidence(),
                    _exchange_evidence(),
                    {
                        "source": "logs",
                        "reference": "backend-aws",
                        "detail": "[2026-06-16] container=backend-aws: open_orders_cache write failed during sync",
                        "confidence": "medium",
                    },
                ]
            ),
            confidence=85,
            recommended_fix="Run exchange sync to populate open_orders_cache.",
        )
        assert status == InvestigationStatus.COMPLETED

    def test_missing_evidence_listed_when_incomplete(self):
        gaps = identify_missing_evidence([], [], category="orders")
        assert any("database" in g.lower() for g in gaps)
        assert any("exchange" in g.lower() or "log" in g.lower() for g in gaps)

    def test_mismatch_resolution_rejected_for_executed_orders_template(self):
        status = validate_investigation_report_fields(
            root_cause="No active dashboard/exchange mismatch detected",
            evidence=merge_evidence([_db_evidence(), _exchange_evidence()]),
            confidence=96,
            recommended_fix="No action",
            template_id="executed_orders_missing",
            category="orders",
        )
        assert status == InvestigationStatus.INSUFFICIENT_EVIDENCE


class TestSynthesis:
    def test_final_synthesis_includes_required_sections(self):
        evidence = merge_evidence([_db_evidence(), _exchange_evidence()])
        synthesis = build_synthesis(
            objective="Why are open orders empty?",
            evidence=evidence,
            root_cause="Database has open orders but dashboard cache is empty",
            impact="Dashboard shows empty open orders despite DB rows.",
            next_action="Run exchange sync to populate open_orders_cache.",
            confidence=85,
            missing_evidence=[],
        )
        for key in (
            "summary",
            "evidence_found",
            "root_cause",
            "impact",
            "safe_recommended_next_action",
            "missing_evidence",
            "confidence_level",
        ):
            assert key in synthesis
        assert synthesis["root_cause"]
        assert synthesis["safe_recommended_next_action"]
        assert synthesis["confidence_level"] == "high"

    def test_build_report_includes_synthesis(self):
        ranked = [
            RootCauseCandidate(
                cause="Database has open orders but dashboard cache is empty",
                score=85.0,
                supporting_evidence=["db vs cache"],
                explanation="Supported.",
            )
        ]
        report = build_investigation_report(
            investigation_id="q-1",
            objective="Investigate why open orders show 0 in the dashboard",
            category="dashboard",
            template_id="open_orders_zero_dashboard",
            evidence=merge_evidence(
                [
                    _db_evidence(),
                    _exchange_evidence(),
                    {
                        "source": "logs",
                        "reference": "sync",
                        "detail": "open_orders_cache empty after sync; exchange_live=2 dashboard=0",
                        "confidence": "high",
                    },
                ]
            ),
            ranked_causes=ranked,
            created_at="2026-06-16T00:00:00+00:00",
        )
        data = report.to_dict()
        assert "synthesis" in data
        assert data["synthesis"]["root_cause"]
        assert data["synthesis"]["safe_recommended_next_action"]


class TestTemplateRouting:
    def test_executed_orders_routes_before_dashboard_mismatch(self):
        template = match_investigation_template("Why are executed orders missing? investigate btc orders")
        assert template is not None
        assert template.template_id == "executed_orders_missing"

    def test_btc_dashboard_mismatch_not_executed_orders(self):
        template = match_investigation_template(
            "Why are BTC orders missing from the dashboard but visible in Crypto.com?"
        )
        assert template is not None
        assert template.template_id == "dashboard_exchange_mismatch"

    def test_open_orders_zero_dashboard_template(self):
        template = match_investigation_template("Investigate why open orders show 0 in the dashboard")
        assert template is not None
        assert template.template_id == "open_orders_zero_dashboard"

    def test_portfolio_reconciliation_template(self):
        template = match_investigation_template("Investigate portfolio reconciliation mismatch")
        assert template is not None
        assert template.template_id == "portfolio_reconciliation_mismatch"
