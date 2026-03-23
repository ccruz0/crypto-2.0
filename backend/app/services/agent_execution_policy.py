"""
Execution policy for OpenClaw/ATP task lifecycle.

Classifies actions into:
- read_only: No side effects (read docs, logs, configs, runtime state)
- safe_ops: Idempotent, non-destructive (health checks, status snapshots, log inspection)
- patch_prep: Prepare artifacts only (write to docs/, generate diffs, proposals)
- prod_mutation: Production-impacting (edit prod code/config, deploy, migrations, live behavior changes)

Governance (ATP_GOVERNANCE_AGENT_ENFORCE on AWS) uses classify_callback_action; false negatives
(bypass) are unacceptable. On AWS, classification is fail-closed to prod_mutation unless the
callback pack is explicitly marked safe (governance_action_class or callable markers / allowlists).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.core.environment import getRuntimeEnv, is_aws

logger = logging.getLogger(__name__)

# Bundle key set by select_default_callbacks_for_task (authoritative when present).
GOVERNANCE_ACTION_CLASS_KEY = "governance_action_class"
GOV_CLASS_PATCH_PREP = "patch_prep"
GOV_CLASS_PROD_MUTATION = "prod_mutation"

# Callables may set these attributes (set in agent_callbacks / analysis modules).
ATTR_PROD_MUTATION = "ATP_GOVERNANCE_PROD_MUTATION_APPLY"
ATTR_SAFE_LAB_APPLY = "ATP_GOVERNANCE_SAFE_LAB_APPLY"

# Reserved: Notion execution_mode value for future explicit lab routing (documented in IMPLEMENTATION_NOTES).
EXECUTION_MODE_LAB_ONLY = "lab_only"


class ActionClass(str, Enum):
    """Classification of agent/callback actions."""

    READ_ONLY = "read_only"
    SAFE_OPS = "safe_ops"
    PATCH_PREP = "patch_prep"
    PROD_MUTATION = "prod_mutation"


_VALID_GOVERNANCE_STRINGS = frozenset({GOV_CLASS_PATCH_PREP, GOV_CLASS_PROD_MUTATION})

# Legacy substring rules (local / non-AWS only): prod keywords checked before patch_prep
_PROD_MUTATION_REASONS = (
    "strategy-patch",
    "profile-setting-analysis",
)

_PATCH_PREP_REASONS = (
    "bug investigation",
    "documentation",
    "monitoring",
    "triage",
    "generic OpenClaw",
    "signal-performance-analysis",
    "strategy-analysis",
)

# Fallback identity allowlists when callables lack attributes (e.g. wrapped functions).
_PROD_APPLY_MODULES: frozenset[tuple[str, str]] = frozenset(
    {
        ("app.services.agent_strategy_patch", "apply_strategy_patch_task"),
        ("app.services.profile_setting_analysis", "apply_profile_setting_analysis_task"),
    }
)

_SAFE_APPLY_MODULES: frozenset[tuple[str, str]] = frozenset(
    {
        ("app.services.signal_performance_analysis", "apply_signal_performance_analysis_task"),
        ("app.services.agent_strategy_analysis", "apply_strategy_analysis_task"),
        ("app.services.agent_callbacks", "apply_bug_investigation_task"),
        ("app.services.agent_callbacks", "apply_documentation_task"),
        ("app.services.agent_callbacks", "apply_monitoring_triage_task"),
    }
)


@dataclass
class GovernanceClassificationValidation:
    """Result of structural / explicit governance metadata cross-check (apply path only)."""

    is_conflicting: bool
    conflict_type: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


class GovernanceClassificationConflictError(RuntimeError):
    """Raised on AWS when agent governance enforcement is on and callback metadata is self-contradictory."""

    def __init__(self, conflict_type: str, details: dict[str, Any], message: str | None = None) -> None:
        self.conflict_type = conflict_type
        self.details = details
        super().__init__(message or f"governance classification conflict: {conflict_type}")


def _apply_fn_identity(fn: Any) -> tuple[str, str]:
    if not callable(fn):
        return ("", "")
    mod = str(getattr(fn, "__module__", "") or "")
    name = str(getattr(fn, "__name__", "") or "")
    return (mod, name)


def governance_agent_enforcement_context_active() -> bool:
    """Same truth as governance_agent_bridge.governance_agent_enforce_production (no import cycle)."""
    raw = (os.environ.get("ATP_GOVERNANCE_AGENT_ENFORCE") or "").strip().lower()
    return raw in ("1", "true", "yes", "on") and is_aws()


def _legacy_local_reason_classification(reason_lower: str) -> ActionClass:
    for kw in _PROD_MUTATION_REASONS:
        if kw in reason_lower:
            return ActionClass.PROD_MUTATION
    for kw in _PATCH_PREP_REASONS:
        if kw in reason_lower:
            return ActionClass.PATCH_PREP
    return ActionClass.PROD_MUTATION


def validate_governance_classification_inputs(
    callback_selection: dict[str, Any] | None,
) -> GovernanceClassificationValidation:
    """
    Cross-check explicit governance_action_class against callable markers and module allowlists.

    Returns is_conflicting=True when metadata simultaneously claims safe lab and prod mutation
    (e.g. explicit patch_prep + prod marker, dual markers on one callable, or both allowlists).
    """
    cb = callback_selection or {}
    explicit = str(cb.get(GOVERNANCE_ACTION_CLASS_KEY) or "").strip().lower()
    apply_fn = cb.get("apply_change_fn")
    has_apply = callable(apply_fn)

    details: dict[str, Any] = {
        "explicit_class": explicit if explicit in _VALID_GOVERNANCE_STRINGS else "",
        "callback_module": "",
        "callback_name": "",
        "safe_lab_marker": False,
        "prod_mutation_marker": False,
        "in_prod_allowlist": False,
        "in_safe_allowlist": False,
        "structural_implied_class": "",
        "structural_source": "",
    }

    if not has_apply:
        return GovernanceClassificationValidation(False, None, details)

    mod, name = _apply_fn_identity(apply_fn)
    details["callback_module"] = mod
    details["callback_name"] = name
    prod_m = bool(getattr(apply_fn, ATTR_PROD_MUTATION, False))
    safe_m = bool(getattr(apply_fn, ATTR_SAFE_LAB_APPLY, False))
    details["safe_lab_marker"] = safe_m
    details["prod_mutation_marker"] = prod_m
    ident = (mod, name)
    in_prod = ident in _PROD_APPLY_MODULES
    in_safe = ident in _SAFE_APPLY_MODULES
    details["in_prod_allowlist"] = in_prod
    details["in_safe_allowlist"] = in_safe

    if prod_m and safe_m:
        return GovernanceClassificationValidation(
            True,
            "dual_safe_lab_and_prod_mutation_markers",
            {
                **details,
                "note": "Callable must not set both ATP_GOVERNANCE_PROD_MUTATION_APPLY and ATP_GOVERNANCE_SAFE_LAB_APPLY",
            },
        )

    if in_prod and in_safe:
        return GovernanceClassificationValidation(
            True,
            "dual_allowlist_membership",
            {
                **details,
                "note": "Identity appears in both _PROD_APPLY_MODULES and _SAFE_APPLY_MODULES",
            },
        )

    if explicit not in _VALID_GOVERNANCE_STRINGS:
        return GovernanceClassificationValidation(False, None, details)

    implied: str | None = None
    implied_source = ""
    if prod_m:
        implied = GOV_CLASS_PROD_MUTATION
        implied_source = "callable_prod_marker"
    elif safe_m:
        implied = GOV_CLASS_PATCH_PREP
        implied_source = "callable_safe_lab_marker"
    elif in_prod:
        implied = GOV_CLASS_PROD_MUTATION
        implied_source = "module_allowlist_prod"
    elif in_safe:
        implied = GOV_CLASS_PATCH_PREP
        implied_source = "module_allowlist_safe"

    details["structural_implied_class"] = implied or ""
    details["structural_source"] = implied_source

    if implied is None:
        return GovernanceClassificationValidation(False, None, details)

    if explicit == GOV_CLASS_PATCH_PREP and implied == GOV_CLASS_PROD_MUTATION:
        return GovernanceClassificationValidation(
            True,
            "explicit_patch_prep_vs_structural_prod",
            {
                **details,
                "note": "governance_action_class=patch_prep conflicts with prod mutation signals",
            },
        )
    if explicit == GOV_CLASS_PROD_MUTATION and implied == GOV_CLASS_PATCH_PREP:
        return GovernanceClassificationValidation(
            True,
            "explicit_prod_mutation_vs_structural_safe",
            {
                **details,
                "note": "governance_action_class=prod_mutation conflicts with safe lab signals",
            },
        )
    return GovernanceClassificationValidation(False, None, details)


def log_governance_classification_conflict(
    *,
    validation: GovernanceClassificationValidation,
    selection_reason: str,
    callback_module: str,
    callback_name: str,
    enforcement_active: bool,
    environment: str,
    log_context: str,
    resolution: str,
) -> None:
    """Structured log for grep / audit scripts (event: governance_classification_conflict)."""
    payload = {
        "event": "governance_classification_conflict",
        "conflict_type": validation.conflict_type,
        "resolution": resolution,
        "selection_reason": (selection_reason or "")[:500],
        "explicit_class": validation.details.get("explicit_class", ""),
        "callback_module": callback_module,
        "callback_name": callback_name,
        "safe_lab_marker": validation.details.get("safe_lab_marker"),
        "prod_mutation_marker": validation.details.get("prod_mutation_marker"),
        "in_prod_allowlist": validation.details.get("in_prod_allowlist"),
        "in_safe_allowlist": validation.details.get("in_safe_allowlist"),
        "structural_implied_class": validation.details.get("structural_implied_class", ""),
        "structural_source": validation.details.get("structural_source", ""),
        "enforcement_active": enforcement_active,
        "environment": environment,
        "log_context": log_context,
        "details": validation.details,
    }
    line = json.dumps(payload, default=str)
    if resolution == "blocked_raise" and enforcement_active and environment == "aws":
        logger.error("governance_classification_conflict %s", line)
    else:
        logger.warning("governance_classification_conflict %s", line)


def classify_callback_action(
    callback_selection: dict[str, Any],
    prepared_task: dict[str, Any] | None = None,
    *,
    log_context: str = "",
) -> ActionClass:
    """
    Classify the action that a callback pack will perform.

    On AWS (runtime): fail-closed to prod_mutation when an apply callback exists unless
    governance_action_class or structural safety markers / module allowlists say otherwise.
    Locally: legacy selection_reason heuristics still apply when no explicit class is present.

    Conflicting explicit class vs markers/allowlists: on AWS with ATP_GOVERNANCE_AGENT_ENFORCE,
    raises GovernanceClassificationConflictError. Otherwise logs and returns prod_mutation (fail-safe).
    """
    cb = callback_selection or {}
    reason = str(cb.get("selection_reason") or "").strip()
    reason_lower = reason.lower()
    apply_fn = cb.get("apply_change_fn")
    has_apply = callable(apply_fn)
    enforcement = governance_agent_enforcement_context_active()
    environment = getRuntimeEnv()

    validation = validate_governance_classification_inputs(cb)
    if validation.is_conflicting:
        mod_c, name_c = _apply_fn_identity(apply_fn if has_apply else None)
        if enforcement and is_aws():
            log_governance_classification_conflict(
                validation=validation,
                selection_reason=reason,
                callback_module=mod_c,
                callback_name=name_c,
                enforcement_active=enforcement,
                environment=environment,
                log_context=log_context,
                resolution="blocked_raise",
            )
            raise GovernanceClassificationConflictError(
                validation.conflict_type or "unknown",
                dict(validation.details),
            )
        log_governance_classification_conflict(
            validation=validation,
            selection_reason=reason,
            callback_module=mod_c,
            callback_name=name_c,
            enforcement_active=enforcement,
            environment=environment,
            log_context=log_context,
            resolution="fail_safe_prod_mutation",
        )
        _log_classification(
            result=ActionClass.PROD_MUTATION,
            reason=reason,
            apply_fn=apply_fn if has_apply else None,
            enforcement_active=enforcement,
            path="metadata_conflict_fail_safe_prod_mutation",
            log_context=log_context,
            environment=environment,
            explicit_class=str(validation.details.get("explicit_class") or ""),
            extra={
                "conflict_type": validation.conflict_type,
                "safe_lab_marker": validation.details.get("safe_lab_marker"),
                "prod_mutation_marker": validation.details.get("prod_mutation_marker"),
            },
        )
        return ActionClass.PROD_MUTATION

    explicit = str(cb.get(GOVERNANCE_ACTION_CLASS_KEY) or "").strip().lower()
    if explicit in _VALID_GOVERNANCE_STRINGS:
        result = ActionClass.PATCH_PREP if explicit == GOV_CLASS_PATCH_PREP else ActionClass.PROD_MUTATION
        _log_classification(
            result=result,
            reason=reason,
            apply_fn=apply_fn,
            enforcement_active=enforcement,
            path="explicit_governance_action_class",
            log_context=log_context,
            environment=environment,
            explicit_class=explicit,
            extra={"explicit": explicit},
        )
        return result

    if has_apply and bool(getattr(apply_fn, ATTR_PROD_MUTATION, False)):
        _log_classification(
            result=ActionClass.PROD_MUTATION,
            reason=reason,
            apply_fn=apply_fn,
            enforcement_active=enforcement,
            path="callable_prod_marker",
            log_context=log_context,
            environment=environment,
            explicit_class="",
        )
        return ActionClass.PROD_MUTATION

    if has_apply and bool(getattr(apply_fn, ATTR_SAFE_LAB_APPLY, False)):
        _log_classification(
            result=ActionClass.PATCH_PREP,
            reason=reason,
            apply_fn=apply_fn,
            enforcement_active=enforcement,
            path="callable_safe_lab_marker",
            log_context=log_context,
            environment=environment,
            explicit_class="",
        )
        return ActionClass.PATCH_PREP

    ident = _apply_fn_identity(apply_fn) if has_apply else ("", "")
    if has_apply and ident in _PROD_APPLY_MODULES:
        _log_classification(
            result=ActionClass.PROD_MUTATION,
            reason=reason,
            apply_fn=apply_fn,
            enforcement_active=enforcement,
            path="module_allowlist_prod",
            log_context=log_context,
            environment=environment,
            explicit_class="",
            extra={"identity": ident},
        )
        return ActionClass.PROD_MUTATION

    if has_apply and ident in _SAFE_APPLY_MODULES:
        _log_classification(
            result=ActionClass.PATCH_PREP,
            reason=reason,
            apply_fn=apply_fn,
            enforcement_active=enforcement,
            path="module_allowlist_safe",
            log_context=log_context,
            environment=environment,
            explicit_class="",
            extra={"identity": ident},
        )
        return ActionClass.PATCH_PREP

    if not has_apply:
        # No callable: use legacy reason heuristics everywhere (strategy-patch / profile keywords still prod).
        result = _legacy_local_reason_classification(reason_lower)
        _log_classification(
            result=result,
            reason=reason,
            apply_fn=None,
            enforcement_active=enforcement,
            path="no_apply_fn",
            log_context=log_context,
            environment=environment,
            explicit_class="",
        )
        return result

    if is_aws():
        uncertain_payload = {
            "event": "classification_uncertain_defaulted_to_prod_mutation",
            "selection_reason": reason[:500],
            "explicit_class": "",
            "callback_module": ident[0],
            "callback_name": ident[1],
            "safe_lab_marker": False,
            "prod_mutation_marker": False,
            "final_classification": ActionClass.PROD_MUTATION.value,
            "enforcement_active": enforcement,
            "environment": environment,
            "classification_path": "aws_fail_closed_uncertain",
            "log_context": log_context,
        }
        logger.warning("classification_uncertain_defaulted_to_prod_mutation %s", json.dumps(uncertain_payload, default=str))
        _log_classification(
            result=ActionClass.PROD_MUTATION,
            reason=reason,
            apply_fn=apply_fn,
            enforcement_active=enforcement,
            path="aws_fail_closed_uncertain",
            log_context=log_context,
            environment=environment,
            explicit_class="",
            extra={"identity": ident},
        )
        return ActionClass.PROD_MUTATION

    result = _legacy_local_reason_classification(reason_lower)
    _log_classification(
        result=result,
        reason=reason,
        apply_fn=apply_fn,
        enforcement_active=enforcement,
        path="local_legacy_reason_heuristic",
        log_context=log_context,
        environment=environment,
        explicit_class="",
        extra={"identity": ident},
    )
    return result


def _log_classification(
    *,
    result: ActionClass,
    reason: str,
    apply_fn: Any,
    enforcement_active: bool,
    path: str,
    log_context: str,
    environment: str,
    explicit_class: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    mod, name = _apply_fn_identity(apply_fn)
    prod_m = bool(getattr(apply_fn, ATTR_PROD_MUTATION, False)) if callable(apply_fn) else False
    safe_m = bool(getattr(apply_fn, ATTR_SAFE_LAB_APPLY, False)) if callable(apply_fn) else False
    payload = {
        "event": "governance_classification_result",
        "classification_result": result.value,
        "final_classification": result.value,
        "is_prod_mutation": result == ActionClass.PROD_MUTATION,
        "selection_reason": reason[:500],
        "apply_module": mod,
        "apply_name": name,
        "callback_module": mod,
        "callback_name": name,
        "explicit_class": explicit_class,
        "safe_lab_marker": safe_m,
        "prod_mutation_marker": prod_m,
        "enforcement_active": enforcement_active,
        "environment": environment,
        "classification_path": path,
        "log_context": log_context,
        **(extra or {}),
    }
    logger.info("%s %s", payload["event"], json.dumps(payload, default=str))


def requires_approval_before_apply(
    callback_selection: dict[str, Any],
    prepared_task: dict[str, Any] | None = None,
) -> bool:
    """
    True if the callback must NOT run apply until human approval.

    When True: apply phase should only prepare (write to docs/), not mutate production.
    """
    return classify_callback_action(callback_selection, prepared_task) == ActionClass.PROD_MUTATION


def is_safe_autonomous_mode() -> bool:
    """
    When True: prod_mutation callbacks run in prepare-only mode during apply.
    They write proposals to docs/ but do not edit production files.
    Approval is required before the actual prod mutation (deploy step).
    """
    raw = (os.environ.get("ATP_SAFE_AUTONOMOUS_MODE") or "true").strip().lower()
    return raw in ("1", "true", "yes")


def get_policy_summary() -> dict[str, Any]:
    """Return a summary of the current policy for logging/ops."""
    return {
        "safe_autonomous_mode": is_safe_autonomous_mode(),
        "prod_mutation_requires_approval": True,
        "single_approval_at": "release-candidate-ready",
        "governance_action_class_key": GOVERNANCE_ACTION_CLASS_KEY,
    }
