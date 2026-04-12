"""Tests for run_marketing_review orchestration tool."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.jarvis.marketing_tools import run_marketing_review


def _sample_analysis() -> dict:
    return {
        "status": "ok",
        "business": "TestBiz",
        "available_sources": ["google_search_console", "ga4", "google_ads", "ga4_top_pages"],
        "biggest_opportunities": [
            {
                "title": "Opp A",
                "summary": "s",
                "priority": "high",
            }
        ],
        "biggest_wastes": [],
        "conversion_gaps": [],
        "missing_data": [],
        "unavailable_sources": [],
    }


def _sample_proposal_result(analysis: dict) -> dict:
    from app.jarvis.marketing_action_proposals import build_proposals_from_analysis

    return build_proposals_from_analysis(analysis, days_back=28, top_n=5)


def test_run_marketing_review_orchestrates_analysis_and_proposals():
    analysis = _sample_analysis()
    proposal = _sample_proposal_result(analysis)

    with patch(
        "app.jarvis.marketing_tools.run_analyze_marketing_opportunities",
        return_value=analysis,
    ):
        with patch(
            "app.jarvis.marketing_tools.build_proposals_from_analysis",
            return_value=proposal,
        ):
            out = run_marketing_review(
                days_back=28,
                top_n=5,
                stage_for_approval=False,
            )
    assert out["business"] == "TestBiz"
    assert out["proposal_status"] == proposal["status"]
    assert out["analysis_status"] == proposal["analysis_status"]
    assert len(out["top_findings"]) >= 1
    assert len(out["proposed_actions"]) >= 1
    assert out["staged_for_approval"] is False
    assert out["selected_action_count"] == 0
    assert out["staged_actions"] == []
    assert "Marketing review" in out["summary"]


def test_stage_false_stages_nothing():
    analysis = _sample_analysis()
    proposal = _sample_proposal_result(analysis)

    with patch(
        "app.jarvis.marketing_tools.run_analyze_marketing_opportunities",
        return_value=analysis,
    ):
        with patch(
            "app.jarvis.marketing_tools.build_proposals_from_analysis",
            return_value=proposal,
        ):
            with patch(
                "app.jarvis.marketing_tools.run_stage_marketing_action_for_approval_with_proposal_result",
            ) as st:
                out = run_marketing_review(stage_for_approval=False)
    st.assert_not_called()
    assert out["selected_action_count"] == 0


def test_stage_true_defaults_top_one(monkeypatch):
    analysis = _sample_analysis()
    proposal = _sample_proposal_result(analysis)
    captured: dict = {}

    def fake_stage(pr, *, days_back, top_n, action_index, action_indices, reason):
        captured["action_index"] = action_index
        captured["action_indices"] = action_indices
        return {
            "status": "ok",
            "selected_count": 1,
            "staged_actions": [{"title": "Staged", "priority": "high"}],
        }

    monkeypatch.setattr(
        "app.jarvis.marketing_tools.run_analyze_marketing_opportunities",
        lambda **k: analysis,
    )
    monkeypatch.setattr(
        "app.jarvis.marketing_tools.build_proposals_from_analysis",
        lambda a, **k: proposal,
    )
    monkeypatch.setattr(
        "app.jarvis.marketing_tools.run_stage_marketing_action_for_approval_with_proposal_result",
        fake_stage,
    )
    out = run_marketing_review(stage_for_approval=True, stage_indices=None)
    assert captured.get("action_index") == 0
    assert captured.get("action_indices") is None
    assert out["selected_action_count"] == 1


def test_explicit_indices_staged():
    analysis = _sample_analysis()
    proposal = {
        "status": "ok",
        "business": "TestBiz",
        "days_back": 28,
        "top_n": 5,
        "analysis_status": "full",
        "proposed_actions": [
            {"title": "A", "priority": "high", "reason": "r", "action_type": "x"},
            {"title": "B", "priority": "medium", "reason": "r2", "action_type": "y"},
        ],
        "missing_data": [],
        "unavailable_sources": [],
    }
    captured: dict = {}

    def fake_stage(pr, *, days_back, top_n, action_index, action_indices, reason):
        captured["indices"] = list(action_indices) if action_indices is not None else None
        captured["action_index"] = action_index
        return {
            "status": "ok",
            "selected_count": len(action_indices or []),
            "staged_actions": [],
        }

    with patch(
        "app.jarvis.marketing_tools.run_analyze_marketing_opportunities",
        return_value=analysis,
    ):
        with patch(
            "app.jarvis.marketing_tools.build_proposals_from_analysis",
            return_value=proposal,
        ):
            with patch(
                "app.jarvis.marketing_tools.run_stage_marketing_action_for_approval_with_proposal_result",
                side_effect=fake_stage,
            ) as _st:
                out = run_marketing_review(
                    stage_for_approval=True,
                    stage_indices=[0, 1],
                )
    assert captured["indices"] == [0, 1]
    assert out["status"] == "ok"
    assert out["selected_action_count"] == 2


def test_duplicate_indices_invalid():
    analysis = _sample_analysis()
    proposal = _sample_proposal_result(analysis)

    with patch(
        "app.jarvis.marketing_tools.run_analyze_marketing_opportunities",
        return_value=analysis,
    ):
        with patch(
            "app.jarvis.marketing_tools.build_proposals_from_analysis",
            return_value=proposal,
        ):
            out = run_marketing_review(
                stage_for_approval=True,
                stage_indices=[0, 0],
            )
    assert out["status"] == "invalid_selection"
    assert "Duplicate" in out["summary"]


def test_invalid_indices_safe():
    analysis = _sample_analysis()
    proposal = _sample_proposal_result(analysis)

    with patch(
        "app.jarvis.marketing_tools.run_analyze_marketing_opportunities",
        return_value=analysis,
    ):
        with patch(
            "app.jarvis.marketing_tools.build_proposals_from_analysis",
            return_value=proposal,
        ):
            out = run_marketing_review(stage_for_approval=True, stage_indices=[99, 100])
    assert out["status"] == "invalid_selection"
    assert "incomplete" in out["summary"].lower() or "Invalid" in out["summary"]
    assert out["selected_action_count"] == 0


def test_partial_data_returns_structure():
    analysis = {
        "status": "insufficient_data",
        "business": "X",
        "available_sources": [],
        "biggest_opportunities": [],
        "biggest_wastes": [],
        "conversion_gaps": [],
        "missing_data": [{"title": "GA4 gap", "source": "ga4"}],
        "unavailable_sources": [{"key": "ga4_funnel"}],
    }
    from app.jarvis.marketing_action_proposals import build_proposals_from_analysis

    proposal = build_proposals_from_analysis(analysis, days_back=7, top_n=3)

    with patch(
        "app.jarvis.marketing_tools.run_analyze_marketing_opportunities",
        return_value=analysis,
    ):
        with patch(
            "app.jarvis.marketing_tools.build_proposals_from_analysis",
            return_value=proposal,
        ):
            out = run_marketing_review(days_back=7, top_n=3, stage_for_approval=False)
    assert "status" in out
    assert "summary" in out
    assert "missing_data" in out

