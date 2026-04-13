"""Jarvis Marketing Intelligence: read-only tools, safe unavailability, registry wiring."""

from __future__ import annotations

import pytest

from app.jarvis.approval_storage import (
    APPROVAL_AUTO_APPROVED,
    EXEC_EXECUTED,
    EXEC_NOT_EXECUTED,
    get_default_approval_storage,
    reset_default_approval_storage_for_tests,
)
from app.jarvis.auto_execution import should_auto_execute
from app.jarvis.executor import execute_plan, invoke_registered_tool
from app.jarvis.tools import TOOL_SPECS


@pytest.fixture(autouse=True)
def _clear_marketing_env(monkeypatch):
    reset_default_approval_storage_for_tests()
    for k in (
        "JARVIS_GSC_SITE_URL",
        "JARVIS_GSC_CREDENTIALS_JSON",
        "JARVIS_GA4_PROPERTY_ID",
        "JARVIS_GA4_CREDENTIALS_JSON",
        "JARVIS_GA4_BOOKING_EVENT_NAME",
        "JARVIS_GOOGLE_ADS_CUSTOMER_ID",
        "JARVIS_GOOGLE_ADS_DEVELOPER_TOKEN",
        "JARVIS_GOOGLE_ADS_CREDENTIALS_JSON",
        "JARVIS_MARKETING_SITE_URL",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "JARVIS_MARKETING_LIVE_APIS",
    ):
        monkeypatch.delenv(k, raising=False)


def test_list_marketing_tools_status_missing_config():
    out = TOOL_SPECS["list_marketing_tools_status"].fn()
    assert out["status"] == "ok"
    assert out["business"] == "Peluquería Cruz"
    sources = {s["source"]: s for s in out["sources"]}
    assert sources["google_search_console"]["configured"] is False
    assert sources["ga4"]["configured"] is False
    assert sources["google_ads"]["configured"] is False
    assert sources["site"]["configured"] is False


def test_get_search_console_summary_unavailable_without_config():
    out = TOOL_SPECS["get_search_console_summary"].fn()
    assert out["status"] == "unavailable"
    assert out["source"] == "google_search_console"
    assert out["reason"] == "not_configured"


def test_get_ga4_booking_funnel_missing_event_mapping(tmp_path, monkeypatch):
    creds = tmp_path / "ga4.json"
    creds.write_text("{}")
    monkeypatch.setenv("JARVIS_GA4_PROPERTY_ID", "properties/123")
    monkeypatch.setenv("JARVIS_GA4_CREDENTIALS_JSON", str(creds))
    monkeypatch.delenv("JARVIS_GA4_BOOKING_EVENT_NAME", raising=False)
    out = TOOL_SPECS["get_ga4_booking_funnel"].fn()
    assert out["status"] == "unavailable"
    assert out["reason"] == "missing_event_mapping"
    assert "JARVIS_GA4_BOOKING_EVENT_NAME" in out["message"]


def test_get_google_ads_summary_unavailable_without_config():
    out = TOOL_SPECS["get_google_ads_summary"].fn()
    assert out["status"] == "unavailable"
    assert out["source"] == "google_ads"
    assert out["reason"] == "not_configured"


def test_get_top_pages_by_conversion_unavailable_without_config():
    out = TOOL_SPECS["get_top_pages_by_conversion"].fn()
    assert out["status"] == "unavailable"
    assert out["reason"] == "not_configured"


def test_marketing_tools_in_registry_metadata():
    names = {
        "list_marketing_tools_status",
        "get_search_console_summary",
        "get_ga4_booking_funnel",
        "get_google_ads_summary",
        "get_top_pages_by_conversion",
        "analyze_marketing_opportunities",
        "propose_marketing_actions",
        "stage_marketing_action_for_approval",
    }
    for n in names:
        spec = TOOL_SPECS[n]
        assert spec.policy.value == "safe"
        expected_category = "write" if n == "stage_marketing_action_for_approval" else "read"
        assert spec.category.value == expected_category


def test_execute_plan_marketing_tools_unavailable_mode_no_crash():
    r0 = execute_plan(
        {"action": "list_marketing_tools_status", "args": {}, "reasoning": "test"},
        jarvis_run_id="mkt-0",
    )
    assert isinstance(r0, dict)
    assert "error" not in r0
    assert r0.get("status") == "ok"

    for action in (
        "get_search_console_summary",
        "get_ga4_booking_funnel",
        "get_google_ads_summary",
        "get_top_pages_by_conversion",
    ):
        r = execute_plan(
            {"action": action, "args": {}, "reasoning": "test"},
            jarvis_run_id="mkt-1",
        )
        assert isinstance(r, dict)
        assert "error" not in r
        assert r.get("status") == "unavailable"


def test_invoke_registered_tool_marketing_no_crash():
    r = invoke_registered_tool("get_search_console_summary", {}, jarvis_run_id="x")
    assert isinstance(r, dict)
    assert r.get("status") == "unavailable"


def test_get_search_console_summary_ok_mocked(monkeypatch):
    from app.jarvis import marketing_sources as ms
    from app.jarvis import marketing_tools as mt

    monkeypatch.setattr(
        mt,
        "fetch_search_console_summary",
        lambda days_back: ms.build_search_console_ok_sample(days_back=days_back),
    )
    out = TOOL_SPECS["get_search_console_summary"].fn(days_back=7)
    assert out["status"] == "ok"
    assert out["aggregate"]["clicks"] == 1200
    assert out["date_range"]["days_back"] == 7


def test_list_available_tools_includes_marketing():
    out = TOOL_SPECS["list_available_tools"].fn()
    names = {t["name"] for t in out["tools"]}
    assert "get_search_console_summary" in names
    assert "list_marketing_tools_status" in names
    assert "analyze_marketing_opportunities" in names
    assert "propose_marketing_actions" in names
    assert "stage_marketing_action_for_approval" in names


def test_analyze_marketing_opportunities_all_sources_unavailable_structured():
    out = TOOL_SPECS["analyze_marketing_opportunities"].fn()
    assert out["status"] == "ok"
    assert out["business"] == "Peluquería Cruz"
    assert out["days_back"] == 28
    assert out["top_n"] == 5
    assert "google_search_console" in out["sources_checked"]
    assert isinstance(out["unavailable_sources"], list)
    assert len(out["unavailable_sources"]) >= 1
    assert isinstance(out["missing_data"], list)
    assert len(out["missing_data"]) >= 1


def test_analyze_marketing_opportunities_mixed_availability(monkeypatch):
    from app.jarvis import marketing_sources as ms
    from app.jarvis import marketing_opportunity_analysis as moa

    monkeypatch.setattr(
        moa,
        "fetch_search_console_summary",
        lambda days_back: ms.build_search_console_ok_sample(days_back=days_back),
    )

    out = TOOL_SPECS["analyze_marketing_opportunities"].fn(days_back=14, top_n=3)
    assert out["status"] == "ok"
    assert "google_search_console" in out["available_sources"]
    assert isinstance(out["biggest_opportunities"], list)


def test_analyze_marketing_opportunities_mocked_ads_waste(monkeypatch):
    from app.jarvis import marketing_sources as ms
    from app.jarvis import marketing_opportunity_analysis as moa

    monkeypatch.setattr(
        moa,
        "fetch_google_ads_summary",
        lambda days_back: ms.build_google_ads_waste_sample(days_back=days_back),
    )
    out = TOOL_SPECS["analyze_marketing_opportunities"].fn(top_n=5)
    wastes = out["biggest_wastes"]
    assert any(w.get("type") == "sem_spend_no_conv" for w in wastes)


def test_analyze_marketing_opportunities_mocked_gsc_opportunity(monkeypatch):
    from app.jarvis import marketing_sources as ms
    from app.jarvis import marketing_opportunity_analysis as moa

    monkeypatch.setattr(
        moa,
        "fetch_search_console_summary",
        lambda days_back: ms.build_search_console_opportunity_sample(days_back=days_back),
    )
    out = TOOL_SPECS["analyze_marketing_opportunities"].fn(top_n=5)
    opps = out["biggest_opportunities"]
    assert any(o.get("type") in ("seo_ctr", "seo_page_ctr") for o in opps)


def test_analyze_marketing_opportunities_conversion_gap_mocked(monkeypatch):
    from app.jarvis import marketing_sources as ms
    from app.jarvis import marketing_opportunity_analysis as moa

    monkeypatch.setattr(
        moa,
        "fetch_top_pages_by_conversion",
        lambda days_back, limit: ms.build_top_pages_gap_sample(days_back=days_back, limit=limit),
    )
    out = TOOL_SPECS["analyze_marketing_opportunities"].fn(top_n=5)
    gaps = out["conversion_gaps"]
    assert any(g.get("type") == "conversion_gap_page" for g in gaps)


def test_analyze_marketing_opportunities_missing_booking_event_in_missing_data(tmp_path, monkeypatch):
    creds = tmp_path / "ga4.json"
    creds.write_text("{}")
    monkeypatch.setenv("JARVIS_GA4_PROPERTY_ID", "properties/1")
    monkeypatch.setenv("JARVIS_GA4_CREDENTIALS_JSON", str(creds))
    monkeypatch.delenv("JARVIS_GA4_BOOKING_EVENT_NAME", raising=False)

    out = TOOL_SPECS["analyze_marketing_opportunities"].fn()
    md = out["missing_data"]
    assert any(
        (m.get("value") == "missing_event_mapping" or m.get("type") == "missing_event_mapping")
        for m in md
    )


def test_execute_plan_analyze_marketing_opportunities_no_crash():
    r = execute_plan(
        {"action": "analyze_marketing_opportunities", "args": {}, "reasoning": "t"},
        jarvis_run_id="opp-1",
    )
    assert isinstance(r, dict)
    assert "error" not in r
    assert r.get("status") == "ok"


_PROPOSE_FIELDS = {
    "action_type",
    "title",
    "summary",
    "source",
    "target",
    "reason",
    "priority",
    "suggested_channel",
    "requires_human_review",
    "supporting_metrics",
}


def test_propose_marketing_actions_all_sources_unavailable_structured():
    out = TOOL_SPECS["propose_marketing_actions"].fn()
    assert out["status"] in ("ok", "insufficient_data")
    assert out["business"] == "Peluquería Cruz"
    assert "analysis_status" in out
    assert isinstance(out["proposed_actions"], list)
    assert isinstance(out["missing_data"], list)
    assert isinstance(out["unavailable_sources"], list)
    if out["status"] == "ok":
        assert len(out["proposed_actions"]) >= 1


def test_propose_marketing_actions_seo_snippet_mocked(monkeypatch):
    from app.jarvis import marketing_sources as ms
    from app.jarvis import marketing_opportunity_analysis as moa

    monkeypatch.setattr(
        moa,
        "fetch_search_console_summary",
        lambda days_back: ms.build_search_console_opportunity_sample(days_back=days_back),
    )
    out = TOOL_SPECS["propose_marketing_actions"].fn(top_n=10)
    types = {p["action_type"] for p in out["proposed_actions"]}
    assert "improve_seo_snippet" in types or "improve_meta_description" in types


def test_propose_marketing_actions_ads_budget_mocked(monkeypatch):
    from app.jarvis import marketing_sources as ms
    from app.jarvis import marketing_opportunity_analysis as moa

    monkeypatch.setattr(
        moa,
        "fetch_google_ads_summary",
        lambda days_back: ms.build_google_ads_waste_sample(days_back=days_back),
    )
    out = TOOL_SPECS["propose_marketing_actions"].fn(top_n=10)
    assert any(
        p["action_type"] in ("pause_or_reduce_budget", "review_campaign_targeting")
        for p in out["proposed_actions"]
    )


def test_propose_marketing_actions_landing_cta_mocked(monkeypatch):
    from app.jarvis import marketing_sources as ms
    from app.jarvis import marketing_opportunity_analysis as moa

    monkeypatch.setattr(
        moa,
        "fetch_top_pages_by_conversion",
        lambda days_back, limit: ms.build_top_pages_gap_sample(days_back=days_back, limit=limit),
    )
    out = TOOL_SPECS["propose_marketing_actions"].fn(top_n=10)
    assert any(p["action_type"] == "improve_landing_page_cta" for p in out["proposed_actions"])


def test_propose_marketing_actions_ga4_booking_event_proposal(tmp_path, monkeypatch):
    creds = tmp_path / "ga4.json"
    creds.write_text("{}")
    monkeypatch.setenv("JARVIS_GA4_PROPERTY_ID", "properties/1")
    monkeypatch.setenv("JARVIS_GA4_CREDENTIALS_JSON", str(creds))
    monkeypatch.delenv("JARVIS_GA4_BOOKING_EVENT_NAME", raising=False)

    out = TOOL_SPECS["propose_marketing_actions"].fn(top_n=10)
    assert any(p["action_type"] == "configure_ga4_booking_event" for p in out["proposed_actions"])


def test_propose_marketing_actions_stable_fields_and_priorities():
    out = TOOL_SPECS["propose_marketing_actions"].fn(top_n=5)
    for p in out["proposed_actions"]:
        assert _PROPOSE_FIELDS == set(p.keys())
        assert p["priority"] in ("high", "medium", "low")
        assert p["requires_human_review"] is True


def test_execute_plan_propose_marketing_actions_no_crash():
    r = execute_plan(
        {"action": "propose_marketing_actions", "args": {}, "reasoning": "t"},
        jarvis_run_id="prop-1",
    )
    assert isinstance(r, dict)
    assert "error" not in r
    assert r.get("status") in ("ok", "insufficient_data")
    assert "proposed_actions" in r


def test_propose_marketing_actions_insufficient_data_when_empty_analysis(monkeypatch):
    monkeypatch.setattr(
        "app.jarvis.marketing_action_proposals.run_analyze_marketing_opportunities",
        lambda days_back, top_n: {
            "status": "insufficient_data",
            "business": "Peluquería Cruz",
            "days_back": days_back,
            "top_n": top_n,
            "available_sources": [],
            "unavailable_sources": [],
            "biggest_opportunities": [],
            "biggest_wastes": [],
            "conversion_gaps": [],
            "missing_data": [],
        },
    )
    out = TOOL_SPECS["propose_marketing_actions"].fn()
    assert out["status"] == "insufficient_data"
    assert out["proposed_actions"] == []


def test_stage_marketing_action_single_valid_index(monkeypatch):
    from app.jarvis import marketing_sources as ms
    from app.jarvis import marketing_opportunity_analysis as moa

    monkeypatch.setattr(
        moa,
        "fetch_google_ads_summary",
        lambda days_back: ms.build_google_ads_waste_sample(days_back=days_back),
    )
    prop = TOOL_SPECS["propose_marketing_actions"].fn(top_n=10)
    pause_idx = next(
        i
        for i, p in enumerate(prop["proposed_actions"])
        if p["action_type"] == "pause_or_reduce_budget"
    )
    out = TOOL_SPECS["stage_marketing_action_for_approval"].fn(action_index=pause_idx, top_n=10)
    assert out["status"] == "ok"
    assert out["selected_count"] == 1
    staged = out["staged_actions"][0]
    assert staged["approval_state"] == "pending"
    assert staged["execution_state"] == "not_executed"

    rec = get_default_approval_storage().get_by_run_id(staged["jarvis_run_id"])
    assert rec is not None
    assert rec["approval_status"] == "pending"
    assert rec["execution_status"] == EXEC_NOT_EXECUTED
    assert rec["tool"] == "execute_marketing_proposal"
    assert rec["args"]["proposal"]["action_type"] == "pause_or_reduce_budget"


def test_stage_marketing_action_multiple_valid_indices(monkeypatch):
    from app.jarvis import marketing_sources as ms
    from app.jarvis import marketing_opportunity_analysis as moa

    monkeypatch.setattr(
        moa,
        "fetch_google_ads_summary",
        lambda days_back: ms.build_google_ads_waste_sample(days_back=days_back),
    )
    monkeypatch.setattr(
        moa,
        "fetch_search_console_summary",
        lambda days_back: ms.build_search_console_opportunity_sample(days_back=days_back),
    )
    out = TOOL_SPECS["stage_marketing_action_for_approval"].fn(action_indices=[0, 1], top_n=10)
    assert out["status"] == "ok"
    assert out["selected_count"] == 2
    assert len(out["staged_actions"]) == 2


def test_stage_marketing_action_duplicate_indices_rejected_safely(monkeypatch):
    monkeypatch.setattr(
        "app.jarvis.marketing_approval_staging.run_propose_marketing_actions",
        lambda days_back, top_n: {
            "status": "ok",
            "business": "Peluquería Cruz",
            "analysis_status": "partial",
            "proposed_actions": [_dummy_proposal("a"), _dummy_proposal("b")],
            "missing_data": [],
            "unavailable_sources": [],
        },
    )
    out = TOOL_SPECS["stage_marketing_action_for_approval"].fn(action_indices=[0, 0])
    assert out["status"] == "invalid_selection"
    assert out["staged_actions"] == []


def test_stage_marketing_action_out_of_range_rejected_safely(monkeypatch):
    monkeypatch.setattr(
        "app.jarvis.marketing_approval_staging.run_propose_marketing_actions",
        lambda days_back, top_n: {
            "status": "ok",
            "business": "Peluquería Cruz",
            "analysis_status": "partial",
            "proposed_actions": [_dummy_proposal("only")],
            "missing_data": [],
            "unavailable_sources": [],
        },
    )
    out = TOOL_SPECS["stage_marketing_action_for_approval"].fn(action_index=3)
    assert out["status"] == "invalid_selection"
    assert out["staged_actions"] == []


def test_stage_marketing_action_empty_selection_rejected_safely():
    r = execute_plan(
        {
            "action": "stage_marketing_action_for_approval",
            "args": {"action_indices": [], "days_back": 28, "top_n": 5},
            "reasoning": "t",
        },
        jarvis_run_id="stage-empty-1",
    )
    assert r["status"] == "invalid_selection"
    assert r["staged_actions"] == []


def test_stage_marketing_action_insufficient_data_stages_nothing(monkeypatch):
    monkeypatch.setattr(
        "app.jarvis.marketing_approval_staging.run_propose_marketing_actions",
        lambda days_back, top_n: {
            "status": "insufficient_data",
            "business": "Peluquería Cruz",
            "analysis_status": "insufficient_data",
            "proposed_actions": [],
            "missing_data": [{"type": "not_configured"}],
            "unavailable_sources": [{"source": "ga4"}],
        },
    )
    out = TOOL_SPECS["stage_marketing_action_for_approval"].fn(action_index=0)
    assert out["status"] == "insufficient_data"
    assert out["selected_count"] == 0
    assert out["staged_actions"] == []


def test_staged_marketing_actions_appear_in_existing_approval_read_tools(monkeypatch):
    from app.jarvis import marketing_sources as ms
    from app.jarvis import marketing_opportunity_analysis as moa

    monkeypatch.setattr(
        moa,
        "fetch_google_ads_summary",
        lambda days_back: ms.build_google_ads_waste_sample(days_back=days_back),
    )
    out = TOOL_SPECS["stage_marketing_action_for_approval"].fn(action_index=0, top_n=10)
    rid = out["staged_actions"][0]["jarvis_run_id"]

    pending = TOOL_SPECS["list_pending_approvals"].fn(limit=20)
    ids = {a["jarvis_run_id"] for a in pending["approvals"]}
    assert rid in ids

    status = TOOL_SPECS["get_approval_status"].fn(jarvis_run_id=rid)
    assert status["found"] is True
    assert status["approval"]["approval_status"] == "pending"
    assert status["approval"]["execution_status"] == "not_executed"

    ready = TOOL_SPECS["list_ready_for_execution"].fn(limit=20)
    assert ready["count"] == 0


def test_execute_plan_stage_marketing_action_no_crash(monkeypatch):
    from app.jarvis import marketing_sources as ms
    from app.jarvis import marketing_opportunity_analysis as moa

    monkeypatch.setattr(
        moa,
        "fetch_google_ads_summary",
        lambda days_back: ms.build_google_ads_waste_sample(days_back=days_back),
    )
    r = execute_plan(
        {
            "action": "stage_marketing_action_for_approval",
            "args": {"action_index": 0, "top_n": 10},
            "reasoning": "t",
        },
        jarvis_run_id="stage-ok-1",
    )
    assert isinstance(r, dict)
    assert "error" not in r
    assert r["status"] == "ok"
    assert r["selected_count"] == 1


def _dummy_proposal(action_type: str) -> dict[str, object]:
    return {
        "action_type": action_type,
        "title": f"title-{action_type}",
        "summary": "summary",
        "source": "google_ads",
        "target": "target",
        "reason": "reason",
        "priority": "medium",
        "suggested_channel": "ops",
        "requires_human_review": True,
        "supporting_metrics": None,
    }


def test_execute_marketing_proposal_unknown_action_type_simulated():
    from app.domains.marketing.execution import safe_execute_marketing_proposal

    out = safe_execute_marketing_proposal(_dummy_proposal("pause_or_reduce_budget"))  # type: ignore[arg-type]
    assert out["status"] == "executed"
    assert out["details"]["mode"] == "simulated"
    assert out["details"]["operation"] == "unsupported_action_type"


def test_marketing_proposal_simulated_types_return_executed():
    from app.domains.marketing.execution import execute_marketing_proposal

    for at in ("send_campaign", "update_budget", "launch_ad"):
        r = execute_marketing_proposal({"action_type": at, "title": "t", "target": "x"})
        assert r["status"] == "executed"
        assert r["action_type"] == at
        assert r["details"]["mode"] == "simulated"


def test_marketing_proposal_execute_after_approval_updates_storage(monkeypatch):
    monkeypatch.setattr(
        "app.jarvis.marketing_approval_staging.run_propose_marketing_actions",
        lambda days_back, top_n: {
            "status": "ok",
            "business": "Peluquería Cruz",
            "analysis_status": "partial",
            "proposed_actions": [
                {
                    "action_type": "send_campaign",
                    "title": "Spring promo",
                    "summary": "s",
                    "source": "test",
                    "target": "camp-1",
                    "reason": "r",
                    "priority": "medium",
                    "suggested_channel": "ops",
                    "requires_human_review": True,
                    "supporting_metrics": None,
                }
            ],
            "missing_data": [],
            "unavailable_sources": [],
        },
    )
    out = TOOL_SPECS["stage_marketing_action_for_approval"].fn(action_index=0, top_n=5)
    rid = out["staged_actions"][0]["jarvis_run_id"]

    ap = TOOL_SPECS["approve_pending_action"].fn(jarvis_run_id=rid, reason="go")
    assert ap["execution_status"] == "ready"

    ex = TOOL_SPECS["execute_ready_action"].fn(jarvis_run_id=rid)
    assert ex["status"] == "ok"
    assert ex["execution_status"] == EXEC_EXECUTED

    rec = get_default_approval_storage().get_by_run_id(rid)
    assert rec is not None
    assert rec["execution_status"] == EXEC_EXECUTED
    assert rec["execution_result"]["status"] == "executed"
    assert rec["execution_result"]["action_type"] == "send_campaign"


def test_marketing_proposal_not_executed_when_still_pending(monkeypatch):
    monkeypatch.setattr(
        "app.jarvis.marketing_approval_staging.run_propose_marketing_actions",
        lambda days_back, top_n: {
            "status": "ok",
            "business": "Peluquería Cruz",
            "analysis_status": "partial",
            "proposed_actions": [_dummy_proposal("launch_ad")],
            "missing_data": [],
            "unavailable_sources": [],
        },
    )
    out = TOOL_SPECS["stage_marketing_action_for_approval"].fn(action_index=0, top_n=5)
    rid = out["staged_actions"][0]["jarvis_run_id"]

    ex = TOOL_SPECS["execute_ready_action"].fn(jarvis_run_id=rid)
    assert ex["status"] == "not_approved"
    assert ex.get("approval_status") == "pending"

    rec = get_default_approval_storage().get_by_run_id(rid)
    assert rec["execution_status"] == EXEC_NOT_EXECUTED


def test_should_auto_execute_rules():
    assert should_auto_execute({"action_type": "pause", "confidence": 0.91}) is True
    assert should_auto_execute({"action_type": "update_budget", "title": "x"}) is True
    assert should_auto_execute({"action_type": "send_campaign", "confidence": 0.5}) is False
    assert should_auto_execute({"action_type": "send_campaign"}) is False
    assert should_auto_execute({}) is False


def test_stage_auto_executes_when_high_confidence(monkeypatch):
    monkeypatch.setattr(
        "app.jarvis.marketing_approval_staging.run_propose_marketing_actions",
        lambda days_back, top_n: {
            "status": "ok",
            "business": "Peluquería Cruz",
            "analysis_status": "partial",
            "proposed_actions": [
                {
                    **dict(_dummy_proposal("launch_ad")),
                    "confidence": 0.95,
                }
            ],
            "missing_data": [],
            "unavailable_sources": [],
        },
    )
    out = TOOL_SPECS["stage_marketing_action_for_approval"].fn(action_index=0, top_n=5)
    assert out["status"] == "ok"
    staged = out["staged_actions"][0]
    assert staged["approval_state"] == "auto_approved"
    assert staged["execution_state"] == "executed"
    assert staged["auto_execution"]["status"] == "ok"
    assert staged["auto_execution"]["auto_executed"] is True

    rid = staged["jarvis_run_id"]
    rec = get_default_approval_storage().get_by_run_id(rid)
    assert rec is not None
    assert rec["approval_status"] == APPROVAL_AUTO_APPROVED
    assert rec["execution_status"] == EXEC_EXECUTED
    assert rec["executed_by"] == "jarvis_auto_execution"


def test_stage_auto_executes_update_budget_without_confidence(monkeypatch):
    monkeypatch.setattr(
        "app.jarvis.marketing_approval_staging.run_propose_marketing_actions",
        lambda days_back, top_n: {
            "status": "ok",
            "business": "Peluquería Cruz",
            "analysis_status": "partial",
            "proposed_actions": [_dummy_proposal("update_budget")],
            "missing_data": [],
            "unavailable_sources": [],
        },
    )
    out = TOOL_SPECS["stage_marketing_action_for_approval"].fn(action_index=0, top_n=5)
    staged = out["staged_actions"][0]
    assert staged["approval_state"] == "auto_approved"
    rec = get_default_approval_storage().get_by_run_id(staged["jarvis_run_id"])
    assert rec["approval_status"] == APPROVAL_AUTO_APPROVED


def test_stage_low_confidence_stays_pending(monkeypatch):
    monkeypatch.setattr(
        "app.jarvis.marketing_approval_staging.run_propose_marketing_actions",
        lambda days_back, top_n: {
            "status": "ok",
            "business": "Peluquería Cruz",
            "analysis_status": "partial",
            "proposed_actions": [
                {
                    **dict(_dummy_proposal("launch_ad")),
                    "confidence": 0.4,
                }
            ],
            "missing_data": [],
            "unavailable_sources": [],
        },
    )
    out = TOOL_SPECS["stage_marketing_action_for_approval"].fn(action_index=0, top_n=5)
    staged = out["staged_actions"][0]
    assert staged["approval_state"] == "pending"
    assert staged["execution_state"] == "not_executed"
    assert staged["auto_execution"]["status"] == "skipped"
    rec = get_default_approval_storage().get_by_run_id(staged["jarvis_run_id"])
    assert rec["approval_status"] == "pending"


def test_stage_unknown_action_type_auto_executes_safely_when_high_confidence(monkeypatch):
    monkeypatch.setattr(
        "app.jarvis.marketing_approval_staging.run_propose_marketing_actions",
        lambda days_back, top_n: {
            "status": "ok",
            "business": "Peluquería Cruz",
            "analysis_status": "partial",
            "proposed_actions": [
                {
                    **dict(_dummy_proposal("totally_unknown_xyz")),
                    "confidence": 0.99,
                }
            ],
            "missing_data": [],
            "unavailable_sources": [],
        },
    )
    out = TOOL_SPECS["stage_marketing_action_for_approval"].fn(action_index=0, top_n=5)
    staged = out["staged_actions"][0]
    assert staged["approval_state"] == "auto_approved"
    rec = get_default_approval_storage().get_by_run_id(staged["jarvis_run_id"])
    assert rec["execution_result"]["status"] == "executed"
    assert rec["execution_result"]["details"]["operation"] == "unsupported_action_type"
