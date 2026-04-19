"""Orchestrator integration: goal satisfaction, one automatic retry, and done gating."""

from __future__ import annotations

from typing import Any

from app.jarvis.autonomous_orchestrator import JarvisAutonomousOrchestrator
from app.jarvis.autonomous_schemas import (
    MISSION_STATUS_DONE,
    MISSION_STATUS_WAITING_FOR_APPROVAL,
    MISSION_STATUS_WAITING_FOR_INPUT,
)

from test_jarvis_autonomous_mission import _FakeNotion, _FakeTelegram

GOOGLE_ADS_READ_ONLY_FULL = (
    "Analyze my Google Ads account for the last 30 days. Return top 10 campaigns by spend "
    "with impressions, clicks, CTR, conversions, cost, top issues, and top opportunities. Read-only only."
)


class _PlannerOk:
    def run(self, prompt: str) -> dict[str, Any]:
        _ = prompt
        return {"objective": "Read-only Google Ads analytics", "requires_input": False, "requires_research": False}


class _PlannerNeedsInput:
    def run(self, prompt: str) -> dict[str, Any]:
        _ = prompt
        return {
            "objective": "Unclear scope",
            "requires_input": True,
            "requires_research": False,
            "input_request": "missing constraints",
        }


class _ResearchNoop:
    def run(self, *, prompt: str, plan: dict) -> dict:
        _ = prompt, plan
        return {"findings": [], "open_questions": [], "confidence": 1.0}


class _StrategyAdsDiagnose:
    def run(self, **kwargs: Any) -> dict[str, Any]:
        _ = kwargs
        return {
            "actions": [
                {
                    "title": "Google Ads diagnostics",
                    "rationale": "Read-only",
                    "action_type": "diagnose_google_ads_setup",
                    "params": {},
                    "impact": "high",
                    "confidence": 0.9,
                    "execution_mode": "auto_execute",
                    "priority_score": 99,
                    "requires_approval": False,
                }
            ],
            "source": "test",
        }


class _OpsNoApproval:
    def run(self, **kwargs: Any) -> dict[str, Any]:
        _ = kwargs
        return {"waiting_for_approval": [], "diagnostics": []}


class _ReviewPass:
    def run(self, *, plan: dict, execution: dict) -> dict[str, Any]:
        _ = plan, execution
        return {"passed": True, "summary": "ok"}


_SHALLOW_RESULT: dict[str, Any] = {
    "auth_ok": True,
    "campaign_fetch_ok": True,
    "campaigns": ["x"],
    "analytics_top_campaigns": [],
    "analytics_summary": "",
    "analytics_issues": [],
    "analytics_opportunities": [],
}

_RICH_RESULT: dict[str, Any] = {
    "auth_ok": True,
    "campaign_fetch_ok": True,
    "analytics_top_campaigns": [
        {
            "name": "Camp",
            "cost": "10",
            "impressions": 100,
            "clicks": 5,
            "ctr": "5%",
            "conversions": 1.0,
        }
    ],
    "analytics_summary": "Top line summary.",
    "analytics_issues": ["Issue a"],
    "analytics_opportunities": ["Opp b"],
}


class _ExecShallowThenRich:
    def __init__(self) -> None:
        self.runs = 0

    def run(self, *, strategy: dict | None, mission_prompt: str = ""):
        _ = strategy, mission_prompt
        self.runs += 1
        res = _SHALLOW_RESULT if self.runs == 1 else _RICH_RESULT
        return {
            "executed": [{"action_type": "diagnose_google_ads_setup", "result": res}],
            "waiting_for_approval": [],
            "waiting_for_input": [],
            "needs_approval": False,
        }


class _ExecAlwaysShallow:
    def __init__(self) -> None:
        self.runs = 0

    def run(self, *, strategy: dict | None, mission_prompt: str = ""):
        _ = strategy, mission_prompt
        self.runs += 1
        return {
            "executed": [{"action_type": "diagnose_google_ads_setup", "result": dict(_SHALLOW_RESULT)}],
            "waiting_for_approval": [],
            "waiting_for_input": [],
            "needs_approval": False,
        }


class _ExecRichOnce:
    def run(self, *, strategy: dict | None, mission_prompt: str = ""):
        _ = strategy, mission_prompt
        return {
            "executed": [{"action_type": "diagnose_google_ads_setup", "result": dict(_RICH_RESULT)}],
            "waiting_for_approval": [],
            "waiting_for_input": [],
            "needs_approval": False,
        }


def test_google_ads_well_specified_completes_without_autoretry():
    fake = _FakeNotion()
    tg = _FakeTelegram()
    orch = JarvisAutonomousOrchestrator(
        notion=fake,
        planner=_PlannerOk(),
        researcher=_ResearchNoop(),
        strategist=_StrategyAdsDiagnose(),
        ops=_OpsNoApproval(),
        executor=_ExecRichOnce(),
        reviewer=_ReviewPass(),
        telegram=tg,
    )
    out = orch.run_new_mission(prompt=GOOGLE_ADS_READ_ONLY_FULL, actor="u", chat_id="1")
    assert out["status"] == MISSION_STATUS_DONE
    assert not any(ev[1] == "goal_autoretry" for ev in fake.events)


def test_google_ads_shallow_then_rich_triggers_one_retry_then_done():
    fake = _FakeNotion()
    ex = _ExecShallowThenRich()
    orch = JarvisAutonomousOrchestrator(
        notion=fake,
        planner=_PlannerOk(),
        researcher=_ResearchNoop(),
        strategist=_StrategyAdsDiagnose(),
        ops=_OpsNoApproval(),
        executor=ex,
        reviewer=_ReviewPass(),
        telegram=_FakeTelegram(),
    )
    out = orch.run_new_mission(prompt=GOOGLE_ADS_READ_ONLY_FULL, actor="u", chat_id="1")
    assert out["status"] == MISSION_STATUS_DONE
    assert ex.runs == 2
    assert sum(1 for ev in fake.events if ev[1] == "goal_autoretry") == 1
    assert any(ev[1] == "execution_retry" for ev in fake.events)


def test_google_ads_stays_shallow_after_retry_waits_for_input_not_done():
    fake = _FakeNotion()
    ex = _ExecAlwaysShallow()
    orch = JarvisAutonomousOrchestrator(
        notion=fake,
        planner=_PlannerOk(),
        researcher=_ResearchNoop(),
        strategist=_StrategyAdsDiagnose(),
        ops=_OpsNoApproval(),
        executor=ex,
        reviewer=_ReviewPass(),
        telegram=_FakeTelegram(),
    )
    out = orch.run_new_mission(prompt=GOOGLE_ADS_READ_ONLY_FULL, actor="u", chat_id="1")
    assert out["status"] == MISSION_STATUS_WAITING_FOR_INPUT
    assert fake.state == MISSION_STATUS_WAITING_FOR_INPUT
    assert ex.runs == 2


def test_planner_requires_input_sends_natural_clarification_not_rigid_block(monkeypatch):
    monkeypatch.setattr("app.jarvis.bedrock_client.ask_bedrock", lambda _q: (_ for _ in ()).throw(RuntimeError("off")))
    fake = _FakeNotion()
    tg = _FakeTelegram()
    orch = JarvisAutonomousOrchestrator(
        notion=fake,
        planner=_PlannerNeedsInput(),
        telegram=tg,
    )
    out = orch.run_new_mission(prompt="Do something with Google Ads", actor="u", chat_id="1")
    assert out["status"] == MISSION_STATUS_WAITING_FOR_INPUT
    msg = out["dialog_message"]
    assert "Provide missing constraints" not in msg
    assert "Before I start" in msg or "?" in msg


def test_mutating_mission_still_pauses_for_approval_not_done():
    class _StrategyDeploy:
        def run(self, **kwargs: Any) -> dict[str, Any]:
            _ = kwargs
            return {
                "actions": [
                    {
                        "title": "Deploy",
                        "rationale": "go",
                        "action_type": "deploy",
                        "params": {},
                        "impact": "high",
                        "confidence": 0.9,
                        "execution_mode": "requires_approval",
                        "priority_score": 95,
                        "requires_approval": True,
                    }
                ],
                "source": "test",
            }

    class _ExecDeployApproval:
        def run(self, *, strategy: dict | None, mission_prompt: str = ""):
            _ = strategy, mission_prompt
            return {
                "executed": [{"title": "Deploy", "action_type": "deploy"}],
                "waiting_for_approval": [{"title": "Deploy", "execution_mode": "requires_approval"}],
                "waiting_for_input": [],
                "needs_approval": True,
            }

    fake = _FakeNotion()
    orch = JarvisAutonomousOrchestrator(
        notion=fake,
        planner=_PlannerOk(),
        researcher=_ResearchNoop(),
        strategist=_StrategyDeploy(),
        ops=_OpsNoApproval(),
        executor=_ExecDeployApproval(),
        reviewer=_ReviewPass(),
        telegram=_FakeTelegram(),
    )
    out = orch.run_new_mission(prompt="Deploy the backend to production", actor="u", chat_id="1")
    assert out["status"] == MISSION_STATUS_WAITING_FOR_APPROVAL
    assert fake.state == MISSION_STATUS_WAITING_FOR_APPROVAL
