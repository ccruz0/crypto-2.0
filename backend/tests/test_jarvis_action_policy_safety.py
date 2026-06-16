"""Tests that action_policy delegates to execution.safety consistently."""

from __future__ import annotations

import pytest

from app.jarvis.action_policy import (
    classify_objective_safety,
    classify_objective_safety_with_reason,
    is_autonomous_mission_blocked,
    is_objective_forbidden,
)
from app.jarvis.autonomous_agents import ExecutionAgent, PlannerAgent as BedrockPlannerAgent, StrategyAgent
from app.jarvis.autonomous_orchestrator import JarvisAutonomousOrchestrator
from app.jarvis.execution.safety import SafetyLevel, classify_text_with_reason
from app.jarvis.agents.planner_agent import build_plan


_FORBIDDEN_OBJECTIVES = [
    "Investigate and execute trade if missing orders are detected",
    "Investigate missing BTC orders and place replacement orders",
    "Investigate discrepancy and cancel all open orders",
    "Investigate portfolio mismatch and buy BTC",
    "Investigate open orders and sell ETH",
    "Execute market order after checking logs",
    "Open a BTC position after investigating logs",
    "Close all positions after checking reconciliation",
]

_SAFE_OBJECTIVES = [
    "Why are executed orders missing?",
    "Investigate reconciliation mismatch between database and Crypto.com",
    "Explain discrepancy in open orders",
    "Investigate BTC open orders without placing trades",
    "Read logs and explain why orders are missing",
]


@pytest.mark.parametrize("objective", _FORBIDDEN_OBJECTIVES)
def test_action_policy_matches_execution_safety_forbidden(objective: str):
    direct = classify_text_with_reason(objective)
    via_policy = classify_objective_safety_with_reason(objective)
    assert direct == via_policy
    assert classify_objective_safety(objective) == SafetyLevel.FORBIDDEN
    assert is_objective_forbidden(objective)


@pytest.mark.parametrize("objective", _SAFE_OBJECTIVES)
def test_action_policy_matches_execution_safety_safe(objective: str):
    direct = classify_text_with_reason(objective)
    via_policy = classify_objective_safety_with_reason(objective)
    assert direct == via_policy
    assert classify_objective_safety(objective) == SafetyLevel.SAFE_AUTO
    assert not is_objective_forbidden(objective)


@pytest.mark.parametrize("objective", _FORBIDDEN_OBJECTIVES)
def test_bedrock_planner_blocks_forbidden_objective(objective: str):
    plan = BedrockPlannerAgent().run(objective)
    assert plan.get("overall_safety") == SafetyLevel.FORBIDDEN.value
    assert plan.get("source") == "safety_blocked"
    assert plan.get("steps") == []


@pytest.mark.parametrize("objective", _SAFE_OBJECTIVES)
def test_phase3_planner_matches_policy_safe(objective: str):
    assert build_plan(objective).overall_safety == SafetyLevel.SAFE_AUTO.value
    assert classify_objective_safety(objective) == SafetyLevel.SAFE_AUTO


@pytest.mark.parametrize("objective", _FORBIDDEN_OBJECTIVES)
def test_phase3_planner_matches_policy_forbidden(objective: str):
    assert build_plan(objective).overall_safety == SafetyLevel.FORBIDDEN.value
    assert classify_objective_safety(objective) == SafetyLevel.FORBIDDEN


def test_execution_agent_blocks_forbidden_mission_prompt():
    result = ExecutionAgent().run(
        strategy={"actions": [{"title": "Run analysis", "action_type": "analysis", "execution_mode": "auto_execute"}]},
        mission_prompt="Investigate and execute trade if missing orders are detected",
    )
    assert result.get("blocked") is True
    assert result.get("safety_level") == SafetyLevel.FORBIDDEN.value
    assert result.get("executed") == []


def test_strategy_agent_skips_forbidden_action_titles():
    strategy = StrategyAgent().run(
        prompt="Why are executed orders missing?",
        plan={"objective": "investigate"},
        research={"findings": [], "confidence": 0.9},
    )
    titles = [a.get("title") for a in strategy.get("actions") or []]
    assert not any("execute trade" in (t or "").lower() for t in titles)


class _SafetyNotion:
    def configured(self) -> bool:
        return True

    def create_mission(self, **kwargs):
        return {"mission_id": "m-safety-1"}

    def transition_state(self, *args, **kwargs):
        return True

    def append_readability_timeline(self, *args, **kwargs):
        return None

    def append_readability_timeline_low(self, *args, **kwargs):
        return None

    def append_event(self, *args, **kwargs):
        return None

    def append_agent_output(self, *args, **kwargs):
        return None

    def append_technical_detail_marker(self, *args, **kwargs):
        return None


class _SafetyTelegram:
    def send_message(self, *args, **kwargs):
        return True


def test_orchestrator_blocks_forbidden_mission_at_pipeline_start():
    orch = JarvisAutonomousOrchestrator(notion=_SafetyNotion(), telegram=_SafetyTelegram())
    result = orch._run_pipeline(
        mission_id="m-safety-1",
        prompt="Investigate missing BTC orders and place replacement orders",
        actor="tester",
        chat_id="1",
        external_input="",
    )
    assert result.get("ok") is False
    assert result.get("status") == "failed"
    assert result.get("safety", {}).get("level") == SafetyLevel.FORBIDDEN.value


def test_deploy_mission_not_blocked_by_autonomous_gate():
    assert not is_autonomous_mission_blocked("deploy app")
