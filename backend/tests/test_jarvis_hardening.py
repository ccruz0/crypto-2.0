"""Focused tests for Jarvis hardening: validation, policy, executor, JSON extraction, API."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.jarvis.approval_storage import (
    APPROVAL_APPROVED,
    APPROVAL_PENDING,
    EXEC_EXECUTED,
    EXEC_FAILED,
    EXEC_NOT_EXECUTED,
    EXEC_READY,
    get_default_approval_storage,
    reset_default_approval_storage_for_tests,
)
from app.jarvis.bedrock_client import extract_planner_json_object
from app.jarvis.executor import execute_plan
from app.jarvis.memory import InMemoryJarvisMemory, reset_default_memory_for_tests
from app.jarvis.orchestrator import run_jarvis
from app.jarvis.plan_validation import PlanValidated, validate_plan_dict
from app.jarvis.planner import create_plan
from app.jarvis.tools import (
    ALL_JARVIS_ENVS,
    DEV_LAB_JARVIS_ENVS,
    TOOL_SPECS,
    ToolRiskLevel,
    get_tool_spec as get_tool_spec_unpatched,
)
from app.api.routes_jarvis import router as jarvis_router


@pytest.fixture(autouse=True)
def _clear_jarvis_memory():
    reset_default_memory_for_tests()
    reset_default_approval_storage_for_tests()
    yield


def test_validate_plan_dict_accepts_valid():
    raw = {"action": "echo_message", "args": {"message": "hi"}, "reasoning": "because"}
    m, err = validate_plan_dict(raw)
    assert err is None
    assert m is not None
    assert m.action == "echo_message"


def test_validate_plan_dict_rejects_extra_fields():
    raw = {"action": "echo_message", "args": {}, "reasoning": "", "confidence": 0.9}
    m, err = validate_plan_dict(raw)
    assert m is None
    assert err is not None


def test_extract_json_noisy_model_output():
    text = """Here is the plan:
```json
{"action": "get_server_time", "args": {}, "reasoning": "user asked"}
```
Hope this helps."""
    obj = extract_planner_json_object(text)
    assert obj is not None
    assert obj.get("action") == "get_server_time"


def test_extract_json_balanced_with_prose():
    text = 'Sure — {"action":"echo_message","args":{"message":"x"},"reasoning":"ok"} — done.'
    obj = extract_planner_json_object(text)
    assert obj is not None
    assert obj["action"] == "echo_message"


def test_execute_plan_safe_tool_success():
    r = execute_plan(
        {"action": "get_unix_time", "args": {}, "reasoning": "test"},
        jarvis_run_id="run-test-1",
    )
    assert "error" not in r
    assert "unix" in r
    assert "iso_utc" in r


def test_execute_unknown_tool():
    r = execute_plan({"action": "not_a_real_tool_ever", "args": {}, "reasoning": "x"})
    assert r.get("error") == "unknown_tool"


def test_execute_invalid_args():
    r = execute_plan(
        {
            "action": "get_server_time",
            "args": {"unexpected": True},
            "reasoning": "x",
        },
    )
    assert r.get("error") == "args_invalid"


def test_policy_denial_path(monkeypatch):
    monkeypatch.setattr(
        "app.jarvis.executor.EXECUTABLE_POLICIES",
        frozenset(),
    )
    r = execute_plan({"action": "get_server_time", "args": {}, "reasoning": "x"})
    assert r.get("error") == "policy_denied"
    assert r.get("policy") is not None


def test_approval_required_does_not_execute_send_test_notification():
    plan = {
        "action": "send_test_notification",
        "args": {"channel": "qa", "note": "hello"},
        "reasoning": "test approval path",
    }
    r = execute_plan(plan, jarvis_run_id="approval-run-1")
    assert r.get("status") == "approval_required"
    assert r.get("jarvis_run_id") == "approval-run-1"
    assert r.get("tool") == "send_test_notification"
    assert r.get("args") == {"channel": "qa", "note": "hello"}
    assert r.get("policy") == "approval_required"
    assert r.get("category") == "external_side_effect"
    assert "message" in r
    assert r.get("created_at")
    assert "T" in r["created_at"] or "+" in r["created_at"] or r["created_at"].endswith("Z")

    store = get_default_approval_storage()
    rec = store.get_by_run_id("approval-run-1")
    assert rec is not None
    assert rec["approval_status"] == APPROVAL_PENDING
    assert rec["execution_status"] == EXEC_NOT_EXECUTED
    assert rec["status"] == "pending"
    assert rec["tool"] == "send_test_notification"
    assert rec["args"] == {"channel": "qa", "note": "hello"}
    assert rec["policy"] == "approval_required"
    assert rec["category"] == "external_side_effect"
    assert rec["created_at"] == r["created_at"]
    assert rec.get("updated_at") is None
    assert rec.get("decision") is None
    assert rec.get("decision_reason") is None
    assert rec.get("risk_level") == "medium"
    assert rec.get("allowed_envs") == sorted(DEV_LAB_JARVIS_ENVS)


def test_approve_and_reject_transitions_and_idempotence():
    execute_plan(
        {
            "action": "send_test_notification",
            "args": {"channel": "c", "note": "n"},
            "reasoning": "r",
        },
        jarvis_run_id="flow-1",
    )
    approve = TOOL_SPECS["approve_pending_action"].fn
    reject = TOOL_SPECS["reject_pending_action"].fn

    a1 = approve(jarvis_run_id="flow-1", reason="ok")
    assert a1["status"] == "ok"
    assert a1["approval_status"] == "approved"
    assert a1["execution_status"] == EXEC_READY
    assert a1["decision"] == "approved"
    assert a1["decision_reason"] == "ok"
    assert a1["updated_at"]
    assert a1["created_at"]

    a2 = approve(jarvis_run_id="flow-1", reason="again")
    assert a2["status"] == "already_decided"
    assert a2["approval_status"] == "approved"
    assert a2["execution_status"] == EXEC_READY

    execute_plan(
        {
            "action": "send_test_notification",
            "args": {},
            "reasoning": "x",
        },
        jarvis_run_id="flow-2",
    )
    r1 = reject(jarvis_run_id="flow-2", reason="nope")
    assert r1["status"] == "ok"
    assert r1["approval_status"] == "rejected"
    assert r1["execution_status"] == EXEC_NOT_EXECUTED
    assert r1["decision"] == "rejected"
    assert r1["decision_reason"] == "nope"

    r2 = reject(jarvis_run_id="flow-2")
    assert r2["status"] == "already_decided"


def test_approve_reject_not_found():
    approve = TOOL_SPECS["approve_pending_action"].fn
    nf = approve(jarvis_run_id="does-not-exist")
    assert nf["status"] == "not_found"


def test_list_pending_excludes_decided_list_recent_includes_all():
    execute_plan(
        {"action": "send_test_notification", "args": {}, "reasoning": "a"},
        jarvis_run_id="p1",
    )
    execute_plan(
        {"action": "send_test_notification", "args": {}, "reasoning": "b"},
        jarvis_run_id="p2",
    )
    TOOL_SPECS["approve_pending_action"].fn(jarvis_run_id="p1")

    pending = TOOL_SPECS["list_pending_approvals"].fn(limit=20)
    assert pending["count"] == 1
    assert pending["approvals"][0]["jarvis_run_id"] == "p2"

    recent = TOOL_SPECS["list_recent_approvals"].fn(limit=20)
    ids = {x["jarvis_run_id"] for x in recent["approvals"]}
    assert ids == {"p1", "p2"}
    by_id = {x["jarvis_run_id"]: x for x in recent["approvals"]}
    assert by_id["p1"]["approval_status"] == "approved"
    assert by_id["p1"]["execution_status"] == EXEC_READY
    assert by_id["p2"]["approval_status"] == APPROVAL_PENDING
    assert by_id["p2"]["execution_status"] == EXEC_NOT_EXECUTED


def test_list_ready_for_execution_only_approved_and_ready():
    execute_plan(
        {"action": "send_test_notification", "args": {"channel": "a"}, "reasoning": "x"},
        jarvis_run_id="only-pending",
    )
    execute_plan(
        {"action": "send_test_notification", "args": {"channel": "b"}, "reasoning": "x"},
        jarvis_run_id="will-approve",
    )
    execute_plan(
        {"action": "send_test_notification", "args": {"channel": "c"}, "reasoning": "x"},
        jarvis_run_id="will-reject",
    )
    TOOL_SPECS["approve_pending_action"].fn(jarvis_run_id="will-approve")
    TOOL_SPECS["reject_pending_action"].fn(jarvis_run_id="will-reject", reason="no")

    ready = TOOL_SPECS["list_ready_for_execution"].fn(limit=20)
    assert ready["count"] == 1
    assert ready["approvals"][0]["jarvis_run_id"] == "will-approve"
    assert ready["approvals"][0]["approval_status"] == "approved"
    assert ready["approvals"][0]["execution_status"] == EXEC_READY


def test_get_approval_status_reflects_transition():
    execute_plan(
        {"action": "send_test_notification", "args": {}, "reasoning": "x"},
        jarvis_run_id="track-1",
    )
    get = TOOL_SPECS["get_approval_status"].fn
    g0 = get(jarvis_run_id="track-1")["approval"]
    assert g0["approval_status"] == APPROVAL_PENDING
    assert g0["execution_status"] == EXEC_NOT_EXECUTED

    TOOL_SPECS["reject_pending_action"].fn(jarvis_run_id="track-1", reason="no")
    g2 = get(jarvis_run_id="track-1")
    assert g2["approval"]["approval_status"] == "rejected"
    assert g2["approval"]["execution_status"] == EXEC_NOT_EXECUTED
    assert g2["approval"]["decision_reason"] == "no"
    assert g2["approval"].get("updated_at")


def test_list_pending_approvals_returns_stored_records():
    execute_plan(
        {
            "action": "send_test_notification",
            "args": {"channel": "c1", "note": "n1"},
            "reasoning": "r1",
        },
        jarvis_run_id="run-a",
    )
    execute_plan(
        {
            "action": "send_test_notification",
            "args": {"channel": "c2", "note": "n2"},
            "reasoning": "r2",
        },
        jarvis_run_id="run-b",
    )
    spec = TOOL_SPECS["list_pending_approvals"]
    out = spec.fn(limit=10)
    assert out["status"] == "ok"
    assert out["count"] == 2
    ids = {a["jarvis_run_id"] for a in out["approvals"]}
    assert ids == {"run-a", "run-b"}


def test_get_approval_status_found_and_not_found():
    execute_plan(
        {
            "action": "send_test_notification",
            "args": {},
            "reasoning": "x",
        },
        jarvis_run_id="exact-id-99",
    )
    spec = TOOL_SPECS["get_approval_status"]
    hit = spec.fn(jarvis_run_id="exact-id-99")
    assert hit["found"] is True
    assert hit["approval"]["jarvis_run_id"] == "exact-id-99"
    assert hit["approval"]["approval_status"] == APPROVAL_PENDING
    assert hit["approval"]["execution_status"] == EXEC_NOT_EXECUTED

    miss = spec.fn(jarvis_run_id="missing-id")
    assert miss["found"] is False
    assert miss["status"] == "not_found"
    assert miss["jarvis_run_id"] == "missing-id"


def test_restricted_tool_structured_denial():
    r = execute_plan(
        {
            "action": "restricted_operation_placeholder",
            "args": {},
            "reasoning": "x",
        },
        jarvis_run_id="restricted-1",
    )
    assert r.get("status") == "restricted"
    assert r.get("tool") == "restricted_operation_placeholder"
    assert r.get("policy") == "restricted"
    assert r.get("args") == {}


def test_list_available_tools_includes_category_and_policy():
    spec = TOOL_SPECS["list_available_tools"]
    out = spec.fn()
    tools = out["tools"]
    assert isinstance(tools, list)
    by_name = {t["name"]: t for t in tools}
    assert by_name["get_server_time"]["category"] == "read"
    assert by_name["get_server_time"]["policy"] == "safe"
    assert by_name["get_server_time"]["allow_deferred_execution"] is False
    assert by_name["send_test_notification"]["policy"] == "approval_required"
    assert by_name["send_test_notification"]["category"] == "external_side_effect"
    assert by_name["send_test_notification"]["allow_deferred_execution"] is True
    assert by_name["deferred_pipeline_blocked"]["allow_deferred_execution"] is False
    assert by_name["restricted_operation_placeholder"]["policy"] == "restricted"
    assert by_name["restricted_operation_placeholder"]["category"] == "trading"
    assert by_name["restricted_operation_placeholder"]["allow_deferred_execution"] is False
    assert by_name["echo_message"]["risk_level"] == "low"
    assert by_name["echo_message"]["allowed_envs"] == sorted(ALL_JARVIS_ENVS)
    assert by_name["send_test_notification"]["risk_level"] == "medium"
    assert by_name["send_test_notification"]["allowed_envs"] == sorted(DEV_LAB_JARVIS_ENVS)
    assert by_name["restricted_operation_placeholder"]["risk_level"] == "critical"
    assert "description" in by_name["echo_message"]


def test_execute_plan_safe_tool_environment_blocked(monkeypatch):
    monkeypatch.setenv("JARVIS_ENV", "prod")
    orig = TOOL_SPECS["get_unix_time"]
    monkeypatch.setitem(
        TOOL_SPECS,
        "get_unix_time",
        replace(orig, allowed_envs=frozenset({"dev", "lab"})),
    )
    r = execute_plan({"action": "get_unix_time", "args": {}, "reasoning": "x"})
    assert r.get("status") == "environment_not_allowed"
    assert r.get("tool") == "get_unix_time"
    assert r.get("current_env") == "prod"
    assert set(r.get("allowed_envs") or []) == {"dev", "lab"}


def test_approval_required_env_blocked_no_pending_record(monkeypatch):
    monkeypatch.setenv("JARVIS_ENV", "prod")
    r = execute_plan(
        {
            "action": "send_test_notification",
            "args": {},
            "reasoning": "x",
        },
        jarvis_run_id="no-pend-prod",
    )
    assert r.get("status") == "environment_not_allowed"
    assert get_default_approval_storage().get_by_run_id("no-pend-prod") is None


def test_execute_ready_env_blocked_leaves_record_unchanged(monkeypatch):
    monkeypatch.setenv("JARVIS_ENV", "dev")
    execute_plan(
        {
            "action": "send_test_notification",
            "args": {},
            "reasoning": "x",
        },
        jarvis_run_id="env-exec-1",
    )
    TOOL_SPECS["approve_pending_action"].fn(jarvis_run_id="env-exec-1")
    before = get_default_approval_storage().get_by_run_id("env-exec-1")
    assert before["execution_status"] == EXEC_READY

    monkeypatch.setenv("JARVIS_ENV", "prod")
    out = TOOL_SPECS["execute_ready_action"].fn(jarvis_run_id="env-exec-1")
    assert out.get("status") == "environment_not_allowed"
    assert out.get("jarvis_run_id") == "env-exec-1"

    after = get_default_approval_storage().get_by_run_id("env-exec-1")
    assert after["execution_status"] == EXEC_READY
    assert after.get("executed_at") is None
    assert after.get("execution_result") is None


def test_execute_ready_actor_required_for_high_critical_risk(monkeypatch):
    orig = TOOL_SPECS["send_test_notification"]
    monkeypatch.setitem(
        TOOL_SPECS,
        "send_test_notification",
        replace(orig, risk_level=ToolRiskLevel.HIGH),
    )
    monkeypatch.setenv("JARVIS_ENV", "dev")
    execute_plan(
        {"action": "send_test_notification", "args": {}, "reasoning": "x"},
        jarvis_run_id="actor-req-1",
    )
    TOOL_SPECS["approve_pending_action"].fn(jarvis_run_id="actor-req-1")

    no_actor = TOOL_SPECS["execute_ready_action"].fn(jarvis_run_id="actor-req-1")
    assert no_actor.get("status") == "actor_required"
    assert no_actor.get("risk_level") == "high"
    assert no_actor.get("tool") == "send_test_notification"

    rec = get_default_approval_storage().get_by_run_id("actor-req-1")
    assert rec["execution_status"] == EXEC_READY

    ok = TOOL_SPECS["execute_ready_action"].fn(jarvis_run_id="actor-req-1", actor="ops")
    assert ok.get("status") == "ok"
    assert ok.get("execution_status") == EXEC_EXECUTED


def test_execute_ready_medium_risk_does_not_require_actor(monkeypatch):
    """Default send_test_notification is medium; manual run without actor succeeds."""
    monkeypatch.setenv("JARVIS_ENV", "dev")
    execute_plan(
        {"action": "send_test_notification", "args": {}, "reasoning": "x"},
        jarvis_run_id="med-1",
    )
    TOOL_SPECS["approve_pending_action"].fn(jarvis_run_id="med-1")
    out = TOOL_SPECS["execute_ready_action"].fn(jarvis_run_id="med-1")
    assert out.get("status") == "ok"
    assert out.get("execution_status") == EXEC_EXECUTED


def test_planner_fallback_on_invalid_json(monkeypatch):
    monkeypatch.setattr("app.jarvis.planner.ask_bedrock", lambda prompt: "not json at all {{{")
    plan = create_plan("hello there", jarvis_run_id="fb-1")
    assert plan.get("action") == "echo_message"
    assert "fallback" in (plan.get("args") or {}).get("message", "")


def test_planner_valid_when_bedrock_returns_json(monkeypatch):
    monkeypatch.setattr(
        "app.jarvis.planner.ask_bedrock",
        lambda prompt: '{"action":"list_available_tools","args":{},"reasoning":"list"}',
    )
    plan = create_plan("what tools", jarvis_run_id="ok-1")
    assert plan.get("action") == "list_available_tools"
    assert validate_plan_dict(plan)[0] is not None


def test_jarvis_run_id_in_run_jarvis_response():
    with patch(
        "app.jarvis.orchestrator.create_plan",
        return_value=PlanValidated(
            action="get_unix_time",
            args={},
            reasoning="t",
        ).model_dump(),
    ):
        out = run_jarvis("time")
    assert "jarvis_run_id" in out
    assert len(out["jarvis_run_id"]) == 36


def test_run_jarvis_persists_approval_record():
    with patch(
        "app.jarvis.orchestrator.create_plan",
        return_value=PlanValidated(
            action="send_test_notification",
            args={"channel": "x", "note": "y"},
            reasoning="r",
        ).model_dump(),
    ):
        out = run_jarvis("notify please")
    res = out.get("result") or {}
    assert res.get("status") == "approval_required"
    rid = out["jarvis_run_id"]
    rec = get_default_approval_storage().get_by_run_id(rid)
    assert rec is not None
    assert rec["tool"] == "send_test_notification"
    assert rec["approval_status"] == APPROVAL_PENDING
    assert rec["execution_status"] == EXEC_NOT_EXECUTED


def test_jarvis_route_happy_path():
    app = FastAPI()
    app.include_router(jarvis_router)
    client = TestClient(app)
    with patch(
        "app.jarvis.orchestrator.create_plan",
        return_value=PlanValidated(
            action="get_server_status",
            args={},
            reasoning="test",
        ).model_dump(),
    ):
        r = client.post("/jarvis", json={"message": "status please"})
    assert r.status_code == 200
    body = r.json()
    assert body.get("input") == "status please"
    assert body.get("jarvis_run_id")
    assert body.get("plan", {}).get("action") == "get_server_status"
    res = body.get("result") or {}
    assert res.get("status") == "ok"
    assert res.get("component") == "jarvis"


def test_run_jarvis_with_custom_memory():
    mem = InMemoryJarvisMemory()
    with patch(
        "app.jarvis.orchestrator.create_plan",
        return_value=PlanValidated(
            action="echo_message",
            args={"message": "pong"},
            reasoning="t",
        ).model_dump(),
    ):
        out = run_jarvis("ping", memory=mem)
    assert out.get("jarvis_run_id")
    assert out["result"] == {"echo": "pong"}
    assert "ping" in mem.get_recent_context()


def test_execute_ready_action_success():
    execute_plan(
        {
            "action": "send_test_notification",
            "args": {"channel": "c1", "note": "n1"},
            "reasoning": "r",
        },
        jarvis_run_id="exec-ok-1",
    )
    TOOL_SPECS["approve_pending_action"].fn(jarvis_run_id="exec-ok-1")
    out = TOOL_SPECS["execute_ready_action"].fn(jarvis_run_id="exec-ok-1")
    assert out["status"] == "ok"
    assert out["execution_status"] == EXEC_EXECUTED
    assert out["executed_at"]
    assert out["execution_result"]["dry_run"] is True

    rec = get_default_approval_storage().get_by_run_id("exec-ok-1")
    assert rec["approval_status"] == APPROVAL_APPROVED
    assert rec["execution_status"] == EXEC_EXECUTED
    assert rec.get("execution_error") is None
    g = TOOL_SPECS["get_approval_status"].fn(jarvis_run_id="exec-ok-1")
    assert g["approval"]["execution_status"] == EXEC_EXECUTED
    assert g["approval"].get("executed_at")


def test_execute_ready_not_ready_wrong_execution_state():
    """Approved but execution_status not ``ready`` (e.g. only ``not_executed``)."""
    store = get_default_approval_storage()
    store.record_pending(
        {
            "jarvis_run_id": "weird-ex",
            "tool": "send_test_notification",
            "args": {},
            "policy": "approval_required",
            "category": "external_side_effect",
            "message": "x",
            "approval_status": APPROVAL_APPROVED,
            "execution_status": EXEC_NOT_EXECUTED,
            "status": APPROVAL_APPROVED,
            "created_at": "2020-01-01T00:00:00+00:00",
            "updated_at": None,
            "decision": None,
            "decision_reason": None,
            "executed_at": None,
            "execution_result": None,
            "execution_error": None,
        }
    )
    out = TOOL_SPECS["execute_ready_action"].fn(jarvis_run_id="weird-ex")
    assert out["status"] == "not_ready"
    assert out.get("current_execution_status") == EXEC_NOT_EXECUTED


def test_execute_ready_action_invoke_failure(monkeypatch):
    execute_plan(
        {"action": "send_test_notification", "args": {}, "reasoning": "x"},
        jarvis_run_id="exec-fail-1",
    )
    TOOL_SPECS["approve_pending_action"].fn(jarvis_run_id="exec-fail-1")
    monkeypatch.setattr(
        "app.jarvis.executor.invoke_registered_tool",
        lambda *a, **k: {"error": "tool_failed", "detail": "simulated boom"},
    )
    out = TOOL_SPECS["execute_ready_action"].fn(jarvis_run_id="exec-fail-1")
    assert out["status"] == "ok"
    assert out["execution_status"] == EXEC_FAILED
    assert "simulated" in (out.get("execution_error") or "")

    rec = get_default_approval_storage().get_by_run_id("exec-fail-1")
    assert rec["execution_status"] == EXEC_FAILED
    assert rec.get("execution_error")


def test_execute_ready_not_found():
    out = TOOL_SPECS["execute_ready_action"].fn(jarvis_run_id="missing-exec")
    assert out["status"] == "not_found"


def test_execute_ready_not_approved():
    execute_plan(
        {"action": "send_test_notification", "args": {}, "reasoning": "x"},
        jarvis_run_id="na-1",
    )
    out = TOOL_SPECS["execute_ready_action"].fn(jarvis_run_id="na-1")
    assert out["status"] == "not_approved"


def test_execute_ready_not_approved_when_rejected():
    execute_plan(
        {"action": "send_test_notification", "args": {}, "reasoning": "x"},
        jarvis_run_id="nr-1",
    )
    TOOL_SPECS["reject_pending_action"].fn(jarvis_run_id="nr-1")
    out = TOOL_SPECS["execute_ready_action"].fn(jarvis_run_id="nr-1")
    assert out["status"] == "not_approved"
    assert out.get("approval_status") == "rejected"


def test_execute_ready_not_approved_when_still_pending():
    execute_plan(
        {"action": "send_test_notification", "args": {}, "reasoning": "x"},
        jarvis_run_id="nr-2",
    )
    out = TOOL_SPECS["execute_ready_action"].fn(jarvis_run_id="nr-2")
    assert out["status"] == "not_approved"
    assert out.get("approval_status") == APPROVAL_PENDING


def test_execute_ready_already_executed():
    execute_plan(
        {"action": "send_test_notification", "args": {}, "reasoning": "x"},
        jarvis_run_id="ae-1",
    )
    TOOL_SPECS["approve_pending_action"].fn(jarvis_run_id="ae-1")
    ex = TOOL_SPECS["execute_ready_action"].fn
    assert ex(jarvis_run_id="ae-1")["execution_status"] == EXEC_EXECUTED
    again = ex(jarvis_run_id="ae-1")
    assert again["status"] == "already_executed"


def test_list_ready_excludes_after_execute():
    execute_plan(
        {"action": "send_test_notification", "args": {}, "reasoning": "x"},
        jarvis_run_id="lr-1",
    )
    TOOL_SPECS["approve_pending_action"].fn(jarvis_run_id="lr-1")
    assert TOOL_SPECS["list_ready_for_execution"].fn(limit=20)["count"] == 1
    TOOL_SPECS["execute_ready_action"].fn(jarvis_run_id="lr-1")
    assert TOOL_SPECS["list_ready_for_execution"].fn(limit=20)["count"] == 0


def test_approval_required_deferred_eligible_still_creates_pending():
    assert TOOL_SPECS["send_test_notification"].allow_deferred_execution is True
    r = execute_plan(
        {
            "action": "send_test_notification",
            "args": {"channel": "x", "note": "y"},
            "reasoning": "eligible",
        },
        jarvis_run_id="eligible-1",
    )
    assert r.get("status") == "approval_required"
    rec = get_default_approval_storage().get_by_run_id("eligible-1")
    assert rec is not None
    assert rec["approval_status"] == APPROVAL_PENDING


def test_approval_required_not_deferred_returns_denial_and_no_record():
    r = execute_plan(
        {
            "action": "deferred_pipeline_blocked",
            "args": {},
            "reasoning": "blocked",
        },
        jarvis_run_id="blocked-1",
    )
    assert r.get("status") == "deferred_execution_not_allowed"
    assert r.get("tool") == "deferred_pipeline_blocked"
    assert r.get("policy") == "approval_required"
    assert "message" in r
    assert get_default_approval_storage().get_by_run_id("blocked-1") is None


def test_execute_ready_when_tool_no_longer_deferred_eligible_noop(monkeypatch):
    execute_plan(
        {
            "action": "send_test_notification",
            "args": {},
            "reasoning": "x",
        },
        jarvis_run_id="revoke-1",
    )
    TOOL_SPECS["approve_pending_action"].fn(jarvis_run_id="revoke-1")
    before = get_default_approval_storage().get_by_run_id("revoke-1")
    assert before["execution_status"] == EXEC_READY

    def _patched_get(name: str):
        spec = get_tool_spec_unpatched(name)
        if (name or "").strip() == "send_test_notification" and spec is not None:
            return replace(spec, allow_deferred_execution=False)
        return spec

    monkeypatch.setattr("app.jarvis.tools.get_tool_spec", _patched_get)
    invoked: list[str] = []

    def _no_invoke(*a, **k):
        invoked.append("invoke")
        return {}

    monkeypatch.setattr("app.jarvis.executor.invoke_registered_tool", _no_invoke)
    out = TOOL_SPECS["execute_ready_action"].fn(jarvis_run_id="revoke-1")
    assert out["status"] == "deferred_execution_not_allowed"
    assert out.get("tool") == "send_test_notification"
    assert out.get("jarvis_run_id") == "revoke-1"
    assert invoked == []
    after = get_default_approval_storage().get_by_run_id("revoke-1")
    assert after == before


def test_attribution_actor_fields_stored():
    execute_plan(
        {"action": "send_test_notification", "args": {}, "reasoning": "x"},
        jarvis_run_id="attr-1",
    )
    approve = TOOL_SPECS["approve_pending_action"].fn
    reject = TOOL_SPECS["reject_pending_action"].fn
    execute = TOOL_SPECS["execute_ready_action"].fn

    approve(jarvis_run_id="attr-1", reason="go", actor="alice")
    rec = get_default_approval_storage().get_by_run_id("attr-1")
    assert rec.get("approved_by") == "alice"

    execute_plan(
        {"action": "send_test_notification", "args": {}, "reasoning": "x"},
        jarvis_run_id="attr-2",
    )
    reject(jarvis_run_id="attr-2", reason="no", actor="bob")
    r2 = get_default_approval_storage().get_by_run_id("attr-2")
    assert r2.get("rejected_by") == "bob"

    execute_plan(
        {"action": "send_test_notification", "args": {}, "reasoning": "x"},
        jarvis_run_id="attr-3",
    )
    approve(jarvis_run_id="attr-3", actor="carol")
    out = execute(jarvis_run_id="attr-3", actor="dave")
    assert out["status"] == "ok"
    r3 = get_default_approval_storage().get_by_run_id("attr-3")
    assert r3.get("executed_by") == "dave"

    g = TOOL_SPECS["get_approval_status"].fn(jarvis_run_id="attr-3")
    assert g["approval"].get("approved_by") == "carol"
    assert g["approval"].get("executed_by") == "dave"

    recent = TOOL_SPECS["list_recent_approvals"].fn(limit=20)["approvals"]
    by_id = {x["jarvis_run_id"]: x for x in recent}
    assert by_id["attr-1"].get("approved_by") == "alice"
    assert by_id["attr-2"].get("rejected_by") == "bob"

    ready = TOOL_SPECS["list_ready_for_execution"].fn(limit=20)["approvals"]
    assert not any(x["jarvis_run_id"] == "attr-3" for x in ready)
