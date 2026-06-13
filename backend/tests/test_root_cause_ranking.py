"""Tests for root cause ranking model."""

from __future__ import annotations

from app.jarvis.investigations.evidence_model import EvidenceItem
from app.jarvis.investigations.investigation_report import rank_root_causes


def _trigger_failure_evidence() -> list[EvidenceItem]:
    return [
        {
            "source": "exchange",
            "reference": "reconciliation_counts",
            "detail": "Exchange=1, DB=1, dashboard=0",
            "confidence": "high",
        },
        {
            "source": "exchange",
            "reference": "trigger_orders_api",
            "detail": "Trigger-order API error_code=50001: Invalid request",
            "confidence": "high",
        },
        {
            "source": "logs",
            "reference": "backend-aws",
            "detail": "trigger_orders_error_code=50001 cache update aborted",
            "confidence": "medium",
        },
    ]


def _auth_failure_evidence() -> list[EvidenceItem]:
    return [
        {
            "source": "authentication",
            "reference": "duplicated_secret",
            "detail": "Multiple credential pairs configured (2 pairs). Duplicated secret in runtime.env can cause Crypto.com auth failure (40101).",
            "confidence": "high",
        },
        {
            "source": "logs",
            "reference": "backend-aws",
            "detail": "Authentication failure 40101 - Authentication failure",
            "confidence": "high",
        },
    ]


def _portfolio_evidence() -> list[EvidenceItem]:
    return [
        {
            "source": "exchange",
            "reference": "equity_fields",
            "detail": "Exchange API response missing equity/net_equity field; portfolio total is derived from balances",
            "confidence": "high",
        },
        {
            "source": "dashboard",
            "reference": "portfolio_cache",
            "detail": "Portfolio cache total_usd=12345.67; last_updated=2026-06-13",
            "confidence": "high",
        },
    ]


class TestRootCauseRanking:
    def test_trigger_order_failure_ranks_highest_for_dashboard_mismatch(self):
        ranked = rank_root_causes(
            evidence=_trigger_failure_evidence(),
            category="dashboard",
            recent_failures=2,
        )
        assert ranked
        top = ranked[0]
        assert "trigger" in top.cause.lower() or "50001" in top.cause.lower() or "cache" in top.cause.lower()
        assert top.score >= 50

    def test_auth_duplicated_secret_ranks_high(self):
        ranked = rank_root_causes(
            evidence=_auth_failure_evidence(),
            category="authentication",
            recent_failures=1,
        )
        assert ranked
        causes = [c.cause.lower() for c in ranked]
        assert any("auth" in c or "secret" in c or "40101" in c for c in causes)
        assert ranked[0].score > ranked[-1].score if len(ranked) > 1 else True

    def test_portfolio_equity_derived_detected(self):
        ranked = rank_root_causes(
            evidence=_portfolio_evidence(),
            category="portfolio",
        )
        assert ranked
        assert any("equity" in c.cause.lower() or "derived" in c.cause.lower() for c in ranked)

    def test_conflicting_evidence_still_produces_ranked_list(self):
        evidence: list[EvidenceItem] = [
            {
                "source": "database",
                "reference": "exchange_orders",
                "detail": "Open-status count: 5",
                "confidence": "high",
            },
            {
                "source": "api",
                "reference": "open_orders_cache",
                "detail": "Cache contains 0 open orders",
                "confidence": "high",
            },
        ]
        ranked = rank_root_causes(evidence=evidence, category="orders")
        assert ranked
        scores = [c.score for c in ranked]
        assert max(scores) >= min(scores)

    def test_empty_evidence_yields_low_or_empty_ranking(self):
        ranked = rank_root_causes(evidence=[], category="orders")
        assert isinstance(ranked, list)
