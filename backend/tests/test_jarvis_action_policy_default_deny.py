"""Default-deny policy: unregistered Jarvis action types must not auto-execute."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.jarvis.action_policy import (
    ACTION_POLICY,
    MUTATING_ACTION_TYPES,
    UNREGISTERED_ACTION_POLICY,
    get_action_policy,
    is_registered_action_type,
    resolve_action_type,
)
from app.jarvis.autonomous_agents import StrategyAgent

_JARVIS_APP_ROOT = Path(__file__).resolve().parents[1] / "app" / "jarvis"

# action_type literals emitted by ExecutionAgent / orchestrator mutation paths.
_EXECUTION_AGENT_ACTION_TYPES = frozenset(
    {
        "analysis",
        "diagnose_google_ads_setup",
        "diagnose_ga4_setup",
        "diagnose_gsc_setup",
        "google_ads_pause_campaign",
        "google_ads_reduce_campaign_budget",
        "google_ads_resume_campaign",
        "inspect_container_env",
        "inspect_docker_mounts",
        "perico_apply_patch",
        "perico_repo_read",
        "perico_run_pytest",
        "verify_credentials_mount",
        "fix_credentials_path",
        "update_runtime_env",
        "restart_backend",
    }
)

_AUTO_EXECUTE_REGISTERED = frozenset(
    key
    for key, pol in ACTION_POLICY.items()
    if str(pol.get("execution_mode") or "").strip().lower() == "auto_execute"
)

_REQUIRES_APPROVAL_REGISTERED = frozenset(
    key
    for key, pol in ACTION_POLICY.items()
    if str(pol.get("execution_mode") or "").strip().lower() == "requires_approval"
)


def _literal_action_types_in_jarvis_modules() -> set[str]:
    """Collect action_type string literals from jarvis/*.py for registration checks."""
    found: set[str] = set()
    for path in _JARVIS_APP_ROOT.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key_node, val_node in zip(node.keys, node.values):
                if (
                    isinstance(key_node, ast.Constant)
                    and key_node.value == "action_type"
                    and isinstance(val_node, ast.Constant)
                    and isinstance(val_node.value, str)
                ):
                    val = val_node.value.strip().lower()
                    if val:
                        found.add(val)
    return found


def test_unregistered_action_type_requires_approval_not_auto_execute():
    pol = get_action_policy("totally_unknown_mutating_action")
    assert pol.get("execution_mode") == "requires_approval"
    assert pol.get("execution_mode") != "auto_execute"
    assert pol.get("registered") is False
    assert not is_registered_action_type("totally_unknown_mutating_action")


def test_unregistered_action_policy_is_not_analysis_fallback():
    pol = get_action_policy("brand_new_side_effect_action")
    analysis = ACTION_POLICY["analysis"]
    assert pol["execution_mode"] != analysis["execution_mode"]


@pytest.mark.parametrize("action_type", sorted(_AUTO_EXECUTE_REGISTERED))
def test_registered_auto_execute_types_still_auto_execute(action_type: str):
    pol = get_action_policy(action_type)
    assert pol.get("execution_mode") == "auto_execute"
    assert is_registered_action_type(action_type)


@pytest.mark.parametrize("action_type", sorted(_REQUIRES_APPROVAL_REGISTERED))
def test_registered_approval_types_still_require_approval(action_type: str):
    pol = get_action_policy(action_type)
    assert pol.get("execution_mode") == "requires_approval"


@pytest.mark.parametrize("action_type", sorted(MUTATING_ACTION_TYPES))
def test_known_mutating_action_types_are_registered(action_type: str):
    assert action_type in ACTION_POLICY, (
        f"Mutating action_type {action_type!r} must be registered in ACTION_POLICY "
        "(issue #607 default-deny)."
    )


def test_execution_agent_action_types_are_registered():
    missing = _EXECUTION_AGENT_ACTION_TYPES - set(ACTION_POLICY.keys())
    assert not missing, f"ExecutionAgent action types missing from ACTION_POLICY: {sorted(missing)}"


def test_resolve_action_type_preserves_unknown_explicit_hint():
    assert resolve_action_type("Do something risky", "brand_new_mutator") == "brand_new_mutator"
    assert get_action_policy("brand_new_mutator")["execution_mode"] == "requires_approval"


def test_resolve_action_type_still_maps_known_readonly_heuristics():
    assert resolve_action_type("Diagnose Google Ads setup for account", "") == "diagnose_google_ads_setup"
    assert resolve_action_type("Run analysis on metrics", "") == "research"


def test_strategy_agent_unknown_action_type_gets_requires_approval(monkeypatch):
    monkeypatch.setattr(
        "app.jarvis.autonomous_agents.ask_bedrock_json",
        lambda *a, **k: {
            "actions": [
                {
                    "title": "Apply unregistered side effect",
                    "action_type": "unregistered_side_effect_v607",
                    "impact": "high",
                    "confidence": 0.9,
                }
            ]
        },
    )
    out = StrategyAgent().run(
        prompt="Review marketing data",
        plan={"objective": "review"},
        research={"findings": [], "confidence": 0.8},
    )
    actions = out.get("actions") or []
    assert len(actions) == 1
    assert actions[0]["action_type"] == "unregistered_side_effect_v607"
    assert actions[0]["execution_mode"] == "requires_approval"
    assert actions[0]["requires_approval"] is True


def test_jarvis_module_action_type_literals_are_registered_or_default_deny():
    """Fail when a new action_type literal is added under jarvis/ without ACTION_POLICY entry."""
    literals = _literal_action_types_in_jarvis_modules()
    # Marketing proposal types are operator suggestions, not ExecutionAgent mutations.
    marketing_only = {
        "improve_seo_snippet",
        "improve_meta_description",
        "improve_page_title",
        "pause_or_reduce_budget",
        "review_campaign_targeting",
        "add_negative_keywords",
        "improve_landing_page_cta",
        "review_page_message_match",
        "improve_booking_flow",
        "configure_ga4_booking_event",
        "connect_data_source",
    }
    execution_literals = literals - marketing_only
    unregistered = {t for t in execution_literals if t not in ACTION_POLICY}
    assert not unregistered, (
        "Jarvis modules reference action_type literals not in ACTION_POLICY; "
        f"register them or they will default to requires_approval: {sorted(unregistered)}"
    )


def test_unregistered_policy_constant_matches_get_action_policy():
    assert UNREGISTERED_ACTION_POLICY["execution_mode"] == "requires_approval"
