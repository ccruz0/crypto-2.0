from __future__ import annotations

from app.jarvis.autonomous_orchestrator import JarvisAutonomousOrchestrator
from app.jarvis.autonomous_schemas import (
    MISSION_STATUS_DONE,
    MISSION_STATUS_WAITING_FOR_APPROVAL,
    can_transition_mission,
)
from app.jarvis.telegram_control import classify_jarvis_command


class _FakeNotion:
    def __init__(self) -> None:
        self.state = "received"
        self.id = "mission-1"
        self.events: list[tuple[str, str, str]] = []

    def configured(self) -> bool:
        return True

    def create_mission(self, *, prompt: str, actor: str) -> dict:
        _ = prompt, actor
        return {"mission_id": self.id, "status": self.state}

    def get_mission(self, mission_id: str) -> dict | None:
        if mission_id != self.id:
            return None
        return {"mission_id": mission_id, "status": self.state, "task": "Mission"}

    def transition_state(self, mission_id: str, *, to_state: str, note: str = "") -> bool:
        self.events.append((mission_id, "state", to_state))
        self.state = to_state
        return True

    def append_agent_output(self, mission_id: str, *, agent_name: str, content: str) -> None:
        self.events.append((mission_id, agent_name, content))

    def append_event(self, mission_id: str, *, event: str, detail: str = "") -> None:
        self.events.append((mission_id, event, detail))

    def get_recent_outcomes(self, mission_id: str, *, limit: int = 25) -> list[dict]:
        _ = mission_id, limit
        return [{"outcome": "success"}, {"outcome": "failure"}, {"outcome": "success"}]

    def append_action_baseline(self, mission_id: str, *, action: dict) -> None:
        self.events.append((mission_id, "baseline", str(action.get("title") or "")))

    def append_outcome_evaluation(self, mission_id: str, *, evaluations: list[dict], summary: dict) -> None:
        self.events.append((mission_id, "outcome_eval", f"{len(evaluations)}:{summary.get('total', 0)}"))

    def append_readability_executive_summary(self, mission_id: str, **kwargs) -> None:
        self.events.append((mission_id, "readability_summary", str(kwargs.get("status") or "")))

    def append_readability_timeline(self, mission_id: str, sentence: str) -> None:
        self.events.append((mission_id, "readability_timeline", sentence[:200]))

    def append_technical_detail_marker(self, mission_id: str, title: str = "") -> None:
        self.events.append((mission_id, "technical_marker", title))


class _FakeTelegram:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send_approval_request(self, chat_id: str, mission_id: str, summary: str) -> bool:
        self.sent.append(f"{chat_id}:{mission_id}:{summary}")
        return True

    def send_input_request(self, chat_id: str, mission_id: str, question: str) -> bool:
        self.sent.append(f"{chat_id}:{mission_id}:{question}")
        return True

    def send_ops_report(self, chat_id: str, ops_output: dict) -> bool:
        _ = ops_output
        self.sent.append(f"{chat_id}:ops")
        return True


class _PlannerCritical:
    def run(self, prompt: str) -> dict:
        _ = prompt
        return {
            "objective": "Test",
            "steps": ["Deploy new release to production"],
            "requires_research": False,
            "requires_input": False,
        }


class _ResearchNoop:
    def run(self, *, prompt: str, plan: dict) -> dict:
        _ = prompt, plan
        return {"findings": [], "open_questions": [], "confidence": 1.0}


class _ExecutionCritical:
    def run(self, *, strategy: dict | None, mission_prompt: str = ""):
        _ = strategy, mission_prompt
        return {
            "executed": [{"title": "Deploy to production", "action_type": "deploy", "execution_mode": "requires_approval", "priority_score": 95, "impact": "high"}],
            "waiting_for_approval": [{"title": "Deploy to production", "execution_mode": "requires_approval", "priority_score": 95}],
            "waiting_for_input": [],
            "needs_approval": True,
            "approval_summary": "Deploy to production",
        }


class _ReviewPass:
    def run(self, *, plan: dict, execution: dict) -> dict:
        _ = plan, execution
        return {"passed": True, "summary": "ok"}


class _StrategyNoop:
    def run(
        self,
        *,
        prompt: str,
        plan: dict,
        research: dict | None,
        outcome_memory: list[dict] | None = None,
    ) -> dict:
        _ = prompt, plan, research, outcome_memory
        return {
            "actions": [
                {
                    "title": "Deploy to production",
                    "rationale": "Requested in mission",
                    "action_type": "deploy",
                    "params": {"target": "prod"},
                    "impact": "high",
                    "confidence": 0.9,
                    "execution_mode": "requires_approval",
                    "priority_score": 95,
                    "requires_approval": True,
                }
            ]
        }


def test_mission_transition_guard_rules():
    assert can_transition_mission("planning", "researching") is True
    assert can_transition_mission("planning", "done") is False
    assert can_transition_mission("waiting_for_approval", "executing") is True


def test_classify_mission_command():
    kind, args = classify_jarvis_command("/mission approve mission-1") or ("", "")
    assert kind == "mission"
    assert args == "approve mission-1"


def test_orchestrator_pauses_for_approval():
    fake_notion = _FakeNotion()
    fake_tg = _FakeTelegram()
    orch = JarvisAutonomousOrchestrator(
        notion=fake_notion,
        planner=_PlannerCritical(),
        researcher=_ResearchNoop(),
        strategist=_StrategyNoop(),
        executor=_ExecutionCritical(),
        reviewer=_ReviewPass(),
        telegram=fake_tg,
    )

    out = orch.run_new_mission(prompt="deploy app", actor="@ops", chat_id="123")

    assert out["status"] == MISSION_STATUS_WAITING_FOR_APPROVAL
    assert fake_notion.state == MISSION_STATUS_WAITING_FOR_APPROVAL
    assert fake_tg.sent, "approval message must be sent to telegram"
    assert any(ev[1] == "strategy" for ev in fake_notion.events), "strategy output must be written to Notion"
    assert any(ev[1] == "outcome_evaluator" for ev in fake_notion.events), "outcome evaluation must be logged"


def test_orchestrator_approval_completes_mission():
    fake_notion = _FakeNotion()
    fake_tg = _FakeTelegram()
    fake_notion.state = MISSION_STATUS_WAITING_FOR_APPROVAL
    orch = JarvisAutonomousOrchestrator(
        notion=fake_notion,
        planner=_PlannerCritical(),
        researcher=_ResearchNoop(),
        strategist=_StrategyNoop(),
        executor=_ExecutionCritical(),
        reviewer=_ReviewPass(),
        telegram=fake_tg,
    )

    out = orch.continue_after_approval(
        mission_id="mission-1",
        approved=True,
        actor="@ops",
        chat_id="123",
    )
    assert out["status"] == MISSION_STATUS_DONE
    assert fake_notion.state == MISSION_STATUS_DONE


def test_strategy_action_shape_includes_policy_fields():
    action = _StrategyNoop().run(prompt="p", plan={}, research={})["actions"][0]
    assert action["action_type"] == "deploy"
    assert isinstance(action.get("params"), dict)
    assert action["execution_mode"] == "requires_approval"
    assert isinstance(action["priority_score"], int)


def test_outcome_evaluation_records_baseline_and_results():
    fake_notion = _FakeNotion()
    fake_tg = _FakeTelegram()
    orch = JarvisAutonomousOrchestrator(
        notion=fake_notion,
        planner=_PlannerCritical(),
        researcher=_ResearchNoop(),
        strategist=_StrategyNoop(),
        executor=_ExecutionCritical(),
        reviewer=_ReviewPass(),
        telegram=fake_tg,
    )
    orch.run_new_mission(prompt="deploy app", actor="@ops", chat_id="123")
    assert any(ev[1] == "baseline" for ev in fake_notion.events)
    assert any(ev[1] == "outcome_eval" for ev in fake_notion.events)

