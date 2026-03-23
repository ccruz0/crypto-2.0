"""
Stable identity + fingerprint for approved agent execution bundles.

Callables are not JSON-serializable; bundles are stored with prepared_task + metadata and
callbacks are re-selected on load. Fingerprinting ties the approved intent to the resolved
callbacks + governance fields so drift is detectable at execution time.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from app.services.agent_execution_policy import GOVERNANCE_ACTION_CLASS_KEY, GOV_CLASS_PATCH_PREP, GOV_CLASS_PROD_MUTATION

logger = logging.getLogger(__name__)


def _callable_identity(fn: Any) -> dict[str, str] | None:
    if fn is None or not callable(fn):
        return None
    mod = str(getattr(fn, "__module__", "") or "")
    name = str(getattr(fn, "__name__", "") or type(fn).__name__ or "")
    return {"module": mod[:500], "name": name[:200]}


def build_bundle_identity_dict(
    prepared_task: dict[str, Any] | None,
    callback_selection: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Canonical execution identity (JSON-serializable). Used for fingerprinting.

    extended_lifecycle is derived from manual_only on the callback pack (set before
    execute mutates prepared_task with _use_extended_lifecycle).
    """
    pt = prepared_task or {}
    cb = callback_selection or {}
    task = pt.get("task") or {}
    nid = str(task.get("id") or "").strip()
    em = str(pt.get("execution_mode") or task.get("execution_mode") or "normal").strip().lower()[:64]
    gov = str(cb.get(GOVERNANCE_ACTION_CLASS_KEY) or "").strip().lower()
    if gov not in (GOV_CLASS_PATCH_PREP, GOV_CLASS_PROD_MUTATION):
        gov = ""
    sel = str(cb.get("selection_reason") or "").strip()[:500]
    manual_only = bool(cb.get("manual_only"))
    identity: dict[str, Any] = {
        "notion_task_id": nid,
        "execution_mode": em,
        "governance_action_class": gov,
        "selection_reason": sel,
        "manual_only": manual_only,
        "extended_lifecycle": manual_only,
        "apply": _callable_identity(cb.get("apply_change_fn")),
        "validate": _callable_identity(cb.get("validate_fn")),
        "deploy": _callable_identity(cb.get("deploy_fn")),
    }
    return identity


def compute_bundle_fingerprint(identity: dict[str, Any]) -> str:
    """Deterministic sha256 over canonical JSON (no timestamps)."""
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def verify_bundle_fingerprint(
    expected_fingerprint: str | None,
    prepared_task: dict[str, Any] | None,
    callback_selection: dict[str, Any] | None,
) -> tuple[bool, str | None, str | None]:
    """
    Compare approved fingerprint to identity implied by current prepared_task + callbacks.

    Returns (ok, expected_fp_or_none, current_fp_or_none). Missing expected → ok True (legacy bundles).
    """
    if not (expected_fingerprint or "").strip():
        return True, None, None
    exp = (expected_fingerprint or "").strip()
    ident = build_bundle_identity_dict(prepared_task, callback_selection)
    cur = compute_bundle_fingerprint(ident)
    return (cur == exp, exp, cur)


def log_bundle_fingerprint_created(
    *,
    notion_task_id: str,
    fingerprint: str,
    identity: dict[str, Any],
    manifest_id: str | None,
    environment: str,
    enforcement_active: bool,
    log_context: str,
) -> None:
    apply_id = identity.get("apply") or {}
    payload = {
        "event": "governance_bundle_fingerprint_created",
        "notion_task_id": notion_task_id[:64],
        "task_id": notion_task_id[:64],
        "manifest_id": manifest_id or "",
        "approved_fingerprint": fingerprint,
        "governance_action_class": identity.get("governance_action_class", ""),
        "selection_reason": (identity.get("selection_reason") or "")[:500],
        "callback_module": apply_id.get("module", "") if isinstance(apply_id, dict) else "",
        "callback_name": apply_id.get("name", "") if isinstance(apply_id, dict) else "",
        "environment": environment,
        "enforcement_active": enforcement_active,
        "log_context": log_context,
    }
    logger.info("%s %s", payload["event"], json.dumps(payload, default=str))


def log_bundle_fingerprint_verified(
    *,
    notion_task_id: str,
    fingerprint: str,
    manifest_id: str | None,
    environment: str,
    enforcement_active: bool,
    log_context: str,
) -> None:
    payload = {
        "event": "governance_bundle_fingerprint_verified",
        "notion_task_id": notion_task_id[:64],
        "task_id": notion_task_id[:64],
        "manifest_id": manifest_id or "",
        "approved_fingerprint": fingerprint,
        "current_fingerprint": fingerprint,
        "environment": environment,
        "enforcement_active": enforcement_active,
        "log_context": log_context,
    }
    logger.info("%s %s", payload["event"], json.dumps(payload, default=str))


def log_bundle_drift_detected(
    *,
    notion_task_id: str,
    approved_fingerprint: str,
    current_fingerprint: str,
    manifest_id: str | None,
    governance_action_class: str,
    callback_module: str,
    callback_name: str,
    environment: str,
    enforcement_active: bool,
    log_context: str,
    blocked: bool,
) -> None:
    payload = {
        "event": "governance_bundle_drift_detected",
        "notion_task_id": notion_task_id[:64],
        "task_id": notion_task_id[:64],
        "manifest_id": manifest_id or "",
        "approved_fingerprint": approved_fingerprint,
        "current_fingerprint": current_fingerprint,
        "governance_action_class": governance_action_class[:32],
        "callback_module": callback_module[:500],
        "callback_name": callback_name[:200],
        "environment": environment,
        "enforcement_active": enforcement_active,
        "log_context": log_context,
        "blocked": blocked,
    }
    line = json.dumps(payload, default=str)
    if blocked:
        logger.error("%s %s", payload["event"], line)
    else:
        logger.warning("%s %s", payload["event"], line)
