"""Tests for Jarvis Phase 4B fix template registry."""

from __future__ import annotations

from app.jarvis.proposals.fix_templates import (
    find_fix_templates_for_root_cause,
    get_fix_template,
    list_fix_templates,
)

TRIGGER_ROOT_CAUSE = "Trigger order API failure blocks cache updates"


class TestFixTemplates:
    def test_list_fix_templates_includes_pilot_template(self):
        templates = list_fix_templates()
        assert len(templates) >= 1
        ids = {t["fix_template_id"] for t in templates}
        assert "orders.trigger_50001_cache_independent" in ids

    def test_get_fix_template_by_id(self):
        template = get_fix_template("orders.trigger_50001_cache_independent")
        assert template is not None
        assert template["match"] == TRIGGER_ROOT_CAUSE
        assert template["strategy"] == "template"
        assert template["no_fix_required"] is False
        assert "backend/app/services/exchange_sync.py" in template["target_files"]
        assert "backend/tests/test_crypto_com_sync_status.py" in template["test_paths"]

    def test_lookup_for_trigger_50001_root_cause(self):
        matches = find_fix_templates_for_root_cause(TRIGGER_ROOT_CAUSE)
        assert len(matches) == 1
        assert matches[0]["fix_template_id"] == "orders.trigger_50001_cache_independent"
        assert matches[0]["match"] == TRIGGER_ROOT_CAUSE

    def test_unknown_root_cause_returns_empty(self):
        assert find_fix_templates_for_root_cause("Some unknown root cause") == []

    def test_unknown_template_id_returns_none(self):
        assert get_fix_template("does.not.exist") is None
