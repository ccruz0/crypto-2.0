"""
Lightweight human approval gate for agent task execution.

Distinguishes:
- low-risk callbacks (documentation, monitoring triage) that may run automatically
- higher-risk callbacks or tasks that require explicit approval before execution

No user-specific approval logic is stored here; callers pass approved=True/False.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Keywords in task title or details that force approval-required (case-insensitive)
HIGH_RISK_KEYWORDS = (
    "trade",
    "trading",
    "order",
    "exchange",
    "execution",
    "deploy",
    "restart",
    "nginx",
    "docker-compose",
    "crypto.com",
    "signal",
    "strategy",
    "telegram_commands",
)

# Inferred repo area names or matched_rules that force approval-required
HIGH_RISK_AREA_KEYWORDS = (
    "trading",
    "exchange",
    "order",
    "orders",
    "market execution",
    "telegram",
    "notifications",
    "infrastructure",
    "deploy",
    "strategy",
    "signal",
)


def _task_text(prepared_task: dict[str, Any]) -> str:
    """Concatenate task title and details for keyword scanning."""
    task = (prepared_task or {}).get("task") or {}
    title = str(task.get("task") or "")
    details = str(task.get("details") or "")
    return f"{title} {details}".lower()


def _repo_area_text(prepared_task: dict[str, Any]) -> str:
    """Concatenate inferred area name and matched rules for keyword scanning."""
    repo_area = (prepared_task or {}).get("repo_area") or {}
    name = str(repo_area.get("area_name") or "")
    rules = " ".join(str(r) for r in (repo_area.get("matched_rules") or []))
    return f"{name} {rules}".lower()


def _has_high_risk_keywords(prepared_task: dict[str, Any]) -> bool:
    """True if task title/details contain any HIGH_RISK_KEYWORDS."""
    text = _task_text(prepared_task)
    return any(kw in text for kw in HIGH_RISK_KEYWORDS)


def _has_high_risk_area(prepared_task: dict[str, Any]) -> bool:
    """True if inferred repo area suggests trading/order/runtime/deploy."""
    text = _repo_area_text(prepared_task)
    return any(kw in text for kw in HIGH_RISK_AREA_KEYWORDS)


def _is_known_safe_callback(callback_selection: dict[str, Any]) -> bool:
    """
    True if the selected callback pack is a known low-risk one (documentation or monitoring triage).
    Uses selection_reason to avoid importing agent_callbacks.
    """
    reason = str((callback_selection or {}).get("selection_reason") or "")
    reason_lower = reason.lower()
    return (
        "documentation" in reason_lower
        or "monitoring" in reason_lower
        or "triage" in reason_lower
    )


def _has_apply_callback(callback_selection: dict[str, Any]) -> bool:
    """True if an apply callback was selected."""
    return (callback_selection or {}).get("apply_change_fn") is not None


def requires_human_approval(
    prepared_task: dict[str, Any],
    callback_selection: dict[str, Any],
) -> dict[str, Any]:
    """
    Determine whether this task/callback combination requires explicit human approval before execution.

    Returns:
        {
            "required": True | False,
            "reason": "...",
            "risk_level": "low" | "medium" | "high"
        }
    """
    if not prepared_task:
        return {
            "required": True,
            "reason": "no prepared task",
            "risk_level": "high",
        }

    # No callback selected -> do not auto-execute
    if not _has_apply_callback(callback_selection):
        return {
            "required": True,
            "reason": "no known safe callback selected; execution would be skipped or unspecified",
            "risk_level": "medium",
        }

    # High-risk content in task or area -> always require approval
    if _has_high_risk_keywords(prepared_task):
        return {
            "required": True,
            "reason": "task title or details contain high-risk keywords (trading, order, exchange, deploy, etc.)",
            "risk_level": "high",
        }
    if _has_high_risk_area(prepared_task):
        return {
            "required": True,
            "reason": "inferred repo area indicates trading, exchange, order sync, or runtime/deploy",
            "risk_level": "high",
        }

    # Known safe callback (documentation or monitoring triage) and no high-risk signals
    if _is_known_safe_callback(callback_selection):
        return {
            "required": False,
            "reason": "documentation or monitoring triage callback; writes only under docs/",
            "risk_level": "low",
        }

    # Future callback that we don't classify as safe -> require approval
    return {
        "required": True,
        "reason": "callback is not in the approved low-risk set (documentation, monitoring triage)",
        "risk_level": "medium",
    }


def build_approval_summary(
    prepared_task: dict[str, Any],
    callback_selection: dict[str, Any],
    approval_decision: dict[str, Any],
) -> str:
    """
    Build a short human-readable summary for approval decisions.

    Includes: task title, project, priority, inferred repo area, selected callback,
    risk level, whether approval is required, and reason.
    """
    task = (prepared_task or {}).get("task") or {}
    repo_area = (prepared_task or {}).get("repo_area") or {}

    title = str(task.get("task") or "").strip() or "(no title)"
    project = str(task.get("project") or "").strip() or "(none)"
    priority = str(task.get("priority") or "").strip() or "(none)"
    area_name = str(repo_area.get("area_name") or "").strip() or "(none)"
    selection_reason = str((callback_selection or {}).get("selection_reason") or "").strip() or "(none)"
    versioning = (prepared_task or {}).get("versioning") or {}
    proposed_version = str(versioning.get("proposed_version") or task.get("proposed_version") or "").strip() or "(none)"
    change_summary = str(versioning.get("change_summary") or task.get("change_summary") or "").strip() or "(none)"
    confidence_score = str(versioning.get("confidence_score") or task.get("confidence_score") or "").strip()
    symbol = str(versioning.get("symbol") or task.get("symbol") or "").strip()
    profile = str(versioning.get("profile") or task.get("profile") or "").strip()
    side = str(versioning.get("side") or task.get("side") or "").strip()

    required = bool((approval_decision or {}).get("required"))
    risk = str((approval_decision or {}).get("risk_level") or "").strip() or "unknown"
    reason = str((approval_decision or {}).get("reason") or "").strip() or "(none)"
    is_analysis = "analysis" in selection_reason.lower()
    is_strategy_patch = "strategy-patch" in selection_reason.lower()
    is_profile_setting = "profile-setting-analysis" in selection_reason.lower()

    lines = [
        "--- Approval summary ---",
        f"Task: {title}",
        f"Project: {project}",
        f"Priority: {priority}",
        f"Inferred area: {area_name}",
        f"Selected callback: {selection_reason}",
        f"Proposal type: {'strategy patch proposal' if is_strategy_patch else ('analysis proposal' if is_analysis else 'implementation/change')}",
        (
            f"Targets: symbol={symbol or 'unknown'} profile={profile or 'unknown'} side={side or 'unknown'}"
            if is_profile_setting
            else "Targets: n/a"
        ),
        f"Proposed version: {proposed_version}",
        f"Change summary: {change_summary}",
        (
            f"Confidence score: {confidence_score}"
            if confidence_score
            else (
                "Confidence score: pending (computed by analysis callback)"
                if "signal-performance-analysis" in selection_reason.lower()
                else "Confidence score: n/a"
            )
        ),
        (
            "Execution mode: manual-only (auto-execution disabled)"
            if is_strategy_patch
            else "Execution mode: standard"
        ),
        f"Risk level: {risk}",
        f"Approval required: {required}",
        f"Reason: {reason}",
        "------------------------",
    ]
    return "\n".join(lines)
