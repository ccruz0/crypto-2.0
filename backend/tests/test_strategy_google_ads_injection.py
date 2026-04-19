"""Strategy injects concrete Google Ads diagnostic when the model returns only generic actions."""

from __future__ import annotations

import json
from typing import Any

from app.jarvis.autonomous_agents import ExecutionAgent, StrategyAgent

GOOGLE_ADS_ANALYTICS_PROMPT = (
    "Analyze my Google Ads account for the last 30 days. Return top 10 campaigns by spend "
    "with impressions, clicks, CTR, conversions, cost, top issues, and top opportunities. Read-only only."
)


def test_strategy_injects_diagnose_when_bedrock_returns_only_generic_actions(monkeypatch):
    payload = {
        "actions": [
            {
                "title": "Query Top 10 Campaigns by Spend",
                "rationale": "Need spend ranking",
                "action_type": "research",
                "params": {},
                "impact": "medium",
                "confidence": 0.75,
                "requires_approval": False,
            },
            {
                "title": "Analyze Campaign Performance Trends",
                "rationale": "Understand trends",
                "action_type": "analysis",
                "params": {},
                "impact": "low",
                "confidence": 0.6,
                "requires_approval": False,
            },
        ]
    }

    monkeypatch.setattr("app.jarvis.autonomous_agents.ask_bedrock", lambda _q: json.dumps(payload))
    out = StrategyAgent().run(
        prompt=GOOGLE_ADS_ANALYTICS_PROMPT,
        plan={"objective": "o", "steps": [], "requires_research": True, "requires_input": False},
        research={"findings": [], "open_questions": [], "confidence": 0.8},
    )
    types = [str(a.get("action_type") or "") for a in out.get("actions") or []]
    assert types.count("diagnose_google_ads_setup") == 1
    assert any(t == "diagnose_google_ads_setup" for t in types)


def test_strategy_skips_inject_when_diagnose_already_in_strategy(monkeypatch):
    payload = {
        "actions": [
            {
                "title": "Google Ads diagnostic",
                "rationale": "Check API",
                "action_type": "diagnose_google_ads_setup",
                "params": {},
                "impact": "high",
                "confidence": 0.9,
                "requires_approval": False,
            },
            {
                "title": "Query Top 10 Campaigns by Spend",
                "rationale": "x",
                "action_type": "research",
                "params": {},
                "impact": "medium",
                "confidence": 0.7,
                "requires_approval": False,
            },
        ]
    }
    monkeypatch.setattr("app.jarvis.autonomous_agents.ask_bedrock", lambda _q: json.dumps(payload))
    out = StrategyAgent().run(
        prompt=GOOGLE_ADS_ANALYTICS_PROMPT,
        plan={"objective": "o", "steps": [], "requires_research": True, "requires_input": False},
        research={"findings": [], "open_questions": [], "confidence": 0.8},
    )
    assert sum(1 for a in out["actions"] if a.get("action_type") == "diagnose_google_ads_setup") == 1


def test_strategy_does_not_inject_for_ga4_only_well_specified_prompt(monkeypatch):
    ga4_prompt = (
        "Analyze my GA4 property for the last 30 days. Return top 10 events by volume "
        "with sessions, users, engagement, conversions, cost, top issues, and top opportunities. Read-only only."
    )
    payload = {
        "actions": [
            {
                "title": "Explore GA4 events",
                "rationale": "r",
                "action_type": "research",
                "params": {},
                "impact": "medium",
                "confidence": 0.7,
                "requires_approval": False,
            }
        ]
    }
    monkeypatch.setattr("app.jarvis.autonomous_agents.ask_bedrock", lambda _q: json.dumps(payload))
    out = StrategyAgent().run(
        prompt=ga4_prompt,
        plan={"objective": "o", "steps": [], "requires_research": True, "requires_input": False},
        research={"findings": [], "open_questions": [], "confidence": 0.8},
    )
    assert all(a.get("action_type") != "diagnose_google_ads_setup" for a in out["actions"])


def test_execution_returns_structured_google_ads_result_after_strategy_injection(monkeypatch):
    captured: dict[str, Any] = {}

    def _fake_diag(params: dict[str, Any]) -> dict[str, Any]:
        captured.update(params)
        return {
            "auth_ok": True,
            "campaign_fetch_ok": True,
            "campaign_count": 2,
            "campaigns": ["A", "B"],
            "analytics_period": "last_30_days",
            "analytics_top_campaigns": [
                {
                    "name": "A",
                    "cost": "1.00",
                    "impressions": 100,
                    "clicks": 10,
                    "ctr": "10.00%",
                    "conversions": 1.0,
                }
            ],
            "analytics_issues": ["i1"],
            "analytics_opportunities": ["o1"],
            "analytics_summary": "sum",
            "error_type": None,
            "error_message": None,
        }

    monkeypatch.setattr("app.jarvis.autonomous_agents.ask_bedrock", lambda _q: json.dumps({"actions": []}))
    monkeypatch.setattr("app.jarvis.autonomous_agents.run_google_ads_readonly_diagnostic", _fake_diag)
    strategy = StrategyAgent().run(
        prompt=GOOGLE_ADS_ANALYTICS_PROMPT,
        plan={"objective": "o", "steps": [], "requires_research": True, "requires_input": False},
        research={"findings": [], "open_questions": [], "confidence": 0.8},
    )
    ex = ExecutionAgent().run(strategy=strategy, mission_prompt=GOOGLE_ADS_ANALYTICS_PROMPT)
    rows = [r for r in ex["executed"] if r.get("action_type") == "diagnose_google_ads_setup"]
    assert len(rows) == 1
    res = rows[0].get("result")
    assert isinstance(res, dict)
    assert res.get("auth_ok") is True
    assert res.get("analytics_top_campaigns")
    assert res.get("analytics_issues") == ["i1"]
    assert captured.get("include_readonly_analytics_last_30d") is True


def test_telegram_done_message_contains_metrics_after_injected_path(monkeypatch):
    from app.jarvis.autonomous_orchestrator import JarvisAutonomousOrchestrator

    monkeypatch.setattr("app.jarvis.autonomous_agents.ask_bedrock", lambda _q: json.dumps({"actions": []}))
    strategy = StrategyAgent().run(
        prompt=GOOGLE_ADS_ANALYTICS_PROMPT,
        plan={"objective": "o", "steps": [], "requires_research": True, "requires_input": False},
        research={"findings": [], "open_questions": [], "confidence": 0.8},
    )
    monkeypatch.setattr(
        "app.jarvis.autonomous_agents.run_google_ads_readonly_diagnostic",
        lambda _p: {
            "auth_ok": True,
            "campaign_fetch_ok": True,
            "campaign_count": 1,
            "campaigns": ["X"],
            "analytics_period": "last_30_days",
            "analytics_top_campaigns": [
                {
                    "name": "X",
                    "cost": "3.00",
                    "impressions": 50,
                    "clicks": 2,
                    "ctr": "4.00%",
                    "conversions": 0.0,
                }
            ],
            "analytics_issues": ["Low conv"],
            "analytics_opportunities": ["Scale X"],
            "analytics_summary": "ok",
            "error_type": None,
            "error_message": None,
        },
    )
    ex = ExecutionAgent().run(strategy=strategy, mission_prompt=GOOGLE_ADS_ANALYTICS_PROMPT)
    orch = JarvisAutonomousOrchestrator()
    text = orch._build_done_dialog_message(  # noqa: SLF001
        mission_id="m-inj",
        prompt=GOOGLE_ADS_ANALYTICS_PROMPT,
        plan={"source": "bedrock"},
        research={"source": "bedrock"},
        strategy=strategy,
        ops_output={"diagnostics": []},
        execution=ex,
        review={"summary": "ok"},
    )
    assert "Métricas solo lectura" in text
    assert "impr. 50" in text
    assert "Problemas destacados:" in text
    assert "Oportunidades destacadas:" in text
