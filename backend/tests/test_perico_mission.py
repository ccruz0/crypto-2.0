"""Perico software specialist: routing, guards, and deliverables helpers."""

from __future__ import annotations

from app.jarvis import telegram_control as tc
from app.jarvis.analytics_mission_deliverables import infer_analytics_deliverables
from app.jarvis.autonomous_orchestrator import JarvisAutonomousOrchestrator
from app.jarvis.mission_goal_quality import should_attempt_goal_retry
from app.jarvis.perico_mission import (
    PERICO_AGENT_MARKER,
    build_perico_deliverables_snapshot,
    build_perico_mission_prompt,
    classify_perico_task_type,
    infer_perico_target_project,
    is_perico_marked_prompt,
)


def test_classify_perico_command():
    assert tc.classify_jarvis_command("/perico arregla el bug") == ("perico", "arregla el bug")
    assert tc.classify_jarvis_command("/perico") == ("perico", "")


def test_build_perico_mission_prompt_contains_marker_and_default_project():
    p = build_perico_mission_prompt(user_text="revisa tests")
    assert PERICO_AGENT_MARKER in p
    assert "[PERICO_TARGET_PROJECT_HINT:" in p
    assert "crypto-2.0" in p
    assert "Operator software task:" in p
    assert "revisa tests" in p


def test_infer_perico_target_project_signals():
    assert infer_perico_target_project("fallo en ATP telegram") == "ATP"
    assert infer_perico_target_project("repo Rahyang") == "Rahyang"
    assert infer_perico_target_project("sitio peluquería") == "Peluquería Cruz"
    assert infer_perico_target_project("solo arregla un typo") is None


def test_classify_perico_task_type():
    assert classify_perico_task_type("hay un bug en login") == "bugfix"
    assert classify_perico_task_type("corre pytest") == "validation"
    assert classify_perico_task_type("refactor limpiar") == "refactor"
    assert classify_perico_task_type("investiga por qué falla") == "diagnostics"


def test_infer_analytics_deliverables_skips_perico_marked_prompt():
    wrapped = build_perico_mission_prompt(user_text="Google Ads spend last 30 days top campaigns")
    assert is_perico_marked_prompt(wrapped)
    assert infer_analytics_deliverables(wrapped) is None


def test_should_attempt_goal_retry_skips_perico_even_if_auto_retry_flag():
    prompt = build_perico_mission_prompt(user_text="x")
    goal_eval = {"satisfied": False, "auto_retry_recommended": True}
    assert should_attempt_goal_retry(mission_prompt=prompt, goal_eval=goal_eval, retry_used=False) is False


def test_merge_google_ads_mutation_proposals_skips_perico_prompt():
    orch = JarvisAutonomousOrchestrator()
    execution: dict = {"waiting_for_approval": [], "executed": []}
    prompt = build_perico_mission_prompt(user_text="diagnóstico Google Ads")
    out = orch._merge_google_ads_mutation_proposals(
        mission_id="m1",
        prompt=prompt,
        execution=execution,
    )
    assert out is execution


def test_dispatch_perico_requires_task(monkeypatch):
    called: list[dict] = []

    def _capture(**kwargs):
        called.append(kwargs)
        return {"ok": True}

    monkeypatch.setattr(tc, "is_autonomous_jarvis_enabled", lambda: True)
    monkeypatch.setattr(tc, "run_perico_from_telegram", _capture)
    kind, payload = tc.dispatch_jarvis_command("perico", "", actor="a", chat_id="c")
    assert kind == "jarvis"
    assert payload.get("ok") is False
    assert "Uso:" in str(payload.get("dialog_message") or "")
    assert called == []


def test_dispatch_perico_requires_autonomous(monkeypatch):
    monkeypatch.setattr(tc, "is_autonomous_jarvis_enabled", lambda: False)
    kind, payload = tc.dispatch_jarvis_command("perico", "fix", actor="a", chat_id="c")
    assert "JARVIS_AUTONOMOUS_ENABLED" in str(payload.get("dialog_message") or "")


def test_dispatch_perico_runs_when_enabled(monkeypatch):
    monkeypatch.setattr(tc, "is_autonomous_jarvis_enabled", lambda: True)

    def _fake_run(*, text: str, actor: str, chat_id: str):
        assert text == "fix X"
        assert actor == "op"
        assert chat_id == "1"
        return {"ok": True, "dialog_message": "done"}

    monkeypatch.setattr(tc, "run_perico_from_telegram", _fake_run)
    kind, payload = tc.dispatch_jarvis_command("perico", "fix X", actor="op", chat_id="1")
    assert kind == "jarvis"
    assert payload.get("dialog_message") == "done"


def test_perico_deliverables_snapshot_goal_not_satisfied():
    mp = build_perico_mission_prompt(user_text="unit tests")
    snap = build_perico_deliverables_snapshot(
        mission_prompt=mp,
        plan={"objective": "x"},
        execution={"executed": [{"action_type": "run_shell", "title": "pytest", "result": {}}]},
        goal_satisfied=False,
    )
    assert snap["objective_satisfied"] is False
    assert snap["deploy_sensitive"] is False


def test_perico_deliverables_deploy_sensitive_heuristic():
    mp = build_perico_mission_prompt(user_text="x")
    snap = build_perico_deliverables_snapshot(
        mission_prompt=mp,
        plan={},
        execution={
            "executed": [
                {"action_type": "custom", "title": "terraform apply prod", "rationale": ""},
            ]
        },
        goal_satisfied=True,
    )
    assert snap["deploy_sensitive"] is True
    assert snap["objective_satisfied"] is True
