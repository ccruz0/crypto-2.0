"""Perico software specialist: routing, guards, and deliverables helpers."""

from __future__ import annotations

from app.jarvis import telegram_control as tc
from app.jarvis.analytics_mission_deliverables import infer_analytics_deliverables
from app.jarvis.autonomous_orchestrator import JarvisAutonomousOrchestrator
from app.jarvis.mission_goal_quality import should_attempt_goal_retry
from app.jarvis.mission_goal_quality import evaluate_goal_satisfaction
from app.jarvis.perico_mission import (
    PERICO_AGENT_MARKER,
    build_perico_deliverables_snapshot,
    build_perico_mission_prompt,
    classify_perico_task_type,
    format_perico_closure_key_result,
    format_perico_closure_status_display,
    infer_perico_target_project,
    is_perico_marked_prompt,
    is_perico_software_mission_prompt,
    normalize_perico_strategy_actions,
    parse_perico_task_type_from_prompt,
)


def test_classify_perico_command():
    assert tc.classify_jarvis_command("/perico arregla el bug") == ("perico", "arregla el bug")
    assert tc.classify_jarvis_command("/perico") == ("perico", "")


def test_classify_perico_normalizes_zw_and_at_bot():
    from app.jarvis.telegram_control import classify_jarvis_command, normalize_telegram_slash_command

    assert classify_jarvis_command("\u200b/perico fix bug") == ("perico", "fix bug")
    assert classify_jarvis_command(normalize_telegram_slash_command("/perico@SomeBotName tail")) == (
        "perico",
        "tail",
    )


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
    assert classify_perico_task_type("arregla integración webhook que falla") == "integration_fix"


def test_classify_perico_crypto_tests_prompt_is_bugfix_not_diagnostics():
    text = (
        "Hay un problema con los tests en crypto-2.0. Algunos están fallando. "
        "Investiga la causa, aplica un parche mínimo si tiene sentido y ejecuta pytest para validar. "
        "No hagas deploy."
    )
    assert classify_perico_task_type(text) == "bugfix"
    mp = build_perico_mission_prompt(user_text=text)
    assert parse_perico_task_type_from_prompt(mp) == "bugfix"
    assert "[PERICO_TASK_TYPE: bugfix]" in mp


def test_is_perico_software_mission_prompt_without_agent_marker():
    full = build_perico_mission_prompt(user_text="fix tests")
    assert is_perico_software_mission_prompt(full) is True
    stripped = full.replace(PERICO_AGENT_MARKER, "").lstrip()
    assert is_perico_software_mission_prompt(stripped) is True


def test_google_ads_mission_heuristic_skips_perico_boilerplate_without_marker():
    orch = JarvisAutonomousOrchestrator()
    p = build_perico_mission_prompt(user_text="fix tests").replace(PERICO_AGENT_MARKER, "").lstrip()
    assert (
        orch._is_google_ads_mission(prompt=p, strategy={"actions": [], "source": "bedrock"}) is False
    )


def test_parse_perico_task_type_from_wrapped_prompt():
    mp = build_perico_mission_prompt(user_text="arregla integración webhook que falla")
    assert parse_perico_task_type_from_prompt(mp) == "integration_fix"


def test_evaluate_goal_bugfix_patch_and_pytest_green():
    mp = build_perico_mission_prompt(user_text="hay un bug en login")
    ex = {
        "executed": [
            {
                "action_type": "perico_repo_read",
                "params": {"operation": "read", "relative_path": "a.py"},
                "result": {"ok": True, "operation": "read", "path": "/tmp/a.py", "content": "x"},
            },
            {"action_type": "perico_apply_patch", "result": {"ok": True, "relative_path": "a.py"}},
            {
                "action_type": "perico_run_pytest",
                "result": {"ok": True, "pytest": True, "tests_ok": True, "exit_code": 0},
            },
        ]
    }
    g = evaluate_goal_satisfaction(mission_prompt=mp, execution=ex)
    assert g["satisfied"] is True
    assert g.get("evaluator_domain") == "perico_bugfix"


def test_evaluate_goal_bugfix_patch_without_pytest_not_satisfied():
    mp = build_perico_mission_prompt(user_text="fix bug en auth")
    ex = {
        "executed": [
            {
                "action_type": "perico_repo_read",
                "result": {"ok": True, "operation": "read", "path": "/x", "content": "1"},
            },
            {"action_type": "perico_apply_patch", "result": {"ok": True, "relative_path": "a.py"}},
        ]
    }
    g = evaluate_goal_satisfaction(mission_prompt=mp, execution=ex)
    assert g["satisfied"] is False
    assert "perico_bugfix_validation_missing" in g.get("missing_items", [])


def test_evaluate_goal_bugfix_pytest_fail_then_retry_success():
    mp = build_perico_mission_prompt(user_text="bug en parser")
    ex = {
        "executed": [
            {
                "action_type": "perico_repo_read",
                "result": {"ok": True, "operation": "read", "path": "/r/p.py", "content": "x"},
            },
            {"action_type": "perico_apply_patch", "result": {"ok": True, "relative_path": "p.py"}},
            {
                "action_type": "perico_run_pytest",
                "result": {"ok": True, "pytest": True, "tests_ok": False, "exit_code": 1},
            },
            {
                "action_type": "perico_run_pytest",
                "title": "Automatic pytest retry (Perico)",
                "result": {"ok": True, "pytest": True, "tests_ok": True, "exit_code": 0},
            },
        ]
    }
    g = evaluate_goal_satisfaction(mission_prompt=mp, execution=ex)
    assert g["satisfied"] is True


def test_evaluate_goal_bugfix_pytest_fail_after_retry_not_satisfied():
    mp = build_perico_mission_prompt(user_text="bug en parser")
    ex = {
        "executed": [
            {
                "action_type": "perico_repo_read",
                "result": {"ok": True, "operation": "grep", "matches": [{"path": "p.py", "line": 1, "text": "x"}]},
            },
            {"action_type": "perico_apply_patch", "result": {"ok": True, "relative_path": "p.py"}},
            {
                "action_type": "perico_run_pytest",
                "result": {"ok": True, "pytest": True, "tests_ok": False, "exit_code": 1},
            },
            {
                "action_type": "perico_run_pytest",
                "title": "Automatic pytest retry (Perico)",
                "result": {
                    "ok": True,
                    "pytest": True,
                    "tests_ok": False,
                    "exit_code": 1,
                    "retry_reason": "x",
                },
            },
        ]
    }
    g = evaluate_goal_satisfaction(mission_prompt=mp, execution=ex)
    assert g["satisfied"] is False
    assert "perico_bugfix_tests_failed" in g.get("missing_items", [])


def test_evaluate_goal_bugfix_diagnosis_only_insufficient_without_patch():
    mp = build_perico_mission_prompt(user_text="error raro en modulo X")
    ex = {
        "executed": [
            {
                "action_type": "perico_repo_read",
                "result": {"ok": True, "operation": "read", "path": "/repo/x.py", "content": "ok"},
            },
        ]
    }
    g = evaluate_goal_satisfaction(mission_prompt=mp, execution=ex)
    assert g["satisfied"] is False
    assert "perico_bugfix_patch_missing" in g.get("missing_items", [])


def test_evaluate_goal_bugfix_no_inspection_not_satisfied():
    mp = build_perico_mission_prompt(user_text="fix bug z")
    g = evaluate_goal_satisfaction(mission_prompt=mp, execution={"executed": []})
    assert g["satisfied"] is False
    assert "perico_bugfix_inspection_missing" in g.get("missing_items", [])


def test_bugfix_deliverables_blocked_when_pytest_red():
    mp = build_perico_mission_prompt(user_text="fix bug en modulo z")
    execution = {
        "executed": [
            {
                "action_type": "perico_repo_read",
                "result": {"ok": True, "operation": "read", "path": "/r/a.py", "content": "1"},
            },
            {"action_type": "perico_apply_patch", "result": {"ok": True, "relative_path": "a.py"}},
            {
                "action_type": "perico_run_pytest",
                "result": {"ok": True, "pytest": True, "tests_ok": False, "exit_code": 1, "stderr_tail": "E"},
            },
            {
                "action_type": "perico_run_pytest",
                "result": {"ok": True, "pytest": True, "tests_ok": False, "exit_code": 1},
            },
        ]
    }
    snap = build_perico_deliverables_snapshot(
        mission_prompt=mp,
        plan={"objective": "Arreglar regresión"},
        execution=execution,
        goal_satisfied=False,
        retry_attempted=True,
    )
    assert snap.get("software_closure_state") == "blocked"
    assert snap.get("bugfix_rubric") is True
    assert "fall" in (snap.get("validation_result_summary") or "").lower()


def test_bugfix_deliverables_include_summaries_and_closure():
    mp = build_perico_mission_prompt(user_text="arregla fallo tests")
    plan = {"objective": "Corregir aserción rota en módulo foo"}
    execution = {
        "executed": [
            {
                "action_type": "perico_repo_read",
                "title": "Leer foo.py",
                "rationale": "Ubicar la aserción incorrecta",
                "params": {"operation": "read", "relative_path": "foo.py"},
                "result": {"ok": True, "operation": "read", "path": "/r/foo.py", "content": "1"},
            },
            {"action_type": "perico_apply_patch", "result": {"ok": True, "relative_path": "foo.py"}},
            {
                "action_type": "perico_run_pytest",
                "result": {"ok": True, "pytest": True, "tests_ok": True, "exit_code": 0, "cmd": ["pytest", "t.py"]},
            },
        ]
    }
    snap = build_perico_deliverables_snapshot(
        mission_prompt=mp,
        plan=plan,
        execution=execution,
        goal_satisfied=True,
        retry_attempted=False,
    )
    assert snap.get("bugfix_rubric") is True
    assert snap.get("software_closure_state") == "fixed"
    assert "pytest" in (snap.get("validation_result_summary") or "").lower()
    assert snap.get("fix_attempted") is True
    assert "Corregir" in (snap.get("hypothesis_summary") or "")
    assert snap.get("root_cause_summary")
    assert snap.get("retry_reason") == ""


def test_evaluate_goal_non_bugfix_perico_lenient():
    mp = build_perico_mission_prompt(user_text="corre pytest en backend")
    g = evaluate_goal_satisfaction(mission_prompt=mp, execution={"executed": []})
    assert g["satisfied"] is True
    assert g.get("reason") == "perico_no_bugfix_rubric"


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


def test_format_perico_closure_status_and_key_result_fixed():
    snap = {
        "software_closure_state": "fixed",
        "validation_result_summary": "pytest (última pasada): OK",
    }
    assert format_perico_closure_status_display(snap) == "FIXED"
    ex = {
        "executed": [
            {
                "action_type": "perico_run_pytest",
                "result": {"pytest": True, "tests_ok": True, "tests_total": 40, "tests_failed": 0},
            }
        ]
    }
    kr = format_perico_closure_key_result(snap, ex)
    assert "verde" in kr.lower()
    assert "40" in kr


def test_format_perico_closure_blocked_includes_counts():
    snap = {
        "software_closure_state": "blocked",
        "validation_result_summary": "pytest (última pasada): falló",
    }
    assert format_perico_closure_status_display(snap) == "BLOCKED"
    ex = {
        "executed": [
            {
                "action_type": "perico_run_pytest",
                "result": {"pytest": True, "tests_ok": False, "tests_total": 12, "tests_failed": 3},
            }
        ]
    }
    kr = format_perico_closure_key_result(snap, ex)
    assert "3" in kr and "12" in kr


def test_perico_done_dialog_message_uses_closure_not_review_summary():
    orch = JarvisAutonomousOrchestrator()
    mp = build_perico_mission_prompt(user_text="arreglar tests crypto")
    execution = {
        "executed": [
            {
                "action_type": "perico_repo_read",
                "result": {"ok": True, "operation": "read", "path": "/r/x.py", "content": "1"},
            },
            {"action_type": "perico_apply_patch", "result": {"ok": True, "relative_path": "x.py"}},
            {
                "action_type": "perico_run_pytest",
                "result": {
                    "ok": True,
                    "pytest": True,
                    "tests_ok": True,
                    "tests_total": 5,
                    "tests_failed": 0,
                    "cmd": ["pytest", "-q"],
                },
            },
        ]
    }
    text = orch._format_perico_done_dialog_message(  # noqa: SLF001
        mission_id="mid",
        prompt=mp,
        execution=execution,
        review={"summary": "Mission completed with safe actions and validation checks."},
        goal_satisfied=True,
        perico_deliverables_snapshot=None,
    )
    assert "Estado: FIXED" in text
    assert "Tests en verde" in text
    assert "Mission completed with safe actions" not in text


def test_perico_should_skip_nonconcrete_prepare_row():
    from app.jarvis.perico_mission import perico_should_skip_nonconcrete_strategy_action

    mp = build_perico_mission_prompt(user_text="fix login bug")
    action = {
        "title": "Prepare for potential code changes",
        "rationale": "",
        "action_type": "analysis",
        "params": {},
        "execution_mode": "auto_execute",
        "priority_score": 10,
    }
    assert perico_should_skip_nonconcrete_strategy_action(action, mission_prompt=mp) is True


def test_perico_should_skip_code_change_empty_patch_bugfix():
    from app.jarvis.perico_mission import perico_should_skip_nonconcrete_strategy_action

    mp = build_perico_mission_prompt(user_text="arregla integración webhook que falla")
    action = {
        "title": "Apply change",
        "action_type": "code_change",
        "params": {"relative_path": "x.py"},
        "execution_mode": "auto_execute",
        "priority_score": 10,
    }
    assert perico_should_skip_nonconcrete_strategy_action(action, mission_prompt=mp) is True


def test_perico_should_not_skip_concrete_perico_repo_read():
    from app.jarvis.perico_mission import perico_should_skip_nonconcrete_strategy_action

    mp = build_perico_mission_prompt(user_text="bug")
    action = {
        "title": "grep foo",
        "action_type": "perico_repo_read",
        "params": {"operation": "grep", "pattern": "foo"},
        "execution_mode": "auto_execute",
        "priority_score": 10,
    }
    assert perico_should_skip_nonconcrete_strategy_action(action, mission_prompt=mp) is False


def test_summarize_execution_for_operator_bugfix_prefers_perico_rows():
    from app.jarvis.notion_mission_readability import summarize_execution_for_operator

    mp = build_perico_mission_prompt(user_text="arregla tests rotos")
    ex = {
        "executed": [
            {
                "action_type": "analysis",
                "title": "Prepare for potential fix",
                "status": "skipped",
                "result": {"ok": False},
            },
            {
                "action_type": "perico_repo_read",
                "title": "Leer tests",
                "status": "executed",
                "result": {"ok": True},
            },
        ]
    }
    s = summarize_execution_for_operator(ex, mission_prompt=mp)
    assert "Prepare" not in s
    assert "Leer tests" in s or "Inspección" in s


def test_normalize_perico_maps_ops_config_read_to_repo_read_auto_execute():
    mp = build_perico_mission_prompt(user_text="revisa tests")
    acts = [
        {
            "title": "Read test configuration",
            "rationale": "Inspect pytest.ini before changes",
            "action_type": "ops_config_change",
            "params": {},
            "execution_mode": "requires_approval",
            "priority_score": 80,
            "impact": "medium",
            "confidence": 0.7,
        }
    ]
    out = normalize_perico_strategy_actions(acts, mission_prompt=mp)
    assert len(out) == 1
    assert out[0]["action_type"] == "perico_repo_read"
    assert out[0]["execution_mode"] == "auto_execute"
    assert out[0].get("requires_approval") is False


def test_normalize_perico_maps_run_full_pytest_to_perico_run_pytest():
    mp = build_perico_mission_prompt(user_text="fix tests")
    acts = [
        {
            "title": "Run full pytest suite",
            "rationale": "Validate after edits",
            "action_type": "code_change",
            "params": {},
            "execution_mode": "auto_execute",
            "priority_score": 70,
            "impact": "high",
            "confidence": 0.8,
        }
    ]
    out = normalize_perico_strategy_actions(acts, mission_prompt=mp)
    assert any(x.get("action_type") == "perico_run_pytest" for x in out)


def test_normalize_perico_maps_code_change_with_patch_to_apply_patch():
    mp = build_perico_mission_prompt(user_text="fix")
    acts = [
        {
            "title": "patch",
            "action_type": "code_change",
            "params": {"relative_path": "foo.py", "old_text": "a", "new_text": "b"},
            "execution_mode": "auto_execute",
            "priority_score": 70,
            "impact": "high",
            "confidence": 0.8,
        }
    ]
    out = normalize_perico_strategy_actions(acts, mission_prompt=mp)
    assert out[0]["action_type"] == "perico_apply_patch"
    assert out[0]["params"]["relative_path"] == "foo.py"


def test_normalize_perico_does_not_map_or_relax_mutating_ops_config():
    mp = build_perico_mission_prompt(user_text="x")
    acts = [
        {
            "title": "Write updated secrets to SSM",
            "rationale": "Rotate credentials and deploy",
            "action_type": "ops_config_change",
            "params": {},
            "execution_mode": "requires_approval",
            "priority_score": 90,
            "impact": "high",
            "confidence": 0.9,
        }
    ]
    out = normalize_perico_strategy_actions(acts, mission_prompt=mp)
    assert len(out) == 1
    assert out[0]["action_type"] == "ops_config_change"
    assert out[0]["execution_mode"] == "requires_approval"


def test_normalize_perico_non_software_prompt_returns_unchanged_shape():
    acts = [{"title": "x", "action_type": "ops_config_change", "params": {}, "execution_mode": "requires_approval"}]
    out = normalize_perico_strategy_actions(acts, mission_prompt="plain marketing text without perico wrapper")
    assert out[0]["action_type"] == "ops_config_change"


def test_review_agent_perico_bugfix_summary_uses_closure_token():
    from app.jarvis.autonomous_agents import ReviewAgent

    mp = build_perico_mission_prompt(user_text="fix parser bug pytest")
    plan = {"objective": "Corregir parser"}
    execution = {
        "executed": [
            {
                "action_type": "perico_repo_read",
                "result": {"ok": True, "operation": "read", "path": "/p.py", "content": "x"},
                "status": "executed",
            },
            {"action_type": "perico_apply_patch", "result": {"ok": True, "relative_path": "p.py"}, "status": "executed"},
            {
                "action_type": "perico_run_pytest",
                "result": {"ok": True, "pytest": True, "tests_ok": True},
                "status": "executed",
            },
        ],
        "needs_approval": False,
    }
    r = ReviewAgent().run(plan=plan, execution=execution, mission_prompt=mp)
    assert r.get("passed") is True
    assert "FIXED" in str(r.get("summary") or "")
    assert "Mission completed with safe actions" not in str(r.get("summary") or "")
