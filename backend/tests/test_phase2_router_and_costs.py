"""Phase 2 unit tests: model router (P2-R2) and cost tracker (P2-R4)."""

from __future__ import annotations

import json

from app.jarvis import cost_tracker
from app.jarvis.model_router import (
    DEFAULT_MODELS,
    LEGACY_DEFAULT_MODEL_ID,
    fallback_chain,
    resolve_model,
)


def _clear_router_env(monkeypatch):
    for var in (
        "JARVIS_BEDROCK_MODEL_ID",
        "JARVIS_MODEL_ROUTER_ENABLED",
        "JARVIS_MODEL_SIMPLE",
        "JARVIS_MODEL_STANDARD",
        "JARVIS_MODEL_CRITICAL",
    ):
        monkeypatch.delenv(var, raising=False)


def test_router_defaults_by_tier(monkeypatch):
    _clear_router_env(monkeypatch)
    assert resolve_model("simple") == DEFAULT_MODELS["simple"]
    assert resolve_model("standard") == DEFAULT_MODELS["standard"]
    assert resolve_model("critical") == DEFAULT_MODELS["critical"]
    # Unknown/empty tier resolves to standard — safe default.
    assert resolve_model(None) == DEFAULT_MODELS["standard"]
    assert resolve_model("weird") == DEFAULT_MODELS["standard"]


def test_router_global_pin_wins_over_everything(monkeypatch):
    _clear_router_env(monkeypatch)
    monkeypatch.setenv("JARVIS_BEDROCK_MODEL_ID", "my.pinned.model")
    monkeypatch.setenv("JARVIS_MODEL_SIMPLE", "should.not.be.used")
    assert resolve_model("simple") == "my.pinned.model"
    assert fallback_chain("simple") == ["my.pinned.model"]


def test_router_disabled_falls_back_to_legacy_default(monkeypatch):
    _clear_router_env(monkeypatch)
    monkeypatch.setenv("JARVIS_MODEL_ROUTER_ENABLED", "false")
    assert resolve_model("simple") == LEGACY_DEFAULT_MODEL_ID
    assert fallback_chain("critical") == [LEGACY_DEFAULT_MODEL_ID]


def test_router_per_tier_env_override(monkeypatch):
    _clear_router_env(monkeypatch)
    monkeypatch.setenv("JARVIS_MODEL_SIMPLE", "custom.haiku.build")
    assert resolve_model("simple") == "custom.haiku.build"
    assert resolve_model("standard") == DEFAULT_MODELS["standard"]


def test_router_fallback_chain_escalates_one_tier(monkeypatch):
    _clear_router_env(monkeypatch)
    chain = fallback_chain("simple")
    assert chain == [DEFAULT_MODELS["simple"], DEFAULT_MODELS["standard"]]
    # Critical has nowhere to escalate.
    assert fallback_chain("critical") == [DEFAULT_MODELS["critical"]]


def test_cost_tracker_records_per_agent_and_mission(tmp_path, monkeypatch):
    log = tmp_path / "costs.jsonl"
    monkeypatch.setenv("JARVIS_COST_LOG", str(log))
    cost_tracker.reset_summary()

    rec = cost_tracker.record_usage(
        model_id="anthropic.claude-3-haiku-20240307-v1:0",
        input_tokens=1000,
        output_tokens=500,
        task="simple",
        agent="planner",
        mission_id="m-1",
    )
    assert rec is not None
    assert rec["cost_usd"] > 0

    cost_tracker.record_usage(
        model_id="anthropic.claude-3-sonnet-20240229-v1:0",
        input_tokens=2000,
        output_tokens=1000,
        task="standard",
        agent="strategy",
        mission_id="m-1",
    )

    summary = cost_tracker.get_summary()
    assert summary["records"] == 2
    assert summary["input_tokens"] == 3000
    assert summary["output_tokens"] == 1500
    assert set(summary["by_agent"]) == {"planner", "strategy"}
    assert summary["by_mission"]["m-1"]["calls"] == 2

    lines = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(lines) == 2
    assert lines[0]["agent"] == "planner"
    assert lines[1]["mission_id"] == "m-1"


def test_cost_tracker_haiku_vs_sonnet_saving_exceeds_committed_range():
    """P2-R3 anchor: identical tokens, classification tier — saving above 60-80%."""
    tokens_in, tokens_out = 1000, 1000
    haiku = cost_tracker.estimate_cost_usd("anthropic.claude-3-haiku-20240307-v1:0", tokens_in, tokens_out)
    sonnet = cost_tracker.estimate_cost_usd("anthropic.claude-3-sonnet-20240229-v1:0", tokens_in, tokens_out)
    saving = 1 - (haiku / sonnet)
    assert saving > 0.80, f"expected >80% saving, got {saving:.1%}"


def test_cost_tracker_never_raises_on_bad_log_path(monkeypatch):
    monkeypatch.setenv("JARVIS_COST_LOG", "/proc/definitely/not/writable/costs.jsonl")
    cost_tracker.reset_summary()
    rec = cost_tracker.record_usage(
        model_id="anthropic.claude-3-haiku-20240307-v1:0",
        input_tokens=10,
        output_tokens=10,
        task="simple",
        agent="x",
    )
    # In-memory accounting still succeeds even when the log path is unwritable.
    assert rec is not None
    assert cost_tracker.get_summary()["records"] == 1
