"""Tests for the objective-aware self-healing improvements.

Covers Deliverable 5 of jarvis_eval/SELF_HEALING_IMPROVEMENT_DESIGN.md:
- domain classification
- cross-domain root-cause blocking / gating
- confidence calibration caps
- recommendation concreteness + generic-phrase ban
- ACW invariance (self-healing gating is untouched by the new flag)

All new behavior is gated behind JARVIS_OBJECTIVE_AWARE_RC; tests assert the old
path is unchanged when the flag is off.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.jarvis.investigations.confidence import calibrate_confidence
from app.jarvis.investigations.domains import (
    InvestigationDomain,
    apply_domain_gating,
    classify_cause_domain,
    classify_domain,
    domain_relevance,
    objective_aware_rc_enabled,
)
from app.jarvis.investigations.investigation_report import (
    RootCauseCandidate,
    build_investigation_report,
    rank_root_causes,
)
from app.jarvis.investigations.investigation_types import InvestigationStatus
from app.jarvis.investigations.recommendation_builder import (
    build_recommendation_plan,
    is_generic_recommendation,
)


@pytest.fixture()
def objective_aware(monkeypatch):
    monkeypatch.setenv("JARVIS_OBJECTIVE_AWARE_RC", "true")
    yield


@pytest.fixture()
def objective_aware_off(monkeypatch):
    monkeypatch.delenv("JARVIS_OBJECTIVE_AWARE_RC", raising=False)
    yield


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Domain classification
# --------------------------------------------------------------------------- #


class TestDomainClassification:
    @pytest.mark.parametrize(
        "objective,category,template_id,expected",
        [
            (
                "Investigate Crypto.com authentication failures",
                "authentication",
                "exchange_auth_failing",
                InvestigationDomain.EXCHANGE_AUTH,
            ),
            (
                "Investigate portfolio reconciliation mismatch",
                "portfolio",
                "portfolio_reconciliation_mismatch",
                InvestigationDomain.PORTFOLIO_RECONCILIATION,
            ),
            (
                "Why are open orders empty on the dashboard?",
                "orders",
                "open_orders_empty",
                InvestigationDomain.OPEN_ORDERS,
            ),
            (
                "Why does the dashboard differ from the exchange order list?",
                "dashboard",
                "dashboard_exchange_mismatch",
                InvestigationDomain.ORDER_RECONCILIATION,
            ),
            (
                "Why is the Jarvis scheduled task failing?",
                "deployment",
                "jarvis_task_failing",
                InvestigationDomain.DEPLOYMENT,
            ),
            (
                "Why are websocket prices stale?",
                "websocket",
                "websocket_prices_stale",
                InvestigationDomain.INFRASTRUCTURE,
            ),
            (
                "Check database health and recent query errors",
                "deployment",
                "generic",
                InvestigationDomain.DATABASE,
            ),
            (
                "Analyze recent error logs for production incidents",
                "api",
                "generic",
                InvestigationDomain.GENERIC,
            ),
        ],
    )
    def test_objective_domains(self, objective, category, template_id, expected):
        result = classify_domain(objective, category=category, template_id=template_id)
        assert result.domain == expected

    def test_exact_template_is_high_confidence(self):
        result = classify_domain("anything", category="", template_id="exchange_auth_failing")
        assert result.domain == InvestigationDomain.EXCHANGE_AUTH
        assert result.domain_confidence == 1.0

    def test_no_signal_is_generic_low_confidence(self):
        result = classify_domain("", category="", template_id="generic")
        assert result.domain == InvestigationDomain.GENERIC
        assert result.domain_confidence <= 0.3

    def test_cause_domains(self):
        assert (
            classify_cause_domain("Crypto.com API credentials missing or misconfigured in runtime.env")
            == InvestigationDomain.EXCHANGE_AUTH
        )
        assert (
            classify_cause_domain(
                "FILLED orders exist in database but dashboard trade history does not display them"
            )
            == InvestigationDomain.ORDER_RECONCILIATION
        )
        assert (
            classify_cause_domain(
                "Portfolio equity derived from balances because exchange omits a top-level equity field"
            )
            == InvestigationDomain.PORTFOLIO_RECONCILIATION
        )

    def test_flag_default_off(self, objective_aware_off):
        assert objective_aware_rc_enabled() is False

    def test_flag_on(self, objective_aware):
        assert objective_aware_rc_enabled() is True


# --------------------------------------------------------------------------- #
# Cross-domain gating
# --------------------------------------------------------------------------- #


class TestDomainGating:
    def test_relevance_matrix(self):
        assert domain_relevance(InvestigationDomain.EXCHANGE_AUTH, InvestigationDomain.EXCHANGE_AUTH) == 1.0
        assert (
            domain_relevance(InvestigationDomain.EXCHANGE_AUTH, InvestigationDomain.ORDER_RECONCILIATION)
            == 0.2
        )
        assert (
            domain_relevance(InvestigationDomain.OPEN_ORDERS, InvestigationDomain.ORDER_RECONCILIATION)
            == 0.6
        )

    def test_generic_objective_disables_gating(self):
        assert (
            domain_relevance(InvestigationDomain.GENERIC, InvestigationDomain.ORDER_RECONCILIATION) == 1.0
        )

    def test_low_confidence_disables_gating(self):
        assert (
            domain_relevance(
                InvestigationDomain.EXCHANGE_AUTH,
                InvestigationDomain.ORDER_RECONCILIATION,
                objective_confidence=0.2,
            )
            == 1.0
        )

    def test_cross_domain_cause_is_penalized_and_demoted(self):
        candidates = [
            RootCauseCandidate(
                cause="FILLED orders exist in database but dashboard trade history does not display them",
                score=90.0,
            ),
            RootCauseCandidate(
                cause="Crypto.com API credentials missing or misconfigured in runtime.env",
                score=48.0,
            ),
        ]
        gated = apply_domain_gating(candidates, InvestigationDomain.EXCHANGE_AUTH, 0.9)
        # The in-domain (auth) cause now ranks first despite a lower base score.
        assert gated[0].domain == InvestigationDomain.EXCHANGE_AUTH.value
        order_candidate = next(c for c in gated if "FILLED orders" in c.cause)
        assert order_candidate.score == pytest.approx(18.0)  # 90 * 0.2


# --------------------------------------------------------------------------- #
# Confidence calibration
# --------------------------------------------------------------------------- #


def _strong_evidence() -> list[dict]:
    return [
        {"source": "database", "detail": "db open orders rows=3", "confidence": "high", "is_direct": True},
        {"source": "exchange", "detail": "exchange reports 3 open orders", "confidence": "high", "is_direct": True},
        {"source": "cache", "detail": "cache empty", "confidence": "medium", "is_direct": False},
    ]


def _weak_evidence() -> list[dict]:
    return [
        {"source": "runtime", "detail": "health check warning", "confidence": "low", "is_direct": False},
    ]


class TestConfidenceCalibration:
    def test_domain_mismatch_capped_at_50(self):
        breakdown = calibrate_confidence(
            evidence=_strong_evidence(),
            tool_outputs=None,
            objective_domain=InvestigationDomain.EXCHANGE_AUTH,
            objective_confidence=0.9,
            cause_domain=InvestigationDomain.ORDER_RECONCILIATION,
            specificity=1.0,
            has_meaningful_root_cause=True,
        )
        assert breakdown.final <= 50.0
        assert "domain_mismatch_cap_50" in breakdown.caps_applied

    def test_weak_evidence_capped_at_40(self):
        breakdown = calibrate_confidence(
            evidence=_weak_evidence(),
            tool_outputs=None,
            objective_domain=InvestigationDomain.EXCHANGE_AUTH,
            objective_confidence=0.9,
            cause_domain=InvestigationDomain.EXCHANGE_AUTH,
            specificity=1.0,
            has_meaningful_root_cause=True,
        )
        assert breakdown.final <= 40.0

    def test_generic_recommendation_capped_at_60(self):
        breakdown = calibrate_confidence(
            evidence=_strong_evidence(),
            tool_outputs=None,
            objective_domain=InvestigationDomain.OPEN_ORDERS,
            objective_confidence=0.9,
            cause_domain=InvestigationDomain.OPEN_ORDERS,
            specificity=0.1,
            has_meaningful_root_cause=True,
        )
        assert breakdown.final <= 60.0
        assert "generic_recommendation_cap_60" in breakdown.caps_applied

    def test_non_meaningful_root_cause_is_zero(self):
        breakdown = calibrate_confidence(
            evidence=_strong_evidence(),
            tool_outputs=None,
            objective_domain=InvestigationDomain.OPEN_ORDERS,
            objective_confidence=0.9,
            cause_domain=InvestigationDomain.OPEN_ORDERS,
            specificity=1.0,
            has_meaningful_root_cause=False,
        )
        assert breakdown.final == 0.0

    def test_strong_in_domain_can_be_high(self):
        breakdown = calibrate_confidence(
            evidence=_strong_evidence(),
            tool_outputs=None,
            objective_domain=InvestigationDomain.PORTFOLIO_RECONCILIATION,
            objective_confidence=1.0,
            cause_domain=InvestigationDomain.PORTFOLIO_RECONCILIATION,
            specificity=1.0,
            has_meaningful_root_cause=True,
        )
        assert breakdown.final >= 70.0
        assert breakdown.caps_applied == []

    def test_no_90_to_100_when_evidence_or_domain_weak(self):
        weak = calibrate_confidence(
            evidence=_weak_evidence(),
            tool_outputs=None,
            objective_domain=InvestigationDomain.EXCHANGE_AUTH,
            objective_confidence=0.9,
            cause_domain=InvestigationDomain.EXCHANGE_AUTH,
            specificity=1.0,
            has_meaningful_root_cause=True,
        )
        mismatch = calibrate_confidence(
            evidence=_strong_evidence(),
            tool_outputs=None,
            objective_domain=InvestigationDomain.EXCHANGE_AUTH,
            objective_confidence=0.9,
            cause_domain=InvestigationDomain.ORDER_RECONCILIATION,
            specificity=1.0,
            has_meaningful_root_cause=True,
        )
        assert weak.final < 90.0
        assert mismatch.final < 90.0


# --------------------------------------------------------------------------- #
# Recommendation concreteness
# --------------------------------------------------------------------------- #


class TestRecommendationBuilder:
    def test_generic_phrase_detection(self):
        assert is_generic_recommendation("Review collected evidence and implement targeted fix.") is True
        assert is_generic_recommendation("No repair needed.") is True
        assert is_generic_recommendation("") is True
        assert is_generic_recommendation("Deduplicate runtime.env key/secret pair.") is False

    def test_template_backed_plan_is_concrete(self):
        plan = build_recommendation_plan(
            root_cause="Database has open orders but dashboard cache is empty",
            category="dashboard",
            evidence=[],
            existing_fix="Use DB fallback for dashboard counts and refresh open_orders_cache.",
        )
        assert plan.affected_files  # at least one concrete file
        assert plan.validation_steps  # at least one validation step
        assert plan.specificity >= 0.5
        assert not is_generic_recommendation(plan.proposed_fix)

    def test_actionable_plan_has_file_and_validation(self):
        plan = build_recommendation_plan(
            root_cause="Database has open orders but dashboard cache is empty",
            category="dashboard",
            evidence=[],
            existing_fix="Use DB fallback for dashboard counts.",
        )
        if plan.specificity > 0.1:
            assert len(plan.affected_files) >= 1
            assert len(plan.validation_steps) >= 1

    def test_generic_only_becomes_gap_statement(self):
        plan = build_recommendation_plan(
            root_cause="Something vague that matches no template",
            category="api",
            evidence=[],
            existing_fix="Review configuration and investigate further.",
        )
        assert plan.specificity <= 0.1
        assert plan.proposed_fix.startswith("Insufficient evidence")
        assert not is_generic_recommendation(plan.proposed_fix.replace("Insufficient evidence", ""))

    def test_evidence_derived_candidate_files(self):
        evidence = [
            {"source": "repository", "detail": "code ref", "confidence": "medium", "file_path": "backend/app/foo.py"},
        ]
        plan = build_recommendation_plan(
            root_cause="Concrete enough root cause for the api layer latency",
            category="api",
            evidence=evidence,
            existing_fix="Add request timeout to the api layer call path.",
        )
        assert any("backend/app/foo.py" in f for f in plan.affected_files)
        assert plan.specificity == pytest.approx(0.5)


# --------------------------------------------------------------------------- #
# build_investigation_report integration (flag on vs off)
# --------------------------------------------------------------------------- #


class TestReportIntegration:
    def _portfolio_inputs(self):
        evidence = [
            {
                "source": "portfolio",
                "detail": "Exchange equity fields found: accounts[].market_value; missing top-level equity",
                "confidence": "high",
                "is_direct": True,
            },
            {
                "source": "repository",
                "detail": "portfolio_cache derives equity from balances",
                "confidence": "high",
                "is_direct": True,
                "file_path": "backend/app/services/portfolio_cache.py",
            },
        ]
        ranked = [
            RootCauseCandidate(
                cause="Portfolio equity derived from balances because exchange omits a top-level equity field",
                score=90.0,
                supporting_evidence=["[portfolio] explicit equity gap"],
            )
        ]
        return evidence, ranked

    def test_flag_off_preserves_legacy_confidence(self, objective_aware_off):
        evidence, ranked = self._portfolio_inputs()
        report = build_investigation_report(
            investigation_id="t-off",
            objective="Investigate portfolio reconciliation mismatch",
            category="portfolio",
            template_id="portfolio_reconciliation_mismatch",
            evidence=evidence,
            ranked_causes=ranked,
            tool_outputs=[],
            created_at=_now(),
        )
        assert report.confidence == 90.0
        assert report.domain == ""
        assert report.confidence_breakdown == {}

    def test_flag_on_emits_domain_and_breakdown(self, objective_aware):
        evidence, ranked = self._portfolio_inputs()
        report = build_investigation_report(
            investigation_id="t-on",
            objective="Investigate portfolio reconciliation mismatch",
            category="portfolio",
            template_id="portfolio_reconciliation_mismatch",
            evidence=evidence,
            ranked_causes=ranked,
            tool_outputs=[],
            created_at=_now(),
        )
        assert report.domain == InvestigationDomain.PORTFOLIO_RECONCILIATION.value
        assert report.confidence_breakdown
        assert report.recommendation_plan
        assert report.recommendation_plan["affected_files"]
        # In-domain + concrete recommendation -> genuinely high but earned.
        assert report.confidence_breakdown["caps_applied"] == []

    def test_cross_domain_objective_blocks_promotion(self, objective_aware):
        # Auth objective misrouted to an order category with an order root cause.
        evidence = [
            {"source": "database", "detail": "order rows present", "confidence": "medium", "is_direct": False},
        ]
        ranked = [
            RootCauseCandidate(
                cause="FILLED orders exist in database but dashboard trade history does not display them",
                score=90.0,
            )
        ]
        report = build_investigation_report(
            investigation_id="t-cross",
            objective="Investigate Crypto.com authentication failures (40101)",
            category="orders",
            template_id="generic",
            evidence=evidence,
            ranked_causes=ranked,
            tool_outputs=[],
            created_at=_now(),
        )
        assert report.confidence <= 50.0
        assert report.status == InvestigationStatus.INSUFFICIENT_EVIDENCE

    def test_cross_domain_completes_when_flag_off(self, objective_aware_off):
        evidence = [
            {"source": "database", "detail": "order rows present", "confidence": "medium", "is_direct": False},
        ]
        ranked = [
            RootCauseCandidate(
                cause="FILLED orders exist in database but dashboard trade history does not display them",
                score=90.0,
            )
        ]
        report = build_investigation_report(
            investigation_id="t-cross-off",
            objective="Investigate Crypto.com authentication failures (40101)",
            category="orders",
            template_id="generic",
            evidence=evidence,
            ranked_causes=ranked,
            tool_outputs=[],
            created_at=_now(),
        )
        # Legacy behavior: order cause promoted at full score.
        assert report.confidence == 90.0
        assert report.root_cause is not None

    def test_rank_root_causes_unchanged_when_flag_off(self, objective_aware_off):
        ranked = rank_root_causes(
            evidence=[
                {"source": "database", "reference": "orders", "detail": "x", "confidence": "high", "is_direct": True}
            ],
            category="authentication",
            tool_outputs=[{"tool": "t", "ok": True, "root_cause": "Some order cause about filled orders"}],
            objective="Investigate authentication failures",
        )
        # No domain assigned and scores not re-weighted when the flag is off.
        assert all(c.domain == "" for c in ranked)


# --------------------------------------------------------------------------- #
# ACW invariance: the new flag must not change self-healing gating
# --------------------------------------------------------------------------- #


class TestAcwInvariance:
    def _report_dict(self) -> dict:
        from app.jarvis.investigations.investigation_report import InvestigationReport

        return InvestigationReport(
            investigation_id="inv-acw",
            objective="Why is the dashboard open-order count different from the database?",
            category="dashboard",
            template_id="generic",
            status=InvestigationStatus.COMPLETED,
            summary="DB has open orders, dashboard cache empty.",
            evidence=[
                {"source": "database", "reference": "orders", "detail": "db rows=3", "confidence": "high"},
                {"source": "cache", "reference": "open_orders", "detail": "cache=0", "confidence": "high"},
            ],
            root_cause="Database has open orders but dashboard cache is empty",
            confidence=82.0,
            ranked_causes=[],
            impact="Dashboard understates open orders.",
            recommended_fix="Use DB fallback for dashboard counts and refresh open_orders_cache.",
            verification_steps=["Confirm DB fallback populates dashboard."],
            next_action="Recommend fix.",
            created_at=_now(),
        ).to_dict()

    def test_acw_gating_identical_with_flag_on_and_off(self, monkeypatch):
        from app.jarvis.self_healing.service import build_recommendation

        monkeypatch.setenv("JARVIS_SELF_HEALING_ENABLED", "true")
        monkeypatch.setenv("JARVIS_SELF_HEALING_ACW_THRESHOLD", "70")

        monkeypatch.delenv("JARVIS_OBJECTIVE_AWARE_RC", raising=False)
        rec_off = build_recommendation(self._report_dict())

        monkeypatch.setenv("JARVIS_OBJECTIVE_AWARE_RC", "true")
        rec_on = build_recommendation(self._report_dict())

        assert rec_off["acw_ready"] == rec_on["acw_ready"]
        assert rec_off["acw"]["reasons"] == rec_on["acw"]["reasons"]
        assert rec_off["safety"]["allowed"] == rec_on["safety"]["allowed"]

    def test_low_confidence_still_blocks_acw(self, monkeypatch):
        from app.jarvis.self_healing.service import build_recommendation

        monkeypatch.setenv("JARVIS_SELF_HEALING_ENABLED", "true")
        monkeypatch.setenv("JARVIS_SELF_HEALING_ACW_THRESHOLD", "70")
        monkeypatch.setenv("JARVIS_OBJECTIVE_AWARE_RC", "true")

        report = self._report_dict()
        report["confidence"] = 40.0
        rec = build_recommendation(report)
        assert rec["acw_ready"] is False
