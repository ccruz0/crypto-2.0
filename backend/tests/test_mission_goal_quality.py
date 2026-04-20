"""Tests for goal satisfaction, natural clarification, and retry helpers."""

from __future__ import annotations

import pytest

from app.jarvis.analytics_mission_deliverables import (
    deliverables_to_dict,
    infer_analytics_deliverables,
)
from app.jarvis.analytics_prompt_gates import readonly_analytics_prompt_sufficient
from app.jarvis.mission_goal_quality import (
    build_corrective_google_ads_diagnose_action,
    build_corrective_readonly_analytics_action,
    evaluate_goal_satisfaction,
    format_goal_shortfall_user_message,
    format_natural_clarification_request,
    should_attempt_goal_retry,
)

GOOGLE_ADS_FULL = (
    "Analyze my Google Ads account for the last 30 days. Return top 10 campaigns by spend "
    "with impressions, clicks, CTR, conversions, cost, top issues, and top opportunities. Read-only only."
)

GA4_ANALYTICS_FULL = (
    "Analyze my GA4 property for the last 30 days. Return top 10 pages and events with sessions, users, "
    "traffic and conversions metrics, top issues, and top opportunities. Read-only only."
)

GSC_ANALYTICS_FULL = (
    "Review Google Search Console for the last 28 days. Return top 15 queries and landing pages with "
    "clicks, impressions, CTR, and average position metrics, top issues, and opportunities. Read-only only."
)

GOOGLE_ADS_ES_REVIEW_PAUSE_HINT = (
    "Revisa mis campañas de Google Ads y dime si hay alguna que debería pausar. Solo lectura."
)


def test_spanish_google_ads_review_readonly_passes_strict_gate():
    assert readonly_analytics_prompt_sufficient(GOOGLE_ADS_ES_REVIEW_PAUSE_HINT) is True


def test_spanish_google_ads_infer_default_timeframe_and_top_rank():
    spec = infer_analytics_deliverables(GOOGLE_ADS_ES_REVIEW_PAUSE_HINT)
    assert spec is not None
    assert spec.domain == "google_ads"
    assert spec.inferred_timeframe is True
    assert spec.inferred_top_rank is True
    assert spec.timeframe_label == "last 30 days"
    assert spec.top_rank == 10
    d = deliverables_to_dict(spec)
    assert d["inferred_timeframe"] is True
    assert d["inferred_top_rank"] is True


def test_spanish_google_ads_explicit_window_skips_time_inference():
    p = (
        "Revisa mis campañas de Google Ads de los últimos 14 días y dime si hay alguna que debería pausar. "
        "Solo lectura."
    )
    assert readonly_analytics_prompt_sufficient(p) is True
    spec = infer_analytics_deliverables(p)
    assert spec is not None
    assert spec.inferred_timeframe is False
    assert "14" in spec.timeframe_label
    assert spec.inferred_top_rank is True
    assert spec.top_rank == 10


def test_vague_long_google_ads_readonly_without_review_still_rejected():
    p = (
        "Haz algo con Google Ads en solo lectura por favor extiende el texto lo suficiente como para "
        "cumplir el mínimo de longitud que exige el sistema y no agregamos verbo de revisión explícita."
    )
    assert readonly_analytics_prompt_sufficient(p) is False


def test_mutating_google_ads_pause_intent_without_readonly_still_rejected():
    p = (
        "Pausa todas las campañas de Google Ads de inmediato sin revisar métricas y avisa cuando haya "
        "terminado el trabajo en bloques de varias palabras para cumplir longitud mínima del prompt aquí."
    )
    assert readonly_analytics_prompt_sufficient(p) is False


def test_goal_eval_deliverables_include_inferred_default_flags_for_spanish_prompt():
    execution = {
        "executed": [
            {
                "action_type": "diagnose_google_ads_setup",
                "result": {
                    "auth_ok": True,
                    "campaign_fetch_ok": True,
                    "analytics_top_campaigns": [
                        {
                            "name": "A",
                            "cost": "1",
                            "impressions": 1,
                            "clicks": 1,
                            "ctr": "1%",
                            "conversions": 0.0,
                        }
                    ],
                    "analytics_summary": "ok",
                    "analytics_issues": ["i"],
                    "analytics_opportunities": ["o"],
                },
            }
        ]
    }
    g = evaluate_goal_satisfaction(mission_prompt=GOOGLE_ADS_ES_REVIEW_PAUSE_HINT, execution=execution)
    assert g["satisfied"] is True
    deliv = g.get("deliverables") or {}
    assert deliv.get("inferred_timeframe") is True
    assert deliv.get("inferred_top_rank") is True


def test_well_specified_english_google_ads_deliverables_do_not_mark_inferred_defaults():
    spec = infer_analytics_deliverables(GOOGLE_ADS_FULL)
    assert spec is not None
    assert spec.inferred_timeframe is False
    assert spec.inferred_top_rank is False


def test_well_specified_google_ads_prompt_passes_goal_when_metrics_present():
    execution = {
        "executed": [
            {
                "action_type": "diagnose_google_ads_setup",
                "result": {
                    "auth_ok": True,
                    "campaign_fetch_ok": True,
                    "analytics_top_campaigns": [
                        {
                            "name": "A",
                            "cost": "1",
                            "impressions": 1,
                            "clicks": 1,
                            "ctr": "1%",
                            "conversions": 0.0,
                        }
                    ],
                    "analytics_summary": "ok",
                    "analytics_issues": ["i"],
                    "analytics_opportunities": ["o"],
                },
            }
        ]
    }
    g = evaluate_goal_satisfaction(mission_prompt=GOOGLE_ADS_FULL, execution=execution)
    assert g["satisfied"] is True
    assert g["missing_items"] == []
    assert g.get("reason") == "read_only_google_ads_rubric"
    assert g.get("evaluator_domain") == "google_ads"


def test_shallow_google_ads_result_fails_goal_satisfaction():
    execution = {
        "executed": [
            {
                "action_type": "diagnose_google_ads_setup",
                "result": {
                    "auth_ok": True,
                    "campaign_fetch_ok": True,
                    "campaigns": ["Only"],
                    "analytics_top_campaigns": [],
                    "analytics_summary": "",
                    "analytics_issues": [],
                    "analytics_opportunities": [],
                },
            }
        ]
    }
    g = evaluate_goal_satisfaction(mission_prompt=GOOGLE_ADS_FULL, execution=execution)
    assert g["satisfied"] is False
    assert "google_ads_performance_metrics" in g["missing_items"]
    assert g.get("auto_retry_recommended") is True
    assert g.get("evaluator_domain") == "google_ads"


def test_retry_allowed_once_for_shallow_google_ads():
    g = {"satisfied": False, "auto_retry_recommended": True, "missing_items": ["google_ads_performance_metrics"]}
    assert should_attempt_goal_retry(mission_prompt=GOOGLE_ADS_FULL, goal_eval=g, retry_used=False) is True
    assert should_attempt_goal_retry(mission_prompt=GOOGLE_ADS_FULL, goal_eval=g, retry_used=True) is False


def test_under_specified_prompt_uses_fallback_clarification_when_bedrock_unavailable(monkeypatch):
    monkeypatch.setattr("app.jarvis.bedrock_client.ask_bedrock", lambda _q: (_ for _ in ()).throw(RuntimeError("x")))
    q = format_natural_clarification_request(mission_prompt="Do something vague.", plan={"objective": "x"})
    assert "?" in q
    assert "Provide missing constraints" not in q


def test_natural_clarification_uses_model_question_when_spanish(monkeypatch):
    monkeypatch.setattr("app.jarvis.bedrock_client.ask_bedrock", lambda _q: "{}")
    monkeypatch.setattr(
        "app.jarvis.bedrock_client.extract_planner_json_object",
        lambda _raw: {"question": "¿Debo incluir también las campañas pausadas?"},
    )
    q = format_natural_clarification_request(mission_prompt="Analyze ads", plan={"objective": "o"})
    assert "pausadas" in q.lower() or "campañas" in q.lower()


def test_natural_clarification_english_model_uses_spanish_fallback(monkeypatch):
    monkeypatch.setattr("app.jarvis.bedrock_client.ask_bedrock", lambda _q: "{}")
    monkeypatch.setattr(
        "app.jarvis.bedrock_client.extract_planner_json_object",
        lambda _raw: {"question": "What time range should I use for this analysis?"},
    )
    q = format_natural_clarification_request(mission_prompt="Analyze ads", plan={"objective": "o"})
    assert "Puedo hacerlo" in q
    assert "alcance" in q.lower()


def test_clarification_question_looks_spanish_heuristic():
    from app.jarvis.mission_goal_quality import clarification_question_looks_spanish

    assert clarification_question_looks_spanish("¿Qué período quieres usar?") is True
    assert clarification_question_looks_spanish("Qué cuenta debo usar para el informe?") is True
    assert clarification_question_looks_spanish("What scope should I use?") is False
    assert clarification_question_looks_spanish("Should I include brand campaigns?") is False


def test_corrective_action_is_diagnose_auto_execute():
    row = build_corrective_google_ads_diagnose_action()
    assert row["action_type"] == "diagnose_google_ads_setup"
    assert row["execution_mode"] == "auto_execute"


def test_corrective_readonly_analytics_action_ga4_and_gsc():
    ga = build_corrective_readonly_analytics_action("ga4")
    assert ga["action_type"] == "diagnose_ga4_setup"
    assert ga["execution_mode"] == "auto_execute"
    assert ga.get("params", {}).get("container_name") == "backend-aws"
    gsc = build_corrective_readonly_analytics_action("gsc")
    assert gsc["action_type"] == "diagnose_gsc_setup"
    assert gsc["execution_mode"] == "auto_execute"


def test_ga4_style_prompt_uses_generalized_rubric_not_google_ads():
    g = evaluate_goal_satisfaction(
        mission_prompt=GA4_ANALYTICS_FULL,
        execution={"executed": []},
    )
    assert g.get("reason") == "read_only_ga4_rubric"
    assert g.get("evaluator_domain") == "ga4"
    assert "google_ads" not in str(g.get("missing_items", [])).lower()
    assert "ga4_diagnostic_execution" in g["missing_items"]


def test_gsc_style_prompt_uses_generalized_rubric():
    g = evaluate_goal_satisfaction(
        mission_prompt=GSC_ANALYTICS_FULL,
        execution={"executed": []},
    )
    assert g.get("reason") == "read_only_gsc_rubric"
    assert g.get("evaluator_domain") == "gsc"
    assert "gsc_diagnostic_execution" in g["missing_items"]


def test_vague_ga4_prompt_skips_strict_rubric():
    vague = "Tell me about GA4 read-only."
    assert readonly_analytics_prompt_sufficient(vague) is False
    g = evaluate_goal_satisfaction(
        mission_prompt=vague,
        execution={"executed": [{"action_type": "diagnose_ga4_setup", "result": {}}]},
    )
    assert g["reason"] == "no_strict_rubric"
    assert g["satisfied"] is True


def test_ga4_stub_rich_execution_passes_goal():
    execution = {
        "executed": [
            {
                "action_type": "diagnose_ga4_setup",
                "result": {
                    "missing_env_vars": [],
                    "env_configured": True,
                    "ga4_analytics_fetch_ok": True,
                    "analytics_top_pages": [{"path": "/", "views": 100}],
                    "analytics_summary": "ok",
                    "analytics_issues": ["slow LCP"],
                    "analytics_opportunities": ["expand top page"],
                },
            }
        ]
    }
    g = evaluate_goal_satisfaction(mission_prompt=GA4_ANALYTICS_FULL, execution=execution)
    assert g["satisfied"] is True
    assert g.get("reason") == "read_only_ga4_rubric"


def test_ga4_shallow_empty_metrics_recommends_retry():
    execution = {
        "executed": [
            {
                "action_type": "diagnose_ga4_setup",
                "result": {
                    "missing_env_vars": [],
                    "env_configured": True,
                    "ga4_analytics_fetch_ok": True,
                    "analytics_top_pages": [],
                    "analytics_top_events": [],
                },
            }
        ]
    }
    g = evaluate_goal_satisfaction(mission_prompt=GA4_ANALYTICS_FULL, execution=execution)
    assert g["satisfied"] is False
    assert "ga4_performance_metrics" in g["missing_items"]
    assert g.get("auto_retry_recommended") is True


def test_ga4_permission_error_maps_to_authentication_no_retry():
    execution = {
        "executed": [
            {
                "action_type": "diagnose_ga4_setup",
                "result": {
                    "missing_env_vars": [],
                    "env_configured": True,
                    "ga4_analytics_fetch_ok": False,
                    "analytics_query_error": "403 Permission denied for caller",
                },
            }
        ]
    }
    g = evaluate_goal_satisfaction(mission_prompt=GA4_ANALYTICS_FULL, execution=execution)
    assert g["satisfied"] is False
    assert "ga4_authentication" in g["missing_items"]
    assert g.get("auto_retry_recommended") is False


def test_ga4_setup_only_fails_with_unavailable_missing_item():
    execution = {
        "executed": [
            {
                "action_type": "diagnose_ga4_setup",
                "result": {
                    "missing_env_vars": [],
                    "env_configured": True,
                },
            }
        ]
    }
    g = evaluate_goal_satisfaction(mission_prompt=GA4_ANALYTICS_FULL, execution=execution)
    assert g["satisfied"] is False
    assert "ga4_readonly_analytics_unavailable" in g["missing_items"]


def test_gsc_stub_rich_execution_passes_goal():
    execution = {
        "executed": [
            {
                "action_type": "diagnose_gsc_setup",
                "result": {
                    "missing_env_vars": [],
                    "env_configured": True,
                    "analytics_top_queries": [{"query": "hair salon", "clicks": 5}],
                    "analytics_summary": "ok",
                    "analytics_issues": ["low CTR on branded"],
                    "analytics_opportunities": ["improve snippets"],
                },
            }
        ]
    }
    g = evaluate_goal_satisfaction(mission_prompt=GSC_ANALYTICS_FULL, execution=execution)
    assert g["satisfied"] is True


def test_goal_retry_respects_readonly_gate_for_ga4_eval():
    g_eval = {
        "satisfied": False,
        "auto_retry_recommended": True,
        "missing_items": ["ga4_diagnostic_execution"],
        "evaluator_domain": "ga4",
    }
    vague = "GA4?"
    assert should_attempt_goal_retry(mission_prompt=vague, goal_eval=g_eval, retry_used=False) is False
    assert should_attempt_goal_retry(mission_prompt=GA4_ANALYTICS_FULL, goal_eval=g_eval, retry_used=False) is True


def test_execution_agent_merges_ga4_analytics_when_readonly_prompt_sufficient(monkeypatch):
    from app.jarvis.autonomous_agents import ExecutionAgent

    def _fake_inspect(_container: str, env_prefixes=None):
        return {
            "success": True,
            "env": {
                "JARVIS_GA4_PROPERTY_ID": "123456789",
                "JARVIS_GA4_CREDENTIALS_JSON": "/secrets/ga4.json",
            },
            "count": 2,
        }

    def _fake_analytics(params: dict):
        assert int(params.get("limit") or 0) == 10
        return {
            "analytics_period": "last_30_days",
            "ga4_analytics_fetch_ok": True,
            "analytics_top_pages": [
                {
                    "path": "/",
                    "title": "Home",
                    "sessions": 50,
                    "users": 40,
                    "event_count": 120,
                    "engagement_rate": 0.42,
                    "conversions": 1.0,
                }
            ],
            "analytics_top_events": [
                {"name": "page_view", "event_count": 200, "users": 45, "conversions": 0.0},
            ],
            "analytics_summary": "Combined snapshot ok.",
            "analytics_issues": ["Issue a"],
            "analytics_opportunities": ["Opp a"],
            "analytics_query_error": None,
        }

    monkeypatch.setattr("app.jarvis.ops_tools.inspect_container_env", _fake_inspect)
    monkeypatch.setattr("app.jarvis.autonomous_agents.run_ga4_readonly_analytics", _fake_analytics)
    out = ExecutionAgent().run(
        strategy={
            "actions": [
                {
                    "title": "GA4 probe",
                    "action_type": "diagnose_ga4_setup",
                    "params": {"container_name": "backend-aws"},
                    "execution_mode": "auto_execute",
                    "priority_score": 90,
                }
            ]
        },
        mission_prompt=GA4_ANALYTICS_FULL,
    )
    row = out["executed"][0]
    res = row["result"]
    assert res.get("ga4_analytics_fetch_ok") is True
    assert len(res.get("analytics_top_pages") or []) == 1
    assert len(res.get("analytics_top_events") or []) == 1
    g = evaluate_goal_satisfaction(mission_prompt=GA4_ANALYTICS_FULL, execution=out)
    assert g["satisfied"] is True


def test_execution_agent_runs_ga4_setup_diagnostic(monkeypatch):
    from app.jarvis.autonomous_agents import ExecutionAgent

    def _fake_inspect(_container: str, env_prefixes=None):
        return {
            "success": True,
            "env": {
                "JARVIS_GA4_PROPERTY_ID": "123",
                "JARVIS_GA4_CREDENTIALS_JSON": "/secrets/ga4.json",
            },
            "count": 2,
        }

    monkeypatch.setattr("app.jarvis.ops_tools.inspect_container_env", _fake_inspect)
    out = ExecutionAgent().run(
        strategy={
            "actions": [
                {
                    "title": "GA4 probe",
                    "action_type": "diagnose_ga4_setup",
                    "params": {"container_name": "backend-aws"},
                    "execution_mode": "auto_execute",
                    "priority_score": 90,
                }
            ]
        },
        mission_prompt="noop",
    )
    row = out["executed"][0]
    assert row["action_type"] == "diagnose_ga4_setup"
    assert row["result"]["env_configured"] is True
    assert row["result"]["missing_env_vars"] == []


def test_goal_shortfall_message_lists_missing():
    g = {"missing_items": ["google_ads_performance_metrics", "google_ads_summary"]}
    msg = format_goal_shortfall_user_message(g)
    assert "métricas" in msg.lower() or "resumen" in msg.lower()


def test_goal_shortfall_ga4_unavailable_copy():
    msg = format_goal_shortfall_user_message({"missing_items": ["ga4_readonly_analytics_unavailable"]})
    assert "ga4" in msg.lower() or "analytics" in msg.lower()


def test_non_google_ads_mission_skips_strict_rubric():
    g = evaluate_goal_satisfaction(
        mission_prompt="Deploy the backend to production safely.",
        execution={"executed": [{"action_type": "analysis", "result": {}}]},
    )
    assert g["satisfied"] is True
