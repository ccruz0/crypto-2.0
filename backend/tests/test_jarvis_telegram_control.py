"""Tests for Jarvis Telegram formatting (compact replies)."""

from __future__ import annotations

from app.jarvis import telegram_control as tc


def test_format_analyze_marketing_opportunities_sections():
    payload = {
        "jarvis_run_id": "r1",
        "plan": {"action": "analyze_marketing_opportunities", "args": {}, "reasoning": "t"},
        "result": {
            "status": "ok",
            "biggest_opportunities": [
                {
                    "title": "Low CTR query",
                    "summary": "Fix snippet.",
                    "priority": "high",
                },
                {
                    "title": "Page CTR",
                    "summary": "Tune meta.",
                    "priority": "medium",
                },
            ],
            "biggest_wastes": [
                {
                    "campaign": "Brand Ads",
                    "summary": "Spend with no conversions.",
                    "title": "Spend without conversions: Brand Ads",
                }
            ],
            "conversion_gaps": [],
            "missing_data": [
                {"title": "GA4 booking event not mapped", "source": "ga4"},
            ],
        },
    }
    out = tc.format_compact_jarvis_reply("jarvis", payload)
    assert "🧠 Marketing Analysis" in out
    assert "[HIGH]" in out
    assert "Low CTR query" in out
    assert "Fix snippet." in out
    assert "Wasted Spend:" in out
    assert "Brand Ads" in out
    assert "Missing Data:" in out
    assert "{" not in out
    assert len(out) <= 4000


def test_format_propose_marketing_actions_sorted_and_why():
    payload = {
        "jarvis_run_id": "",
        "plan": {"action": "propose_marketing_actions", "args": {}, "reasoning": "t"},
        "result": {
            "status": "ok",
            "proposed_actions": [
                {
                    "title": "Later item",
                    "target": "x",
                    "reason": "because low",
                    "priority": "low",
                },
                {
                    "title": "First item",
                    "target": "/page",
                    "reason": "because high",
                    "priority": "high",
                },
            ],
        },
    }
    out = tc.format_compact_jarvis_reply("jarvis", payload)
    assert "🚀 Recommended Actions" in out
    assert out.index("First item") < out.index("Later item")
    assert "Why: because high" in out
    assert "Target: /page" in out
    assert "{" not in out


def test_analyze_insufficient_data_fallback():
    payload = {
        "jarvis_run_id": "",
        "plan": {"action": "analyze_marketing_opportunities", "args": {}, "reasoning": "t"},
        "result": {
            "status": "insufficient_data",
            "biggest_opportunities": [],
            "biggest_wastes": [],
            "conversion_gaps": [],
            "missing_data": [],
        },
    }
    out = tc.format_compact_jarvis_reply("jarvis", payload)
    assert "Not enough data" in out
    assert "Google Analytics" in out


def test_format_run_marketing_review_telegram():
    payload = {
        "jarvis_run_id": "",
        "plan": {"action": "run_marketing_review", "args": {}, "reasoning": "t"},
        "result": {
            "status": "ok",
            "analysis_status": "ok",
            "proposal_status": "ok",
            "summary": "Marketing review completed. 2 top finding(s) highlighted, 2 action(s) proposed.",
            "top_findings": [
                {"title": "Finding A", "priority": "high"},
            ],
            "proposed_actions": [
                {"title": "Act 1", "priority": "high", "reason": "because"},
            ],
            "staged_actions": [{"title": "Staged X"}],
            "missing_data": [],
            "staged_for_approval": True,
        },
    }
    out = tc.format_compact_jarvis_reply("jarvis", payload)
    assert "🧠 Marketing Review" in out
    assert "Summary:" in out
    assert "Top Findings:" in out
    assert "Proposed Actions:" in out
    assert "[HIGH]" in out
    assert "Staged:" in out
    assert "Staged X" in out
    assert "Why:" not in out
    assert out.count("Act 1") == 1
    assert "{" not in out


def test_format_run_marketing_review_limited_data_missing_sources():
    payload = {
        "jarvis_run_id": "",
        "plan": {"action": "run_marketing_review", "args": {}, "reasoning": "t"},
        "result": {
            "status": "insufficient_data",
            "analysis_status": "insufficient_data",
            "proposal_status": "insufficient_data",
            "summary": "",
            "top_findings": [],
            "proposed_actions": [],
            "staged_actions": [],
            "missing_data": [{"title": "GA4 booking event not configured", "source": "ga4"}],
            "unavailable_sources": ["google_ads", "google_search_console"],
        },
    }
    out = tc.format_compact_jarvis_reply("jarvis", payload)
    assert "🧠 Marketing Review" in out
    assert "Marketing review completed with limited data." in out
    assert "Missing Data:" in out
    assert "Google Ads" in out
    assert "Search Console" in out
    assert "{" not in out


def test_format_run_marketing_review_executor_error():
    payload = {
        "jarvis_run_id": "rid-1",
        "plan": {"action": "run_marketing_review", "args": {}, "reasoning": "t"},
        "result": {"error": "tool_failed", "action": "run_marketing_review", "detail": "boom"},
    }
    out = tc.format_compact_jarvis_reply("jarvis", payload)
    assert "⚠️ Marketing review failed" in out
    assert "tool_failed" in out
    assert "boom" in out
    assert "{" not in out


def test_format_run_marketing_review_shape_fallback_without_plan_action():
    """Runtime payload still formats if plan.action were wrong but result shape matches."""
    payload = {
        "jarvis_run_id": "",
        "plan": {"action": "echo_message", "args": {"message": "x"}, "reasoning": "t"},
        "result": {
            "status": "ok",
            "analysis_status": "ok",
            "proposal_status": "ok",
            "summary": "Pipeline summary.",
            "top_findings": [{"title": "F", "priority": "medium"}],
            "proposed_actions": [{"title": "P", "priority": "low"}],
            "missing_data": [],
        },
    }
    out = tc.format_compact_jarvis_reply("jarvis", payload)
    assert "🧠 Marketing Review" in out
    assert "Pipeline summary." in out
    assert "Available tools" not in out
    assert "```" not in out


def test_analyze_tool_unavailable_short_message():
    payload = {
        "jarvis_run_id": "",
        "plan": {"action": "analyze_marketing_opportunities", "args": {}, "reasoning": "t"},
        "result": {
            "status": "unavailable",
            "message": "Analysis failed.",
        },
    }
    out = tc.format_compact_jarvis_reply("jarvis", payload)
    assert "Analysis failed" in out
    assert "{" not in out
