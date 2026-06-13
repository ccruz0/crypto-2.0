"""Tests for Jarvis Phase 4B fix template registry and catalog."""

from __future__ import annotations

import pytest

from app.jarvis.proposals.fix_templates import (
    find_fix_templates_for_root_cause,
    get_fix_template,
    get_fix_template_detail,
    list_fix_template_summaries,
    list_fix_templates,
    match_templates_for_investigation,
)
from app.jarvis.proposals.template_catalog import FIX_TEMPLATES

TRIGGER_ROOT_CAUSE = "Trigger order API failure blocks cache updates"

EXPECTED_TEMPLATE_IDS = (
    "orders.trigger_50001_cache_independent",
    "crypto.auth_40101_mismatch",
    "dashboard.cache_db_mismatch",
    "portfolio.equity_derived_fallback",
    "websocket.same_origin_regression",
    "open_orders.stale_cache_fallback",
    "exchange_sync_blocked_by_order_history",
    "telegram.bot_command_setup_failure",
)


class TestFixTemplateCatalog:
    def test_catalog_contains_eight_templates(self):
        assert len(FIX_TEMPLATES) == 8

    @pytest.mark.parametrize("template_id", EXPECTED_TEMPLATE_IDS)
    def test_catalog_includes_expected_template(self, template_id: str):
        ids = {template.fix_template_id for template in FIX_TEMPLATES}
        assert template_id in ids

    @pytest.mark.parametrize("template_id", EXPECTED_TEMPLATE_IDS)
    def test_template_has_required_fields(self, template_id: str):
        template = next(t for t in FIX_TEMPLATES if t.fix_template_id == template_id)
        assert template.description
        assert template.match_patterns
        assert template.target_files
        assert template.recommended_fix
        assert template.risk_level in {"low", "medium", "high"}
        assert template.test_paths
        assert template.validation_rules
        assert template.supported_investigations

    def test_list_fix_templates_includes_all_templates(self):
        templates = list_fix_templates()
        assert len(templates) == 8
        ids = {t["fix_template_id"] for t in templates}
        assert set(EXPECTED_TEMPLATE_IDS) == ids

    def test_list_fix_template_summaries_shape(self):
        summaries = list_fix_template_summaries()
        assert len(summaries) == 8
        first = summaries[0]
        assert {"fix_template_id", "description", "target_files", "supported_investigations", "risk_level"} <= set(
            first.keys()
        )

    def test_get_fix_template_by_id(self):
        template = get_fix_template("orders.trigger_50001_cache_independent")
        assert template is not None
        assert template["match"] == TRIGGER_ROOT_CAUSE
        assert template["strategy"] == "template"
        assert "backend/app/services/exchange_sync.py" in template["target_files"]

    def test_get_fix_template_detail_includes_full_metadata(self):
        detail = get_fix_template_detail("crypto.auth_40101_mismatch")
        assert detail is not None
        assert detail["root_cause_exact"]
        assert detail["noop_reason"]
        assert detail["validation_rules"]
        assert detail["match_patterns"]

    def test_unknown_template_id_returns_none(self):
        assert get_fix_template("does.not.exist") is None
        assert get_fix_template_detail("does.not.exist") is None


class TestFixTemplateLookup:
    def test_lookup_for_trigger_50001_root_cause(self):
        matches = find_fix_templates_for_root_cause(TRIGGER_ROOT_CAUSE)
        assert len(matches) >= 1
        assert matches[0]["fix_template_id"] == "orders.trigger_50001_cache_independent"
        assert matches[0]["score"] >= 100

    def test_unknown_root_cause_returns_empty(self):
        assert find_fix_templates_for_root_cause("Some unknown root cause") == []

    def test_match_investigation_returns_primary_template(self):
        result = match_templates_for_investigation(
            {
                "root_cause": TRIGGER_ROOT_CAUSE,
                "recommended_fix": "Allow regular open orders to update cache independently.",
                "category": "orders",
            }
        )
        assert result.primary_template == "orders.trigger_50001_cache_independent"
        assert result.score >= 100
