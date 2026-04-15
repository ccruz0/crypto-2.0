"""Deterministic planner routing for natural-language marketing / website requests."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.jarvis.planner import create_plan


@pytest.mark.parametrize(
    "user_input",
    [
        "/jarvis review my marketing",
        "/jarvis review my marketing please",
        "review my marketing",
        "analiza mi web",
        "analiza mi web de la peluqueria",
        "que mejorar en mi marketing",
        "que puedo mejorar en mi web",
        "analyze my website",
        "analyze my website deeply",
        "revisa mi web",
        "what should I improve on my site",
    ],
)
def test_fuzzy_marketing_routes_to_run_marketing_review(user_input: str) -> None:
    with patch("app.jarvis.planner.ask_bedrock") as mock_bedrock:
        plan = create_plan(user_input, jarvis_run_id="test-run")
    mock_bedrock.assert_not_called()
    assert plan.get("action") == "run_marketing_review"
    assert plan.get("args") == {}
    assert "fuzzy_marketing_intent" in (plan.get("reasoning") or "")


def test_slash_jarvis_review_my_marketing() -> None:
    with patch("app.jarvis.planner.ask_bedrock") as mock_bedrock:
        plan = create_plan("/jarvis review my marketing", jarvis_run_id="r1")
    mock_bedrock.assert_not_called()
    assert plan.get("action") == "run_marketing_review"


def test_unrelated_text_does_not_route_to_marketing_review() -> None:
    with patch("app.jarvis.planner.ask_bedrock", return_value="not json") as mock_bedrock:
        plan = create_plan("the weather is nice in tokyo today", jarvis_run_id="r2")
    mock_bedrock.assert_called_once()
    assert plan.get("action") == "echo_message"


def test_marketing_only_without_action_does_not_fuzzy_route() -> None:
    """Domain keyword alone must not trigger review."""
    with patch("app.jarvis.planner.ask_bedrock", return_value="not json"):
        plan = create_plan("I read a marketing newsletter yesterday", jarvis_run_id="r3")
    assert plan.get("action") == "echo_message"


def test_fallback_plan_prefers_marketing_over_echo() -> None:
    from app.jarvis.planner import _fallback_plan

    out = _fallback_plan("analyze my website", "parse_failed")
    assert out.get("action") == "run_marketing_review"
