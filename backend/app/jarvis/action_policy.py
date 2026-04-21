"""Central action policy for autonomous Jarvis strategy/execution."""

from __future__ import annotations

from typing import Any

# Single source of truth: update this map to change behavior globally.
ACTION_POLICY: dict[str, dict[str, Any]] = {
    "analysis": {
        "execution_mode": "auto_execute",
        "base_priority_score": 45,
        "impact_default": "medium",
    },
    "research": {
        "execution_mode": "auto_execute",
        "base_priority_score": 50,
        "impact_default": "medium",
    },
    "code_change": {
        "execution_mode": "auto_execute",
        "base_priority_score": 65,
        "impact_default": "high",
    },
    "ops_config_change": {
        "execution_mode": "requires_approval",
        "base_priority_score": 78,
        "impact_default": "high",
    },
    "deploy": {
        "execution_mode": "requires_approval",
        "base_priority_score": 90,
        "impact_default": "high",
    },
    "external_side_effect": {
        "execution_mode": "requires_approval",
        "base_priority_score": 82,
        "impact_default": "high",
    },
    "user_input": {
        "execution_mode": "requires_input",
        "base_priority_score": 55,
        "impact_default": "medium",
    },
    "inspect_docker_mounts": {
        "execution_mode": "auto_execute",
        "base_priority_score": 60,
        "impact_default": "medium",
    },
    "inspect_container_env": {
        "execution_mode": "auto_execute",
        "base_priority_score": 60,
        "impact_default": "medium",
    },
    "verify_credentials_mount": {
        "execution_mode": "auto_execute",
        "base_priority_score": 66,
        "impact_default": "medium",
    },
    "diagnose_google_ads_setup": {
        "execution_mode": "auto_execute",
        "base_priority_score": 72,
        "impact_default": "high",
    },
    "diagnose_ga4_setup": {
        "execution_mode": "auto_execute",
        "base_priority_score": 70,
        "impact_default": "high",
    },
    "diagnose_gsc_setup": {
        "execution_mode": "auto_execute",
        "base_priority_score": 70,
        "impact_default": "high",
    },
    "perico_repo_read": {
        "execution_mode": "auto_execute",
        "base_priority_score": 72,
        "impact_default": "high",
    },
    "perico_run_pytest": {
        "execution_mode": "auto_execute",
        "base_priority_score": 76,
        "impact_default": "high",
    },
    "perico_apply_patch": {
        "execution_mode": "auto_execute",
        "base_priority_score": 80,
        "impact_default": "high",
    },
    "fix_credentials_path": {
        "execution_mode": "requires_approval",
        "base_priority_score": 86,
        "impact_default": "high",
    },
    "update_runtime_env": {
        "execution_mode": "requires_approval",
        "base_priority_score": 88,
        "impact_default": "high",
    },
    "restart_backend": {
        "execution_mode": "requires_approval",
        "base_priority_score": 90,
        "impact_default": "high",
    },
}

DEFAULT_ACTION_TYPE = "analysis"
DEFAULT_EXECUTION_MODE = "auto_execute"

_IMPACT_WEIGHT: dict[str, int] = {"low": 0, "medium": 8, "high": 16}


def get_action_policy(action_type: str) -> dict[str, Any]:
    """Return effective policy for an action type."""
    key = (action_type or "").strip().lower()
    return ACTION_POLICY.get(key, ACTION_POLICY[DEFAULT_ACTION_TYPE])


def resolve_action_type(title: str, model_hint: str = "") -> str:
    """Infer action type from title/hint when model does not provide a known one."""
    hint = (model_hint or "").strip().lower()
    if hint in ACTION_POLICY:
        return hint
    text = f"{title} {hint}".lower()
    if any(k in text for k in ("deploy", "release", "rollout")):
        return "deploy"
    if "google ads" in text and "diagnos" in text:
        return "diagnose_google_ads_setup"
    if any(k in text for k in ("google analytics", "ga4")) and "diagnos" in text:
        return "diagnose_ga4_setup"
    if any(k in text for k in ("search console", "gsc")) and "diagnos" in text:
        return "diagnose_gsc_setup"
    if any(k in text for k in ("inspect mount", "docker mount", "container mount")):
        return "inspect_docker_mounts"
    if any(k in text for k in ("inspect env", "container env")):
        return "inspect_container_env"
    if any(k in text for k in ("credentials mount", "verify credentials")):
        return "verify_credentials_mount"
    if any(k in text for k in ("fix credentials path", "move credentials")):
        return "fix_credentials_path"
    if any(k in text for k in ("update runtime env", "write runtime env")):
        return "update_runtime_env"
    if "restart backend" in text:
        return "restart_backend"
    if any(k in text for k in ("secret", "credential", "ssm", "env", "config")):
        return "ops_config_change"
    if any(k in text for k in ("api call", "webhook", "send", "post")):
        return "external_side_effect"
    if any(k in text for k in ("input", "clarify", "ask user", "missing context")):
        return "user_input"
    if any(k in text for k in ("code", "refactor", "patch", "test")):
        return "code_change"
    if any(k in text for k in ("research", "investigate", "analyze", "analysis")):
        return "research"
    return DEFAULT_ACTION_TYPE


def compute_priority_score(*, action_type: str, impact: str, confidence: float) -> int:
    """Compute a bounded priority score from policy + impact + confidence."""
    policy = get_action_policy(action_type)
    base = int(policy.get("base_priority_score", 40) or 40)
    imp = (impact or "").strip().lower()
    impact_weight = _IMPACT_WEIGHT.get(imp, _IMPACT_WEIGHT["medium"])
    conf = max(0.0, min(1.0, float(confidence)))
    confidence_weight = int(round(conf * 12))
    return max(0, min(100, base + impact_weight + confidence_weight))

