"""Google Ads read-only analytics enrichment for Jarvis missions and Telegram formatting."""

from __future__ import annotations

from typing import Any

from app.jarvis.autonomous_agents import ExecutionAgent, _readonly_analytics_insights
from app.jarvis.autonomous_orchestrator import JarvisAutonomousOrchestrator

GOOGLE_ADS_ANALYTICS_PROMPT = (
    "Analyze my Google Ads account for the last 30 days. Return top 10 campaigns by spend "
    "with impressions, clicks, CTR, conversions, cost, top issues, and top opportunities. Read-only only."
)


def test_readonly_analytics_insights_detects_top_spend_zero_conversions():
    rows = [
        {
            "name": "HighSpend",
            "cost": "50.00",
            "impressions": 5000,
            "clicks": 200,
            "ctr": "4.00%",
            "conversions": 0.0,
        },
        {
            "name": "Other",
            "cost": "5.00",
            "impressions": 900,
            "clicks": 25,
            "ctr": "2.78%",
            "conversions": 2.0,
        },
    ]
    issues, opps, summary = _readonly_analytics_insights(rows)
    assert any("zero conversions" in i.lower() for i in issues)
    assert opps
    assert "55.00" in summary or "55" in summary


def test_format_google_ads_execution_lines_includes_metrics_issues_opportunities():
    orch = JarvisAutonomousOrchestrator()
    result: dict[str, Any] = {
        "auth_ok": True,
        "campaign_fetch_ok": True,
        "campaign_count": 2,
        "campaigns": ["A", "B"],
        "analytics_period": "last_30_days",
        "analytics_top_campaigns": [
            {
                "name": "Alpha",
                "cost": "10.00",
                "impressions": 1000,
                "clicks": 50,
                "ctr": "5.00%",
                "conversions": 2.0,
            }
        ],
        "analytics_issues": ["Issue one"],
        "analytics_opportunities": ["Opportunity one"],
        "analytics_summary": "Combined cost 10.00; conversions 2.0.",
    }
    lines = orch._format_google_ads_execution_lines(result)  # noqa: SLF001
    joined = "\n".join(lines)
    assert "Métricas solo lectura" in joined
    assert "Alpha" in joined and "impr. 1000" in joined
    assert "Problemas destacados:" in joined
    assert "Oportunidades destacadas:" in joined
    assert "Resumen:" in joined


def test_execution_agent_passes_analytics_flag_for_sufficient_google_ads_prompt(monkeypatch):
    captured: dict[str, Any] = {}

    def _capture(params: dict[str, Any]) -> dict[str, Any]:
        captured.clear()
        captured.update(params)
        return {
            "auth_ok": True,
            "campaign_fetch_ok": True,
            "campaign_count": 1,
            "campaigns": ["X"],
            "error_type": None,
            "error_message": None,
        }

    monkeypatch.setattr("app.jarvis.autonomous_agents.run_google_ads_readonly_diagnostic", _capture)
    strategy = {
        "actions": [
            {
                "title": "Google Ads diagnostic",
                "action_type": "diagnose_google_ads_setup",
                "params": {},
                "execution_mode": "auto_execute",
                "priority_score": 90,
            }
        ]
    }
    ExecutionAgent().run(strategy=strategy, mission_prompt=GOOGLE_ADS_ANALYTICS_PROMPT)
    assert captured.get("include_readonly_analytics_last_30d") is True


def test_execution_agent_omits_analytics_flag_for_vague_prompt(monkeypatch):
    captured: dict[str, Any] = {}

    def _capture(params: dict[str, Any]) -> dict[str, Any]:
        captured.clear()
        captured.update(params)
        return {
            "auth_ok": True,
            "campaign_fetch_ok": True,
            "campaign_count": 0,
            "campaigns": [],
            "error_type": None,
            "error_message": None,
        }

    monkeypatch.setattr("app.jarvis.autonomous_agents.run_google_ads_readonly_diagnostic", _capture)
    ExecutionAgent().run(
        strategy={
            "actions": [
                {
                    "title": "Google Ads diagnostic",
                    "action_type": "diagnose_google_ads_setup",
                    "params": {},
                    "execution_mode": "auto_execute",
                    "priority_score": 90,
                }
            ]
        },
        mission_prompt="Google Ads???",
    )
    assert "include_readonly_analytics_last_30d" not in captured


def test_done_dialog_puts_google_ads_metrics_before_sources_for_telegram_priority():
    orch = JarvisAutonomousOrchestrator()
    text = orch._build_done_dialog_message(  # noqa: SLF001
        mission_id="m-priority",
        prompt=GOOGLE_ADS_ANALYTICS_PROMPT,
        plan={"source": "bedrock"},
        research={"source": "bedrock"},
        strategy={
            "source": "bedrock",
            "actions": [{"action_type": "diagnose_google_ads_setup", "title": "Google Ads diagnostic"}],
        },
        ops_output={"diagnostics": []},
        execution={
            "executed": [
                {
                    "action_type": "diagnose_google_ads_setup",
                    "title": "Google Ads diagnostic",
                    "result": {
                        "auth_ok": True,
                        "campaign_fetch_ok": True,
                        "campaign_count": 1,
                        "campaigns": ["Z"],
                        "analytics_period": "last_30_days",
                        "analytics_top_campaigns": [
                            {
                                "name": "Zeta",
                                "cost": "2.00",
                                "impressions": 100,
                                "clicks": 5,
                                "ctr": "5.00%",
                                "conversions": 0.0,
                            }
                        ],
                        "analytics_issues": [],
                        "analytics_opportunities": ["Opp"],
                        "analytics_summary": "S.",
                        "error_type": None,
                        "error_message": None,
                    },
                }
            ]
        },
        review={"summary": "ok"},
    )
    assert text.index("Autenticación con Google Ads") < text.index("Fuentes:")
    assert "Métricas solo lectura" in text
    assert len(text) <= 3900


def test_extract_google_ads_execution_result_prefers_row_with_analytics():
    orch = JarvisAutonomousOrchestrator()
    shallow = {
        "auth_ok": True,
        "campaign_fetch_ok": True,
        "campaign_count": 1,
        "campaigns": ["OnlyName"],
    }
    rich = {
        "auth_ok": True,
        "campaign_fetch_ok": True,
        "campaign_count": 1,
        "campaigns": ["X"],
        "analytics_top_campaigns": [{"name": "Rich", "cost": "1", "impressions": 1, "clicks": 1, "ctr": "1%", "conversions": 0.0}],
        "analytics_summary": "ok",
    }
    execution = {
        "executed": [
            {"action_type": "analysis", "title": "Other", "result": {"note": 1}},
            {"action_type": "diagnose_google_ads_setup", "title": "Ads shallow", "result": shallow},
            {"action_type": "diagnose_google_ads_setup", "title": "Ads deep", "result": rich},
        ]
    }
    picked = orch._extract_google_ads_execution_result(execution)  # noqa: SLF001
    assert picked is not None
    assert picked.get("analytics_top_campaigns")


def test_done_dialog_full_google_ads_analytics_prompt_shows_metrics_block():
    orch = JarvisAutonomousOrchestrator()
    text = orch._build_done_dialog_message(  # noqa: SLF001
        mission_id="m2",
        prompt=GOOGLE_ADS_ANALYTICS_PROMPT,
        plan={"source": "bedrock"},
        research={"source": "bedrock"},
        strategy={
            "source": "bedrock",
            "actions": [{"action_type": "diagnose_google_ads_setup", "title": "Google Ads diagnostic"}],
        },
        ops_output={"diagnostics": []},
        execution={
            "executed": [
                {
                    "action_type": "diagnose_google_ads_setup",
                    "title": "Google Ads diagnostic",
                    "result": {
                        "auth_ok": True,
                        "campaign_fetch_ok": True,
                        "campaign_count": 1,
                        "campaigns": ["Alpha"],
                        "analytics_period": "last_30_days",
                        "analytics_top_campaigns": [
                            {
                                "name": "Alpha",
                                "cost": "1.00",
                                "impressions": 500,
                                "clicks": 20,
                                "ctr": "4.00%",
                                "conversions": 1.0,
                            }
                        ],
                        "analytics_issues": ["Low volume on one geo"],
                        "analytics_opportunities": ["Scale Alpha"],
                        "analytics_summary": "Snapshot ok.",
                        "error_type": None,
                        "error_message": None,
                    },
                }
            ]
        },
        review={"summary": "ok"},
    )
    assert "Métricas solo lectura" in text
    assert "impr. 500" in text
    assert "Problemas destacados:" in text
    assert "Oportunidades destacadas:" in text
    assert "Ref. interna: m2" in text


GA4_MISSION_PROMPT = (
    "Analyze my GA4 property for the last 30 days. Return top 10 pages and events with sessions, users, "
    "traffic and conversions metrics, top issues, and top opportunities. Read-only only."
)


def test_format_ga4_execution_lines_includes_metrics_summary_issues_opportunities():
    orch = JarvisAutonomousOrchestrator()
    result: dict[str, Any] = {
        "env_configured": True,
        "ga4_analytics_fetch_ok": True,
        "analytics_period": "last_30_days",
        "analytics_top_pages": [
            {
                "path": "/book",
                "title": "Book",
                "sessions": 80,
                "users": 60,
                "event_count": 200,
                "engagement_rate": 0.55,
                "conversions": 2.0,
            }
        ],
        "analytics_top_events": [
            {"name": "page_view", "event_count": 500, "users": 70, "conversions": 0.0},
        ],
        "analytics_summary": "Last 30 days snapshot.",
        "analytics_issues": ["Low engagement on /x"],
        "analytics_opportunities": ["Scale /book"],
    }
    lines = orch._format_ga4_execution_lines(result)  # noqa: SLF001
    joined = "\n".join(lines)
    assert "Métricas solo lectura" in joined
    assert "sesiones 80" in joined
    assert "Resumen GA4:" in joined
    assert "Problemas destacados (GA4):" in joined
    assert "Oportunidades destacadas (GA4):" in joined


def test_done_dialog_puts_ga4_analytics_before_sources():
    orch = JarvisAutonomousOrchestrator()
    text = orch._build_done_dialog_message(  # noqa: SLF001
        mission_id="m-ga4",
        prompt=GA4_MISSION_PROMPT,
        plan={"source": "bedrock"},
        research={"source": "bedrock"},
        strategy={
            "source": "bedrock",
            "actions": [{"action_type": "diagnose_ga4_setup", "title": "GA4 diagnostic"}],
        },
        ops_output={"diagnostics": []},
        execution={
            "executed": [
                {
                    "action_type": "diagnose_ga4_setup",
                    "title": "GA4 diagnostic",
                    "result": {
                        "env_configured": True,
                        "missing_env_vars": [],
                        "ga4_analytics_fetch_ok": True,
                        "analytics_period": "last_30_days",
                        "analytics_top_pages": [
                            {
                                "path": "/",
                                "title": "Home",
                                "sessions": 10,
                                "users": 8,
                                "event_count": 40,
                                "engagement_rate": 0.4,
                                "conversions": 0.0,
                            }
                        ],
                        "analytics_top_events": [
                            {"name": "session_start", "event_count": 12, "users": 8, "conversions": 0.0},
                        ],
                        "analytics_summary": "S.",
                        "analytics_issues": ["I1"],
                        "analytics_opportunities": ["O1"],
                    },
                }
            ]
        },
        review={"summary": "ok"},
    )
    assert text.index("Métricas solo lectura") < text.index("Fuentes:")
    assert "Resumen GA4:" in text
    assert len(text) <= 3900
