"""Tests for Jarvis Phase 4B template matching, ranking, and API endpoints."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes_jarvis import router as jarvis_router
from app.jarvis.proposals.eligibility import ProposalEligibilityConfig, check_proposal_eligibility
from app.jarvis.proposals.patch_generator import generate_patch_for_template, is_fix_already_present
from app.jarvis.proposals.template_catalog import FIX_TEMPLATES
from app.jarvis.proposals.template_matching import match_templates_for_investigation
from app.jarvis.investigations.investigation_types import InvestigationStatus
from app.services._paths import workspace_root

TRIGGER_ROOT_CAUSE = "Trigger order API failure blocks cache updates"
AUTH_ROOT_CAUSE = "Duplicated API secret in runtime.env causes Crypto.com auth failure (40101)"
DB_CACHE_ROOT_CAUSE = "Database has open orders but dashboard cache is empty"
EQUITY_ROOT_CAUSE = (
    "Portfolio equity derived from balances because exchange API omits equity field"
)
WS_ROOT_CAUSE = "Websocket price feed disconnected or not receiving updates"


def _investigation(**overrides):
    base = {
        "investigation_id": "inv-template-test",
        "objective": "Diagnose production issue",
        "category": "orders",
        "status": InvestigationStatus.COMPLETED.value,
        "summary": "",
        "root_cause": TRIGGER_ROOT_CAUSE,
        "confidence": 80.0,
        "recommended_fix": "Allow regular open orders to update cache independently when trigger-order sync fails.",
        "proposal_task_id": None,
        "proposal_status": None,
    }
    base.update(overrides)
    return base


@pytest.fixture()
def template_api_client():
    app = FastAPI()
    app.include_router(jarvis_router)
    return TestClient(app)


class TestTemplateExactMatching:
    @pytest.mark.parametrize(
        ("root_cause", "expected_template"),
        [
            (TRIGGER_ROOT_CAUSE, "orders.trigger_50001_cache_independent"),
            (AUTH_ROOT_CAUSE, "crypto.auth_40101_mismatch"),
            (DB_CACHE_ROOT_CAUSE, "dashboard.cache_db_mismatch"),
            (EQUITY_ROOT_CAUSE, "portfolio.equity_derived_fallback"),
            (WS_ROOT_CAUSE, "websocket.same_origin_regression"),
        ],
    )
    def test_exact_root_cause_selects_primary_template(self, root_cause, expected_template):
        result = match_templates_for_investigation({"root_cause": root_cause})
        assert result.primary_template == expected_template
        assert result.score >= 100

    def test_stale_cache_pattern_matches_open_orders_template(self):
        result = match_templates_for_investigation(
            {
                "root_cause": "Open orders stale cache with exchange=1 db=1 cache=0",
                "summary": "stale_cache_db_fallback observed in resolver",
                "category": "orders",
            }
        )
        assert result.primary_template == "open_orders.stale_cache_fallback"

    def test_order_history_pattern_matches_exchange_sync_template(self):
        result = match_templates_for_investigation(
            {
                "root_cause": "Order history sync monopolizes loop and delays open-order refresh",
                "summary": "sync_open_orders never executes during long order history scan",
                "category": "exchange_sync",
            }
        )
        assert result.primary_template == "exchange_sync_blocked_by_order_history"

    def test_telegram_startup_pattern_matches_telegram_template(self):
        result = match_templates_for_investigation(
            {
                "root_cause": "Telegram bot command registration fails during startup",
                "summary": "setMyCommands failure returned HTTP 400 from Telegram API",
                "category": "telegram",
            }
        )
        assert result.primary_template == "telegram.bot_command_setup_failure"


class TestTemplatePatternMatching:
    @pytest.mark.parametrize(
        ("blob", "expected_template"),
        [
            ("40101 authentication failure on private endpoints", "crypto.auth_40101_mismatch"),
            ("runtime.env credential mismatch duplicated secret", "crypto.auth_40101_mismatch"),
            ("dashboard empty but db contains rows cache=0 db>0", "dashboard.cache_db_mismatch"),
            ("exchange equity missing derived calculation active", "portfolio.equity_derived_fallback"),
            ("browser websocket failures mixed content ws://api", "websocket.same_origin_regression"),
            ("empty in-memory cache stale cache fallback", "open_orders.stale_cache_fallback"),
            ("order history scan blocks sync_open_orders", "exchange_sync_blocked_by_order_history"),
            ("telegram bot startup warning setmycommands failure", "telegram.bot_command_setup_failure"),
        ],
    )
    def test_pattern_blob_matches_expected_template(self, blob, expected_template):
        result = match_templates_for_investigation({"root_cause": blob})
        assert result.primary_template == expected_template
        assert result.score >= 25


class TestTemplateAmbiguityAndRanking:
    def test_ambiguous_cache_mismatch_returns_alternatives(self):
        result = match_templates_for_investigation(
            {
                "root_cause": DB_CACHE_ROOT_CAUSE,
                "summary": "stale cache empty in-memory cache=0 db=1 exchange=1",
                "category": "dashboard",
            }
        )
        assert result.primary_template in {
            "dashboard.cache_db_mismatch",
            "open_orders.stale_cache_fallback",
        }
        assert isinstance(result.alternatives, list)

    def test_candidates_sorted_by_score_descending(self):
        result = match_templates_for_investigation({"root_cause": TRIGGER_ROOT_CAUSE})
        scores = [candidate["score"] for candidate in result.fix_template_candidates]
        assert scores == sorted(scores, reverse=True)

    def test_candidate_includes_template_confidence(self):
        result = match_templates_for_investigation({"root_cause": AUTH_ROOT_CAUSE})
        assert result.fix_template_candidates[0]["template_confidence"] >= 25

    def test_multiple_templates_match_auth_and_cache_overlap(self):
        result = match_templates_for_investigation(
            {
                "root_cause": "40101 auth failure and dashboard cache stale with db rows present",
                "summary": "private endpoints fail while public endpoints succeed",
            }
        )
        ids = {candidate["fix_template_id"] for candidate in result.fix_template_candidates}
        assert "crypto.auth_40101_mismatch" in ids


class TestTemplateNoMatch:
    def test_unknown_root_cause_has_no_primary_template(self):
        result = match_templates_for_investigation({"root_cause": "Completely novel failure mode xyz"})
        assert result.primary_template is None
        assert result.fix_template_candidates == []

    def test_empty_investigation_has_no_matches(self):
        result = match_templates_for_investigation({})
        assert result.primary_template is None

    @pytest.mark.parametrize(
        "root_cause",
        [
            "",
            "   ",
            "Unrelated deployment issue with no template coverage",
        ],
    )
    def test_non_matching_root_causes_return_empty_candidates(self, root_cause):
        result = match_templates_for_investigation({"root_cause": root_cause})
        assert result.fix_template_candidates == []


class TestEligibilityTemplateEnhancements:
    def test_eligibility_includes_primary_template_and_score(self):
        result = check_proposal_eligibility(
            _investigation(),
            config=ProposalEligibilityConfig(proposals_enabled=True, min_confidence=50.0),
        )
        assert result.eligible is True
        assert result.primary_template == "orders.trigger_50001_cache_independent"
        assert result.template_score >= 100
        assert result.template_confidence >= 25

    def test_eligibility_includes_alternatives_list(self):
        result = check_proposal_eligibility(
            _investigation(
                root_cause=DB_CACHE_ROOT_CAUSE,
                recommended_fix="Use DB fallback and refresh cache.",
                summary="stale cache db fallback",
                category="dashboard",
            ),
            config=ProposalEligibilityConfig(proposals_enabled=True, min_confidence=50.0),
        )
        assert isinstance(result.alternatives, list)

    def test_eligibility_no_fix_required_reason_when_fix_present(self):
        repo = workspace_root()
        result = check_proposal_eligibility(
            _investigation(),
            config=ProposalEligibilityConfig(proposals_enabled=True, min_confidence=50.0),
            repo_root=repo,
        )
        if is_fix_already_present(repo, "orders.trigger_50001_cache_independent"):
            assert result.no_fix_required_reason

    def test_eligibility_unknown_root_cause_not_eligible(self):
        result = check_proposal_eligibility(
            _investigation(root_cause="Unknown exotic production failure"),
            config=ProposalEligibilityConfig(proposals_enabled=True, min_confidence=50.0),
        )
        assert result.eligible is False
        assert "no_fix_template" in result.reasons
        assert result.primary_template is None


class TestNoFixRequiredPath:
    @pytest.mark.parametrize(
        "template_id",
        [template.fix_template_id for template in FIX_TEMPLATES],
    )
    def test_repo_markers_present_for_catalog_template(self, template_id):
        repo = workspace_root()
        assert is_fix_already_present(repo, template_id), template_id

    @pytest.mark.parametrize(
        "template_id",
        [template.fix_template_id for template in FIX_TEMPLATES],
    )
    def test_generate_patch_is_noop_when_fix_present(self, template_id):
        repo = workspace_root()
        if not is_fix_already_present(repo, template_id):
            pytest.skip(f"fix not present for {template_id}")
        result = generate_patch_for_template(template_id, repo_root=repo)
        assert result.is_noop is True
        assert result.fix_already_present is True
        assert "no-op" in result.patch_content.lower() or "fix already present" in result.patch_content.lower()


class TestTemplateAPIEndpoints:
    def test_list_templates_endpoint(self, template_api_client):
        resp = template_api_client.get("/api/jarvis/templates")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 8
        assert len(body["templates"]) == 8
        ids = {item["fix_template_id"] for item in body["templates"]}
        assert "orders.trigger_50001_cache_independent" in ids

    def test_get_template_detail_endpoint(self, template_api_client):
        resp = template_api_client.get("/api/jarvis/templates/crypto.auth_40101_mismatch")
        assert resp.status_code == 200
        body = resp.json()
        assert body["fix_template_id"] == "crypto.auth_40101_mismatch"
        assert body["validation_rules"]
        assert body["match_patterns"]
        assert body["risk_level"] == "high"

    def test_get_unknown_template_returns_404(self, template_api_client):
        resp = template_api_client.get("/api/jarvis/templates/not.a.real.template")
        assert resp.status_code == 404

    def test_template_summary_fields(self, template_api_client):
        resp = template_api_client.get("/api/jarvis/templates")
        template = next(
            item
            for item in resp.json()["templates"]
            if item["fix_template_id"] == "portfolio.equity_derived_fallback"
        )
        assert template["description"]
        assert "backend/app/services/portfolio_cache.py" in template["target_files"]
        assert template["risk_level"] == "low"


class TestTemplateCoverageMatrix:
    @pytest.mark.parametrize(
        ("template_id", "risk_level"),
        [
            ("orders.trigger_50001_cache_independent", "medium"),
            ("crypto.auth_40101_mismatch", "high"),
            ("dashboard.cache_db_mismatch", "medium"),
            ("portfolio.equity_derived_fallback", "low"),
            ("websocket.same_origin_regression", "low"),
            ("open_orders.stale_cache_fallback", "medium"),
            ("exchange_sync_blocked_by_order_history", "medium"),
            ("telegram.bot_command_setup_failure", "low"),
        ],
    )
    def test_template_risk_level(self, template_id, risk_level):
        template = next(t for t in FIX_TEMPLATES if t.fix_template_id == template_id)
        assert template.risk_level == risk_level

    @pytest.mark.parametrize("template_id", [t.fix_template_id for t in FIX_TEMPLATES])
    def test_template_has_supported_investigations(self, template_id):
        template = next(t for t in FIX_TEMPLATES if t.fix_template_id == template_id)
        assert len(template.supported_investigations) >= 1

    @pytest.mark.parametrize("template_id", [t.fix_template_id for t in FIX_TEMPLATES])
    def test_template_has_validation_rules(self, template_id):
        template = next(t for t in FIX_TEMPLATES if t.fix_template_id == template_id)
        assert len(template.validation_rules) >= 1
