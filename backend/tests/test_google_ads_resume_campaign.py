"""google_ads_resume_campaign: intent-only proposals, approval UX, post-approve execution (mocked)."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.jarvis.action_policy import get_action_policy
from app.jarvis.autonomous_agents import ExecutionAgent
from app.jarvis.autonomous_orchestrator import JarvisAutonomousOrchestrator
from app.jarvis.autonomous_orchestrator import _format_combined_approval_summary
from app.jarvis.autonomous_schemas import MISSION_STATUS_DONE, MISSION_STATUS_FAILED
from app.jarvis.google_ads_resume_proposals import (
    build_google_ads_resume_campaign_actions,
    format_google_ads_resume_approval_summary,
    google_ads_resume_mission_intent,
)

GOOGLE_ADS_RO_PROMPT = (
    "Analyze my Google Ads account for the last 30 days. Return top 10 campaigns by spend "
    "with impressions, clicks, CTR, conversions, cost, top issues, and top opportunities. Read-only only."
)


def test_policy_resume_requires_approval():
    pol = get_action_policy("google_ads_resume_campaign")
    assert pol.get("execution_mode") == "requires_approval"


def test_resume_intent_detection():
    assert google_ads_resume_mission_intent("Please resume campaign for spring sale")
    assert google_ads_resume_mission_intent("reactivar campaña de marca")
    assert google_ads_resume_mission_intent("reanudar campaña id 12")
    assert google_ads_resume_mission_intent("re-enable campaign after fix")
    assert google_ads_resume_mission_intent("unpause campaign 999")
    assert not google_ads_resume_mission_intent("Only analyze Google Ads last 30 days read-only")


def test_resume_proposal_only_with_intent_and_paused_row():
    diag = {
        "auth_ok": True,
        "campaign_fetch_ok": True,
        "analytics_top_campaigns": [
            {
                "campaign_id": 50,
                "name": "Frozen",
                "status": "PAUSED",
                "cost": "1.20",
                "impressions": 400,
                "clicks": 6,
                "ctr": "1.50%",
                "conversions": 0.0,
            }
        ],
    }
    assert build_google_ads_resume_campaign_actions(diag, "nothing") == []
    acts = build_google_ads_resume_campaign_actions(diag, f"{GOOGLE_ADS_RO_PROMPT}\nPlease resume campaign.")
    assert len(acts) == 1
    assert acts[0]["action_type"] == "google_ads_resume_campaign"
    assert acts[0]["params"]["current_status"] == "PAUSED"
    assert acts[0]["params"]["campaign_id"] == "50"


def test_resume_picks_hinted_campaign_id():
    diag = {
        "auth_ok": True,
        "campaign_fetch_ok": True,
        "analytics_top_campaigns": [
            {
                "campaign_id": 10,
                "name": "A",
                "status": "PAUSED",
                "cost": "2.00",
                "impressions": 100,
                "clicks": 2,
                "ctr": "2.00%",
                "conversions": 0.0,
            },
            {
                "campaign_id": 20,
                "name": "B",
                "status": "PAUSED",
                "cost": "5.00",
                "impressions": 200,
                "clicks": 4,
                "ctr": "2.00%",
                "conversions": 0.0,
            },
        ],
    }
    acts = build_google_ads_resume_campaign_actions(
        diag,
        f"{GOOGLE_ADS_RO_PROMPT}\nresume campaign id 20",
    )
    assert acts[0]["params"]["campaign_id"] == "20"


def test_format_resume_approval_summary():
    act = build_google_ads_resume_campaign_actions(
        {
            "auth_ok": True,
            "campaign_fetch_ok": True,
            "analytics_top_campaigns": [
                {
                    "campaign_id": 1,
                    "name": "Z",
                    "status": "PAUSED",
                    "cost": "2.00",
                    "impressions": 100,
                    "clicks": 2,
                    "ctr": "2.00%",
                    "conversions": 0.0,
                }
            ],
        },
        f"{GOOGLE_ADS_RO_PROMPT}\nresume campaign",
    )[0]
    text = format_google_ads_resume_approval_summary(act)
    assert "Reactivar campaña" in text and "PAUSED" in text
    assert "ENABLED" in text and "al instante" in text.lower()
    assert _format_combined_approval_summary([act]).startswith("Reactivar")


def test_execution_agent_queues_resume():
    pol = get_action_policy("google_ads_resume_campaign")
    ex = ExecutionAgent().run(
        strategy={
            "actions": [
                {
                    "title": "Reactivar",
                    "action_type": "google_ads_resume_campaign",
                    "params": {"campaign_id": "1", "campaign_name": "Z"},
                    "execution_mode": pol.get("execution_mode"),
                    "priority_score": 80,
                }
            ],
            "source": "test",
        },
        mission_prompt=GOOGLE_ADS_RO_PROMPT,
    )
    assert len(ex.get("waiting_for_approval") or []) == 1
    assert not any(x.get("action_type") == "google_ads_resume_campaign" for x in (ex.get("executed") or []))


def test_pause_precedence_over_resume_intent_same_mission():
    """Bad metrics → pause proposal; resume intent does not add a second mutation this cycle."""
    orch = JarvisAutonomousOrchestrator()
    prompt = f"{GOOGLE_ADS_RO_PROMPT}\nPlease resume campaign."
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
                            "campaign_id": 9001,
                            "name": "BadSpend",
                            "status": "ENABLED",
                            "cost": "20.00",
                            "impressions": 5000,
                            "clicks": 40,
                            "ctr": "0.80%",
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
        mission_id="m-priority",
        prompt=prompt,
        execution=execution,
    )
    wa = merged.get("waiting_for_approval") or []
    assert any(x.get("action_type") == "google_ads_pause_campaign" for x in wa)
    assert not any(x.get("action_type") == "google_ads_resume_campaign" for x in wa)


def test_merge_resume_after_no_pause_or_budget():
    orch = JarvisAutonomousOrchestrator()
    prompt = f"{GOOGLE_ADS_RO_PROMPT}\nPlease resume campaign."
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
                            "name": "Frozen",
                            "status": "PAUSED",
                            "cost": "1.50",
                            "impressions": 600,
                            "clicks": 8,
                            "ctr": "1.33%",
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
        mission_id="m-resume",
        prompt=prompt,
        execution=execution,
    )
    wa = merged.get("waiting_for_approval") or []
    assert any(x.get("action_type") == "google_ads_resume_campaign" for x in wa)


def test_continue_after_approval_resume_mock(monkeypatch):
    monkeypatch.setattr(
        "app.jarvis.autonomous_orchestrator.run_google_ads_resume_campaign",
        lambda _p: {"ok": True, "no_op": False, "campaign_name": "Gamma"},
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
                "title": "Reactivar",
                "action_type": "google_ads_resume_campaign",
                "params": {"campaign_id": "5", "campaign_name": "Gamma"},
            }
        ],
    )
    assert out["ok"] is True
    assert out["status"] == MISSION_STATUS_DONE
    assert "reactivada" in out["dialog_message"].lower()


def test_continue_after_approval_resume_no_op_mock(monkeypatch):
    monkeypatch.setattr(
        "app.jarvis.autonomous_orchestrator.run_google_ads_resume_campaign",
        lambda _p: {"ok": True, "no_op": True},
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
                "action_type": "google_ads_resume_campaign",
                "params": {"campaign_id": "1", "campaign_name": "X"},
            }
        ],
    )
    assert out["ok"] is True
    assert "enabled" in out["dialog_message"].lower() or "ya estaba" in out["dialog_message"].lower()


def test_continue_after_approval_resume_failure(monkeypatch):
    monkeypatch.setattr(
        "app.jarvis.autonomous_orchestrator.run_google_ads_resume_campaign",
        lambda _p: {"ok": False, "error_message": "not PAUSED"},
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
            {"action_type": "google_ads_resume_campaign", "params": {"campaign_id": "1", "campaign_name": "X"}}
        ],
    )
    assert out["ok"] is False
    assert out["status"] == MISSION_STATUS_FAILED
