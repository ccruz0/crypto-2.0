"""
Execution policy for OpenClaw/ATP task lifecycle.

Classifies actions into:
- read_only: No side effects (read docs, logs, configs, runtime state)
- safe_ops: Idempotent, non-destructive (health checks, status snapshots, log inspection)
- patch_prep: Prepare artifacts only (write to docs/, generate diffs, proposals)
- prod_mutation: Production-impacting (edit prod code/config, deploy, migrations, live behavior changes)

Policy: Only prod_mutation requires explicit human approval before execution.
Investigation, diagnosis, patch preparation, and verification run autonomously.
"""

from __future__ import annotations

import logging
import os
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ActionClass(str, Enum):
    """Classification of agent/callback actions."""

    READ_ONLY = "read_only"
    SAFE_OPS = "safe_ops"
    PATCH_PREP = "patch_prep"
    PROD_MUTATION = "prod_mutation"


# Callback selection_reason substrings that imply prod_mutation (require approval before apply)
_PROD_MUTATION_REASONS = (
    "strategy-patch",  # Edits signal_monitor.py, trading config
    "profile-setting-analysis",  # Can propose trading_config changes
)

# Callback selection_reason substrings that are patch_prep only (docs/, no prod edit)
_PATCH_PREP_REASONS = (
    "bug investigation",
    "documentation",
    "monitoring",
    "triage",
    "generic OpenClaw",
    "signal-performance-analysis",  # Analysis only, writes to docs/
    "strategy-analysis",  # Analysis only, writes to docs/
)

# Callback selection_reason substrings that are read_only or safe_ops
_READ_ONLY_SAFE_REASONS = (
    "documentation",
    "monitoring",
    "triage",
)


def classify_callback_action(
    callback_selection: dict[str, Any],
    prepared_task: dict[str, Any] | None = None,
) -> ActionClass:
    """
    Classify the action that a callback pack will perform.

    Returns:
        ActionClass: read_only, safe_ops, patch_prep, or prod_mutation
    """
    reason = str((callback_selection or {}).get("selection_reason") or "").lower()

    # Prod mutation: edits production code/config, requires approval before apply
    for kw in _PROD_MUTATION_REASONS:
        if kw in reason:
            return ActionClass.PROD_MUTATION

    # Patch prep: writes to docs/ only, no prod mutation
    for kw in _PATCH_PREP_REASONS:
        if kw in reason:
            return ActionClass.PATCH_PREP

    # Default: unknown callback is treated as prod_mutation (safe default)
    return ActionClass.PROD_MUTATION


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
    }
