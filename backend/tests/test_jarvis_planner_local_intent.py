"""Tests for pre-Bedrock local intent routing in ``create_plan``."""

from __future__ import annotations

import pytest

from app.jarvis.planner import create_plan


@pytest.fixture
def assert_bedrock_not_called(monkeypatch):
    def _fail(*_a, **_k):
        raise AssertionError("ask_bedrock must not be called for local direct intents")

    monkeypatch.setattr("app.jarvis.planner.ask_bedrock", _fail)
    yield


def test_jarvis_list_tools_routes_to_list_available_tools(assert_bedrock_not_called):
    out = create_plan("/jarvis list tools", jarvis_run_id="run-a")
    assert out["action"] == "list_available_tools"
    assert out["args"] == {}
    assert "local_intent" in (out.get("reasoning") or "")


def test_list_tools_routes_to_list_available_tools(assert_bedrock_not_called):
    out = create_plan("LIST TOOLS", jarvis_run_id="run-b")
    assert out["action"] == "list_available_tools"


def test_pending_routes_to_list_pending_approvals(assert_bedrock_not_called):
    out = create_plan("pending", jarvis_run_id="run-c")
    assert out["action"] == "list_pending_approvals"


def test_ready_for_execution_routes(assert_bedrock_not_called):
    out = create_plan("ready for execution", jarvis_run_id="run-d")
    assert out["action"] == "list_ready_for_execution"


def test_unrelated_text_uses_bedrock(monkeypatch):
    calls: list[str] = []

    def fake_ask(prompt: str) -> str:
        calls.append(prompt)
        return '{"action":"get_unix_time","args":{},"reasoning":"from bedrock"}'

    monkeypatch.setattr("app.jarvis.planner.ask_bedrock", fake_ask)
    out = create_plan("completely unrelated query about zebras and clocks", jarvis_run_id="run-e")
    assert calls, "Bedrock should be consulted when no local intent matches"
    assert out["action"] == "get_unix_time"


def test_partial_phrase_does_not_match_local_intent(monkeypatch):
    calls: list[int] = []

    def fake_ask(_prompt: str) -> str:
        calls.append(1)
        return '{"action":"echo_message","args":{"message":"x"},"reasoning":"t"}'

    monkeypatch.setattr("app.jarvis.planner.ask_bedrock", fake_ask)
    out = create_plan("please list tools for me later", jarvis_run_id="run-f")
    assert calls
    assert out["action"] == "echo_message"
