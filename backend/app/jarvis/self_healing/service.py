"""Self-Healing Advisor service (Phase 7).

Bridges completed investigations to safe, advisory fix recommendations and,
when confidence is high enough and safety allows, to an ACW task (which itself
still requires two human approval gates before any code is applied).

Hard guarantees:
* Never modifies production, deploys, merges, places trades, or executes fixes.
* Only generates recommendations and (optionally) prepares an ACW task.
* Human approval remains mandatory downstream.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.jarvis.investigations.investigation_types import InvestigationStatus
from app.jarvis.self_healing.assessment import assess_root_cause
from app.jarvis.self_healing.config import self_healing_acw_threshold, self_healing_enabled
from app.jarvis.self_healing.recommendation import recommend_fix
from app.jarvis.self_healing.safety_rules import evaluate_self_healing_safety

logger = logging.getLogger(__name__)

# Actions surfaced to the Approval Center / dashboard.
ACTION_CREATE_FIX_PR = "create_fix_pr"
ACTION_CREATE_ACW_TASK = "create_acw_task"
ACTION_IGNORE = "ignore"
ACTION_INVESTIGATE_FURTHER = "investigate_further"


class SelfHealingError(Exception):
    """Raised when a self-healing operation cannot proceed."""

    def __init__(self, message: str, *, status_code: int = 400, reasons: list[str] | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.reasons = reasons or []


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_completed(investigation: dict[str, Any]) -> bool:
    return str(investigation.get("status") or "").strip() == InvestigationStatus.COMPLETED.value


def _build_proposed_objective(investigation: dict[str, Any], proposed_fix: str) -> str:
    inv_id = str(investigation.get("investigation_id") or "")[:8]
    fix = (proposed_fix or "").strip() or str(investigation.get("root_cause") or "")
    objective = f"Apply safe fix for investigation {inv_id}: {fix}"
    return objective[:500]


def _build_implementation_plan(
    *,
    proposed_fix: str,
    affected_files: list[str],
    validation_rules: list[str],
    test_paths: list[str],
) -> list[str]:
    plan: list[str] = []
    if affected_files:
        plan.append(f"Update {', '.join(affected_files[:5])} to apply the fix.")
    else:
        plan.append("Locate the affected module(s) and apply the targeted fix.")
    if proposed_fix:
        plan.append(proposed_fix)
    for rule in validation_rules[:4]:
        plan.append(f"Verify: {rule}")
    if test_paths:
        plan.append(f"Run tests: {', '.join(test_paths[:5])}.")
    else:
        plan.append("Add or extend regression tests covering the fixed behavior.")
    plan.append("Submit for human approval (Gate 1 sandbox apply, Gate 2 PR). No auto-merge or deploy.")
    return plan


def _available_actions(*, acw_ready: bool, has_template: bool, safety_allowed: bool) -> list[str]:
    actions: list[str] = []
    if acw_ready:
        actions.append(ACTION_CREATE_ACW_TASK)
    if has_template and safety_allowed:
        actions.append(ACTION_CREATE_FIX_PR)
    actions.append(ACTION_INVESTIGATE_FURTHER)
    actions.append(ACTION_IGNORE)
    return actions


def build_recommendation(investigation: dict[str, Any]) -> dict[str, Any]:
    """Build a complete self-healing recommendation for an investigation dict.

    Pure and deterministic: no DB writes, no production access, no execution.
    Returns the recommendation regardless of the enabled flag (the flag gates
    *acting* on it, not generating advisory content), but ``acw_ready`` and the
    ACW package are only populated when the feature is enabled and safe.
    """
    inv_id = str(investigation.get("investigation_id") or "")
    enabled = self_healing_enabled()
    threshold = self_healing_acw_threshold()
    completed = _is_completed(investigation)
    confidence = float(investigation.get("confidence") or 0.0)

    fix = recommend_fix(investigation)
    proposed_objective = _build_proposed_objective(investigation, fix.proposed_fix)

    safety = evaluate_self_healing_safety(
        objective=str(investigation.get("objective") or ""),
        root_cause=str(investigation.get("root_cause") or ""),
        recommended_fix=fix.proposed_fix,
        proposed_objective=proposed_objective,
        affected_files=fix.affected_files,
    )

    assessment = assess_root_cause(
        investigation,
        affected_files=fix.affected_files,
        has_template=fix.has_template,
        safety_allowed=safety.allowed,
    )

    # Decide ACW readiness with explicit reasons for transparency.
    acw_reasons: list[str] = []
    if not enabled:
        acw_reasons.append("self_healing_disabled")
    if not completed:
        acw_reasons.append("investigation_not_completed")
    if not assessment.has_meaningful_root_cause:
        acw_reasons.append("missing_root_cause")
    if confidence < threshold:
        acw_reasons.append("confidence_below_threshold")
    if not safety.allowed:
        acw_reasons.append("safety_blocked")
    if assessment.fixability not in ("template", "code_change"):
        acw_reasons.append("not_fixable")
    if not fix.affected_files:
        acw_reasons.append("affected_files_unknown")

    acw_ready = len(acw_reasons) == 0

    implementation_plan = _build_implementation_plan(
        proposed_fix=fix.proposed_fix,
        affected_files=fix.affected_files,
        validation_rules=fix.validation_rules,
        test_paths=fix.test_paths,
    )

    return {
        "investigation_id": inv_id,
        "generated_at": _now_iso(),
        "enabled": enabled,
        "status": str(investigation.get("status") or ""),
        "root_cause": investigation.get("root_cause"),
        "confidence": round(confidence, 2),
        "assessment": assessment.to_dict(),
        "recommendation": fix.to_dict(),
        "acw": {
            "acw_ready": acw_ready,
            "threshold": threshold,
            "reasons": acw_reasons,
            "proposed_objective": proposed_objective if acw_ready else "",
            "implementation_plan": implementation_plan,
            "expected_files": list(fix.affected_files),
            "expected_tests": list(fix.test_paths),
        },
        "safety": safety.to_dict(),
        # Convenience top-level fields mirrored onto investigation report (req #6).
        "proposed_fix": fix.proposed_fix,
        "affected_files": list(fix.affected_files),
        "estimated_risk": fix.estimated_risk,
        "acw_ready": acw_ready,
        "available_actions": _available_actions(
            acw_ready=acw_ready,
            has_template=fix.has_template,
            safety_allowed=safety.allowed,
        ),
    }


def _self_healing_fields(recommendation: dict[str, Any]) -> dict[str, Any]:
    """Top-level investigation-report extensions (requirement #6)."""
    return {
        "proposed_fix": recommendation.get("proposed_fix", ""),
        "confidence": recommendation.get("confidence", 0.0),
        "affected_files": recommendation.get("affected_files", []),
        "estimated_risk": recommendation.get("estimated_risk", "medium"),
        "acw_ready": recommendation.get("acw_ready", False),
        "self_healing": recommendation,
    }


def attach_self_healing(investigation: dict[str, Any] | None) -> dict[str, Any] | None:
    """Merge self-healing recommendation fields onto an investigation detail dict.

    Gated by ``JARVIS_SELF_HEALING_ENABLED`` and only for completed investigations.
    Returns the investigation unchanged when disabled or not completed.
    """
    if investigation is None:
        return None
    if not self_healing_enabled() or not _is_completed(investigation):
        return investigation
    try:
        recommendation = build_recommendation(investigation)
        investigation = {**investigation, **_self_healing_fields(recommendation)}
    except Exception as exc:  # pragma: no cover - defensive, never break detail view
        logger.warning("attach_self_healing failed: %s", exc)
    return investigation


def generate_recommendation_for_investigation(investigation_id: str) -> dict[str, Any]:
    """Load an investigation and build its self-healing recommendation."""
    from app.jarvis.investigations.persistence import get_investigation

    inv_id = (investigation_id or "").strip()
    investigation = get_investigation(inv_id)
    if investigation is None:
        raise SelfHealingError("investigation not found", status_code=404)
    if not _is_completed(investigation):
        raise SelfHealingError(
            "investigation is not completed", status_code=409, reasons=["investigation_not_completed"]
        )
    return build_recommendation(investigation)


def _submit_acw_task(
    *,
    objective: str,
    priority: str,
    target_files: list[str] | None,
) -> dict[str, Any]:
    """Lazily submit an ACW task, degrading gracefully if ACW is unavailable.

    The ACW pipeline (objective → plan → patch → review → approval package) waits
    for two human approval gates before any code is applied. Nothing is executed,
    merged, or deployed here.
    """
    try:
        from app.jarvis.coding_workflow.service import submit_coding_workflow
    except ImportError as exc:  # ACW module unavailable in this deployment
        raise SelfHealingError(
            "ACW coding workflow is unavailable in this environment",
            status_code=503,
            reasons=["acw_unavailable"],
        ) from exc
    try:
        return submit_coding_workflow(
            objective=objective,
            priority=priority,
            target_files=target_files,
        )
    except RuntimeError as exc:
        # LAB prerequisites for ACW not met (cursor bridge, builder flags, ATP_TRADING_ONLY).
        raise SelfHealingError(str(exc), status_code=403, reasons=["acw_unavailable"]) from exc


def create_acw_task_from_recommendation(
    investigation_id: str,
    *,
    actor_id: str = "self_healing_advisor",
    priority: str = "normal",
) -> dict[str, Any]:
    """Create an ACW task from a high-confidence, safe recommendation.

    This only *prepares* an ACW task (objective + target files). The ACW pipeline
    produces a patch + review + approval package and waits for human approval at
    both gates. No code is applied, merged, or deployed here.
    """
    if not self_healing_enabled():
        raise SelfHealingError(
            "Self-healing is disabled (JARVIS_SELF_HEALING_ENABLED=false)",
            status_code=403,
            reasons=["self_healing_disabled"],
        )

    recommendation = generate_recommendation_for_investigation(investigation_id)

    safety = recommendation.get("safety") or {}
    if not safety.get("allowed", False):
        raise SelfHealingError(
            "recommendation blocked by self-healing safety rules",
            status_code=403,
            reasons=safety.get("reasons") or ["safety_blocked"],
        )
    if not recommendation.get("acw_ready"):
        raise SelfHealingError(
            "recommendation is not ACW-ready",
            status_code=409,
            reasons=(recommendation.get("acw") or {}).get("reasons") or ["not_acw_ready"],
        )

    acw = recommendation.get("acw") or {}
    objective = acw.get("proposed_objective") or ""
    expected_files = list(acw.get("expected_files") or [])

    task = _submit_acw_task(
        objective=objective,
        priority=priority,
        target_files=expected_files or None,
    )

    logger.info(
        "self_healing.acw_task_created investigation_id=%s task_id=%s actor=%s",
        investigation_id,
        task.get("task_id"),
        actor_id,
    )
    return {
        "investigation_id": recommendation.get("investigation_id"),
        "acw_task": task,
        "recommendation": recommendation,
        "created_by": actor_id,
        "created_at": _now_iso(),
    }


def record_decision(investigation_id: str, decision: str, *, actor_id: str = "operator") -> dict[str, Any]:
    """Acknowledge a lightweight self-healing decision (ignore / investigate_further).

    These actions are advisory and non-destructive. For ``investigate_further`` we
    return a suggested follow-up objective derived from missing evidence; we never
    re-run anything automatically here.
    """
    from app.jarvis.investigations.persistence import get_investigation

    inv_id = (investigation_id or "").strip()
    investigation = get_investigation(inv_id)
    if investigation is None:
        raise SelfHealingError("investigation not found", status_code=404)

    normalized = (decision or "").strip().lower()
    if normalized not in (ACTION_IGNORE, ACTION_INVESTIGATE_FURTHER):
        raise SelfHealingError("unsupported decision", status_code=400)

    payload: dict[str, Any] = {
        "investigation_id": inv_id,
        "decision": normalized,
        "recorded_at": _now_iso(),
        "actor_id": actor_id,
    }
    if normalized == ACTION_INVESTIGATE_FURTHER:
        missing = investigation.get("missing_evidence") or []
        objective = str(investigation.get("objective") or "")
        payload["suggested_objective"] = (
            f"Deeper investigation (read-only): {objective}".strip()[:500]
        )
        payload["missing_evidence"] = list(missing)
    logger.info("self_healing.decision investigation_id=%s decision=%s actor=%s", inv_id, normalized, actor_id)
    return payload
