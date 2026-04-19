"""Planner requires_input relaxation for well-specified read-only analytics prompts."""

from __future__ import annotations

import json

import pytest

from app.jarvis.autonomous_agents import PlannerAgent, _readonly_analytics_prompt_sufficient


GOOGLE_ADS_READONLY_EXAMPLE = (
    "Analyze my Google Ads account for the last 30 days. Return top 10 campaigns by spend "
    "with impressions, clicks, CTR, conversions, cost, top issues, and top opportunities. Read-only only."
)


def test_readonly_analytics_heuristic_matches_google_ads_example():
    assert _readonly_analytics_prompt_sufficient(GOOGLE_ADS_READONLY_EXAMPLE) is True


@pytest.mark.parametrize(
    "vague",
    [
        "Do something about Google Ads.",
        "Analyze my Google Ads account.",
        "Google Ads last 30 days read-only only.",
        "Analyze my Google Ads for the last 30 days with spend and impressions.",
    ],
)
def test_readonly_analytics_heuristic_rejects_vague_prompts(vague: str):
    assert _readonly_analytics_prompt_sufficient(vague) is False


def test_readonly_analytics_heuristic_rejects_when_critical_verbs_present():
    prompt = (
        "Read-only report: last 30 days top 10 campaigns by spend, impressions, clicks, CTR on Google Ads. "
        "Then deploy changes to production."
    )
    assert _readonly_analytics_prompt_sufficient(prompt) is False


def test_planner_clears_requires_input_for_sufficient_google_ads_prompt(monkeypatch):
    monkeypatch.setattr(
        "app.jarvis.autonomous_agents.ask_bedrock",
        lambda _q: json.dumps(
            {
                "objective": "Summarize Google Ads",
                "steps": ["Query metrics", "Rank campaigns"],
                "requires_research": True,
                "requires_input": True,
            }
        ),
    )
    plan = PlannerAgent().run(GOOGLE_ADS_READONLY_EXAMPLE)
    assert plan["source"] == "bedrock"
    assert plan["requires_input"] is False


def test_planner_keeps_requires_input_when_prompt_vague(monkeypatch):
    vague = "Do something about Google Ads."
    monkeypatch.setattr(
        "app.jarvis.autonomous_agents.ask_bedrock",
        lambda _q: json.dumps(
            {
                "objective": "Clarify scope",
                "steps": ["Ask user"],
                "requires_research": False,
                "requires_input": True,
            }
        ),
    )
    plan = PlannerAgent().run(vague)
    assert plan["requires_input"] is True
