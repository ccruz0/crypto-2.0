"""Google Ads pause campaign: proposals, approval queue, post-approve execution (mocked API)."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.jarvis.autonomous_agents import ExecutionAgent, StrategyAgent
from app.jarvis.autonomous_orchestrator import JarvisAutonomousOrchestrator
from app.jarvis.autonomous_schemas import MISSION_STATUS_DONE, MISSION_STATUS_FAILED
from app.jarvis.autonomous_orchestrator import _format_combined_approval_summary
from app.jarvis.google_ads_pause_proposals import (
    build_google_ads_pause_campaign_actions,
    extract_google_ads_readonly_diagnostic_result,
    format_google_ads_pause_approval_summary,
)
from app.jarvis.action_policy import get_action_policy

GOOGLE_ADS_RO_PROMPT = (
    "Analyze my Google Ads account for the last 30 days. Return top 10 campaigns by spend "
    "with impressions, clicks, CTR, conversions, cost, top issues, and top opportunities. Read-only only."
)


def test_action_policy_google_ads_pause_requires_approval():
    pol = get_action_policy("google_ads_pause_campaign")
    assert pol.get("execution_mode") == "requires_approval"


def test_strategy_proposes_pause_from_high_cost_zero_conversions():
    diag = {
        "auth_ok": True,
        "campaign_fetch_ok": True,
        "analytics_top_campaigns": [
            {
                "campaign_id": 9001,
                "name": "Waste",
                "status": "ENABLED",
                "cost": "12.00",
                "impressions": 5000,
                "clicks": 40,
                "ctr": "0.80%",
                "conversions": 0.0,
            }
        ],
    }
    actions = StrategyAgent.propose_google_ads_pause_from_readonly_diagnostic(diag)
    assert len(actions) == 1
    a = actions[0]
    assert a["action_type"] == "google_ads_pause_campaign"
    assert a["execution_mode"] == "requires_approval"
    assert a["requires_approval"] is True
    assert a["params"]["campaign_id"] == "9001"
    assert "Waste" in a["params"]["campaign_name"]
    assert a["params"]["cost"] == "12.00"
    assert a["params"]["conversions"] == 0.0
    assert a["params"]["ctr"] == "0.80%"
    assert a["params"]["rule_key"] == "high_cost_zero_conversions"
    assert "Gasto ≥" in a["params"]["trigger_rule"]
    assert a["params"]["expected_benefit"]


def test_format_pause_approval_summary_lists_metrics_rule_and_benefit():
    actions = build_google_ads_pause_campaign_actions(
        {
            "auth_ok": True,
            "campaign_fetch_ok": True,
            "analytics_top_campaigns": [
                {
                    "campaign_id": 9001,
                    "name": "Waste",
                    "status": "ENABLED",
                    "cost": "12.00",
                    "impressions": 5000,
                    "clicks": 40,
                    "ctr": "0.80%",
                    "conversions": 0.0,
                }
            ],
        }
    )
    text = format_google_ads_pause_approval_summary(actions[0])
    assert "Waste" in text and "9001" in text
    assert "12.00" in text and "0.80%" in text
    assert "• Regla:" in text
    assert "• Motivo:" in text
    assert "• Beneficio esperado:" in text


def test_combined_approval_summary_uses_pause_formatter():
    actions = build_google_ads_pause_campaign_actions(
        {
            "auth_ok": True,
            "campaign_fetch_ok": True,
            "analytics_top_campaigns": [
                {
                    "campaign_id": 7,
                    "name": "Z",
                    "status": "ENABLED",
                    "cost": "20.00",
                    "impressions": 6000,
                    "clicks": 50,
                    "ctr": "0.83%",
                    "conversions": 0.0,
                }
            ],
        }
    )
    s = _format_combined_approval_summary(actions)
    assert "Pausa propuesta" in s and "id 7" in s and "Regla" in s


def test_proposal_low_ctr_path_single_campaign():
    diag = {
        "auth_ok": True,
        "analytics_top_campaigns": [
            {
                "campaign_id": 42,
                "name": "LowCTR",
                "status": "ENABLED",
                "cost": "2.00",
                "impressions": 2000,
                "clicks": 4,
                "ctr": "0.20%",
                "conversions": 2.0,
            }
        ],
    }
    actions = build_google_ads_pause_campaign_actions(diag)
    assert len(actions) == 1
    assert actions[0]["params"]["campaign_id"] == "42"
    assert actions[0]["params"]["rule_key"] == "low_ctr_threshold"
    assert "CTR" in actions[0]["params"]["trigger_rule"]


def test_skips_paused_campaign_status():
    diag = {
        "auth_ok": True,
        "analytics_top_campaigns": [
            {
                "campaign_id": 1,
                "name": "Already",
                "status": "PAUSED",
                "cost": "99.00",
                "impressions": 100,
                "clicks": 1,
                "ctr": "1.00%",
                "conversions": 0.0,
            }
        ],
    }
    assert build_google_ads_pause_campaign_actions(diag) == []


def test_execution_agent_queues_pause_never_auto_executes():
    policy = get_action_policy("google_ads_pause_campaign")
    ex = ExecutionAgent().run(
        strategy={
            "actions": [
                {
                    "title": "Pausar campaña X",
                    "action_type": "google_ads_pause_campaign",
                    "params": {"campaign_id": "1", "campaign_name": "X", "reason": "test"},
                    "execution_mode": policy.get("execution_mode"),
                    "priority_score": 80,
                }
            ],
            "source": "test",
        },
        mission_prompt=GOOGLE_ADS_RO_PROMPT,
    )
    assert not any(x.get("action_type") == "google_ads_pause_campaign" for x in (ex.get("executed") or []))
    assert len(ex.get("waiting_for_approval") or []) == 1
    assert ex["needs_approval"] is True


def test_extract_diagnostic_result_from_execution():
    execution = {
        "executed": [
            {
                "action_type": "diagnose_google_ads_setup",
                "result": {"auth_ok": True, "campaign_fetch_ok": True, "analytics_top_campaigns": [{"name": "A"}]},
            }
        ]
    }
    d = extract_google_ads_readonly_diagnostic_result(execution)
    assert d is not None
    assert d["analytics_top_campaigns"]


def test_merge_orchestrator_adds_waiting_for_approval(monkeypatch):
    orch = JarvisAutonomousOrchestrator()
    mission_id = "test-mission-id"
    execution = {
        "executed": [
            {
                "action_type": "diagnose_google_ads_setup",
                "status": "executed",
                "result": {
                    "auth_ok": True,
                    "campaign_fetch_ok": True,
                    "analytics_top_campaigns": [
                        {
                            "campaign_id": 77,
                            "name": "Waste",
                            "status": "ENABLED",
                            "cost": "10.00",
                            "impressions": 3000,
                            "clicks": 20,
                            "ctr": "0.67%",
                            "conversions": 0.0,
                        }
                    ],
                },
            }
        ],
        "waiting_for_approval": [],
        "waiting_for_input": [],
        "needs_approval": False,
    }
    merged = orch._merge_google_ads_mutation_proposals(
        mission_id=mission_id,
        prompt=GOOGLE_ADS_RO_PROMPT,
        execution=execution,
    )
    assert merged["waiting_for_approval"]
    assert merged["needs_approval"] is True


def test_continue_after_approval_runs_pause_mock(monkeypatch):
    calls: list[dict] = []

    def _fake_pause(params: dict):
        calls.append(params)
        return {"ok": True, "campaign_id": params.get("campaign_id")}

    monkeypatch.setattr(
        "app.jarvis.autonomous_orchestrator.run_google_ads_pause_campaign",
        _fake_pause,
    )
    notion = MagicMock()
    notion.get_mission.return_value = {"mission_id": "mid", "status": "waiting_for_approval"}
    telegram = MagicMock()
    orch = JarvisAutonomousOrchestrator(notion=notion, telegram=telegram)
    pending = [
        {
            "title": "Pausar",
            "action_type": "google_ads_pause_campaign",
            "params": {"campaign_id": "123", "campaign_name": "Alpha"},
        }
    ]
    out = orch.continue_after_approval(
        mission_id="mid",
        approved=True,
        actor="u1",
        chat_id="c1",
        pending_actions=pending,
    )
    assert out["ok"] is True
    assert out["status"] == MISSION_STATUS_DONE
    assert "pausada correctamente" in out["dialog_message"].lower()
    assert calls and calls[0].get("campaign_id") == "123"
    telegram.send_message.assert_called()
    args = telegram.send_message.call_args[0]
    assert "Alpha" in args[1] and "pausada correctamente" in args[1]


def test_continue_after_approval_failure_path(monkeypatch):
    monkeypatch.setattr(
        "app.jarvis.autonomous_orchestrator.run_google_ads_pause_campaign",
        lambda _p: {"ok": False, "error_message": "mutate failed"},
    )
    notion = MagicMock()
    notion.get_mission.return_value = {"mission_id": "mid", "status": "waiting_for_approval"}
    telegram = MagicMock()
    orch = JarvisAutonomousOrchestrator(notion=notion, telegram=telegram)
    out = orch.continue_after_approval(
        mission_id="mid",
        approved=True,
        actor="u1",
        chat_id="c1",
        pending_actions=[
            {
                "action_type": "google_ads_pause_campaign",
                "params": {"campaign_id": "1", "campaign_name": "Beta"},
            }
        ],
    )
    assert out["ok"] is False
    assert out["status"] == MISSION_STATUS_FAILED
