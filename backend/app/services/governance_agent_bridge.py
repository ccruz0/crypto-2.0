"""
Wire Notion/Telegram agent flows into governance manifests.

When ATP_GOVERNANCE_AGENT_ENFORCE=true on AWS:
- Release-candidate deploy approval creates a governance manifest before the Telegram is sent.
- Telegram "Approve Deploy" records governance manifest approval and runs execution via
  governance_executor (agent_deploy_bundle), instead of calling patch + GitHub dispatch directly.
- **execute_prepared_notion_task** (prod_mutation callbacks only): `send_task_approval_request`
  creates an **execution manifest**; Telegram Approve calls `approve_manifest` on it; the apply /
  validate / deploy pipeline runs only through `governance_executor` (`agent_execute_prepared_pipeline`).

Legacy Telegram UX is preserved; governance manifest + digest become the source of truth for
what runs on PROD. agent_approval_states remains for bundle storage / execution guards elsewhere;
PROD deploy mutation when enforced is gated by governance_manifests + executor.

LAB / local (not AWS): enforcement off by default — no manifest required, legacy path unchanged.
Patch-prep / investigation callbacks (non–prod_mutation per agent_execution_policy) skip execution
manifests even on AWS.

When enforce is on, ``ensure_notion_governance_task_stub`` may run from Notion prepare / Telegram
approval **before** any manifest exists — only to create the ``gov-notion-<page_id>`` correlation
row for timelines (not approval semantics).
"""

from __future__ import annotations

import logging
import os
from typing import Any

from sqlalchemy.orm import Session

from app.core.environment import is_aws

logger = logging.getLogger(__name__)

ENV_GOVERNANCE_AGENT_ENFORCE = "ATP_GOVERNANCE_AGENT_ENFORCE"

# TradingSettings key: latest deploy manifest for this Notion page (value = manifest_id)
SETTINGS_DEPLOY_MANIFEST_PREFIX = "governance_deploy_manifest:"
# TradingSettings key: execution manifest for execute_prepared_notion_task (prod_mutation)
SETTINGS_EXECUTE_MANIFEST_PREFIX = "governance_execute_manifest:"


def governance_agent_enforce_production() -> bool:
    """True when agent-driven PROD deploy must use governance manifest + executor."""
    raw = (os.environ.get(ENV_GOVERNANCE_AGENT_ENFORCE) or "").strip().lower()
    return raw in ("1", "true", "yes", "on") and is_aws()


def notion_to_governance_task_id(notion_task_id: str) -> str:
    """Stable governance task id for a Notion task page."""
    nid = (notion_task_id or "").strip()
    return f"gov-notion-{nid}"


def _settings_key(notion_task_id: str) -> str:
    return f"{SETTINGS_DEPLOY_MANIFEST_PREFIX}{notion_task_id.strip()}"


def get_deploy_manifest_id(db: Session, notion_task_id: str) -> str | None:
    try:
        from app.models.trading_settings import TradingSettings

        key = _settings_key(notion_task_id)
        row = db.query(TradingSettings).filter(TradingSettings.setting_key == key).first()
        if row and (row.setting_value or "").strip():
            return (row.setting_value or "").strip()[:128]
    except Exception as e:
        logger.warning("governance_agent_bridge: get_deploy_manifest_id failed %s", e)
    return None


def _execute_settings_key(notion_task_id: str) -> str:
    return f"{SETTINGS_EXECUTE_MANIFEST_PREFIX}{notion_task_id.strip()}"


def get_execute_manifest_id(db: Session, notion_task_id: str) -> str | None:
    try:
        from app.models.trading_settings import TradingSettings

        key = _execute_settings_key(notion_task_id)
        row = db.query(TradingSettings).filter(TradingSettings.setting_key == key).first()
        if row and (row.setting_value or "").strip():
            return (row.setting_value or "").strip()[:128]
    except Exception as e:
        logger.warning("governance_agent_bridge: get_execute_manifest_id failed %s", e)
    return None


def set_execute_manifest_id(db: Session, notion_task_id: str, manifest_id: str) -> None:
    from app.models.trading_settings import TradingSettings

    key = _execute_settings_key(notion_task_id)
    val = (manifest_id or "").strip()[:500]
    row = db.query(TradingSettings).filter(TradingSettings.setting_key == key).first()
    if row:
        row.setting_value = val
    else:
        db.add(
            TradingSettings(
                setting_key=key[:100],
                setting_value=val,
                description="Latest governance manifest for agent execute_prepared pipeline (Notion task)",
            )
        )
    db.flush()


def set_deploy_manifest_id(db: Session, notion_task_id: str, manifest_id: str) -> None:
    from app.models.trading_settings import TradingSettings

    key = _settings_key(notion_task_id)
    val = (manifest_id or "").strip()[:500]
    row = db.query(TradingSettings).filter(TradingSettings.setting_key == key).first()
    if row:
        row.setting_value = val
    else:
        db.add(
            TradingSettings(
                setting_key=key[:100],
                setting_value=val,
                description="Latest governance manifest for agent deploy (Notion task)",
            )
        )
    db.flush()


def build_execute_prepared_manifest_commands(
    prepared_task: dict[str, Any],
    callback_selection: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Canonical command list for execute_prepared_notion_task governance.
    Must stay JSON-serializable and stable for digest checks.
    """
    task = (prepared_task or {}).get("task") or {}
    nid = str(task.get("id") or "").strip()
    sel = str((callback_selection or {}).get("selection_reason") or "").strip()
    use_ext = bool((prepared_task or {}).get("_use_extended_lifecycle")) or bool(
        (callback_selection or {}).get("manual_only")
    )
    emode = str(
        (prepared_task or {}).get("execution_mode")
        or task.get("execution_mode")
        or "normal"
    ).strip()
    apply_fn = (callback_selection or {}).get("apply_change_fn")
    apply_name = ""
    apply_mod = ""
    if callable(apply_fn):
        apply_name = str(getattr(apply_fn, "__name__", "") or type(apply_fn).__name__ or "")[:120]
        apply_mod = str(getattr(apply_fn, "__module__", "") or "")[:200]
    bundle_fp = ""
    try:
        from app.services.agent_bundle_identity import build_bundle_identity_dict, compute_bundle_fingerprint

        bundle_fp = compute_bundle_fingerprint(
            build_bundle_identity_dict(prepared_task, callback_selection)
        )
    except Exception:
        pass
    from app.services.agent_execution_policy import GOVERNANCE_ACTION_CLASS_KEY

    gov_class = str((callback_selection or {}).get(GOVERNANCE_ACTION_CLASS_KEY) or "").strip().lower()[:32]
    return [
        {
            "type": "agent_execute_prepared_pipeline",
            "notion_task_id": nid,
            "audit": {
                "selection_reason": sel[:500],
                "apply_change_fn": apply_name,
                "apply_module": apply_mod,
                "governance_action_class": gov_class,
                "bundle_fingerprint": bundle_fp[:128],
                "validate_configured": bool((callback_selection or {}).get("validate_fn")),
                "deploy_configured": bool((callback_selection or {}).get("deploy_fn")),
                "extended_lifecycle": use_ext,
                "execution_mode": emode[:32],
            },
        }
    ]


def log_governance_bypass_legacy_execute_path(
    *,
    path: str,
    reason: str,
    task_id: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    """Structured marker when prod_mutation runs outside governance (enforce off / not AWS)."""
    payload: dict[str, Any] = {"path": path, "reason": reason, **(extra or {})}
    try:
        from app.services.agent_activity_log import log_agent_event

        log_agent_event(
            "governance_bypassed_legacy_path",
            task_id=task_id or None,
            details=payload,
        )
    except Exception:
        logger.info(
            "governance_bypassed_legacy_path path=%s reason=%s task_id=%s",
            path,
            reason,
            task_id[:12] if task_id else "",
        )


def _risk_to_governance_level(risk: str) -> str:
    r = (risk or "HIGH").strip().upper()
    if r == "HIGH":
        return "high"
    if r == "MEDIUM":
        return "medium"
    if r == "LOW":
        return "low"
    return "high"


def infer_governance_risk_for_notion_agent(
    *,
    task: dict[str, Any] | None = None,
    repo_area: dict[str, Any] | None = None,
    sections: dict[str, Any] | None = None,
) -> str:
    """Map Notion task / bundle context to governance ``risk_level`` (high/medium/low)."""
    from app.services.agent_telegram_approval import infer_risk_classification

    rc = infer_risk_classification(
        sections=sections or {},
        task=task or {},
        repo_area=repo_area or {},
    )
    return _risk_to_governance_level(rc)


def ensure_notion_governance_task_stub(
    db: Session,
    notion_task_id: str,
    *,
    title: str | None = None,
    risk_level: str = "medium",
    actor_id: str = "notion_agent_correlation",
) -> tuple[str | None, bool]:
    """
    Ensure ``gov-notion-<page_id>`` exists when agent governance enforce is on (AWS only).

    Does **not** create manifests or imply human approval — correlation + timeline shell only.
    Idempotent. Returns ``(gov_task_id, created_new)``.
    """
    if not governance_agent_enforce_production():
        return None, False
    nid = (notion_task_id or "").strip()
    if not nid:
        return None, False
    from app.models.governance_models import GovernanceTask
    from app.services.governance_service import create_governance_task

    gov_tid = notion_to_governance_task_id(nid)
    if db.query(GovernanceTask).filter(GovernanceTask.task_id == gov_tid).first() is not None:
        return gov_tid, False
    create_governance_task(
        db,
        task_id=gov_tid,
        source_type="notion_agent",
        source_ref=nid[:500],
        risk_level=(risk_level or "medium")[:16],
        title=(title or "")[:500] if title else None,
        actor_type="system",
        actor_id=actor_id,
        environment="prod",
    )
    return gov_tid, True


def ensure_agent_deploy_manifest(
    db: Session,
    notion_task_id: str,
    *,
    title: str,
    risk_classification: str | None = None,
    task: dict[str, Any] | None = None,
    repo_area: dict[str, Any] | None = None,
    sections: dict[str, Any] | None = None,
) -> str | None:
    """
    Create or refresh governance task + manifest for a release-candidate deploy.

    Returns manifest_id, or None if enforcement is off (caller uses legacy path only).
    """
    if not governance_agent_enforce_production():
        return None

    nid = (notion_task_id or "").strip()
    if not nid:
        return None

    try:
        from app.services.agent_telegram_approval import infer_risk_classification
        from app.services.governance_service import (
            ST_COMPLETED,
            ST_PATCH_READY,
            create_manifest,
            emit_plan_event,
            governance_task_has_plan_event,
            transition_task_state,
        )
        from app.models.governance_models import GovernanceTask

        rc = risk_classification or infer_risk_classification(
            sections=sections or {},
            task=task or {},
            repo_area=repo_area or {},
        )
        g_risk = _risk_to_governance_level(rc)

        gov_tid, _stub_new = ensure_notion_governance_task_stub(
            db,
            nid,
            title=title,
            risk_level=g_risk,
            actor_id="deploy_approval_sender",
        )
        if not gov_tid:
            return None
        grow = db.query(GovernanceTask).filter(GovernanceTask.task_id == gov_tid).first()
        if not grow:
            return None
        if not _stub_new:
            grow.risk_level = g_risk[:16]
            st = (grow.status or "").strip()
            if st == ST_COMPLETED:
                try:
                    transition_task_state(
                        db,
                        task_id=gov_tid,
                        to_state=ST_PATCH_READY,
                        actor_type="system",
                        actor_id="deploy_approval_sender",
                        environment="prod",
                        reason="new deploy cycle",
                        send_telegram=False,
                    )
                except ValueError as e:
                    logger.warning(
                        "governance_agent_bridge: could not move completed gov task to patch_ready %s: %s",
                        gov_tid,
                        e,
                    )
                    return None

        if not governance_task_has_plan_event(db, gov_tid):
            emit_plan_event(
                db,
                task_id=gov_tid,
                actor_type="system",
                actor_id="deploy_approval_sender",
                environment="prod",
                summary=f"Governance task for Notion deploy: {title[:120]}",
                steps=[
                    "Human approves deploy in Telegram",
                    "governance_executor runs agent_deploy_bundle (strategy patch + GitHub dispatch)",
                ],
            )

        commands: list[dict[str, Any]] = [
            {
                "type": "agent_deploy_bundle",
                "notion_task_id": nid,
                "description": "apply_prepared_strategy_patch_after_approval + trigger_deploy_workflow",
            }
        ]
        scope = f"Notion task {nid[:12]}… deploy: strategy patch (if any) + GitHub Actions workflow_dispatch"
        mid, _ = create_manifest(
            db,
            task_id=gov_tid,
            commands=commands,
            scope_summary=scope,
            risk_level=g_risk,
            actor_type="system",
            actor_id="deploy_approval_sender",
            environment="prod",
            attach_and_await_approval=True,
        )
        set_deploy_manifest_id(db, nid, mid)
        logger.info(
            "governance_agent_bridge: ensured deploy manifest notion_task_id=%s manifest_id=%s gov_task=%s",
            nid[:12],
            mid,
            gov_tid,
        )
        return mid
    except Exception as e:
        logger.exception("governance_agent_bridge: ensure_agent_deploy_manifest failed: %s", e)
        return None


def ensure_agent_execute_prepared_manifest(
    db: Session,
    notion_task_id: str,
    *,
    prepared_task: dict[str, Any],
    callback_selection: dict[str, Any],
    title: str,
    risk_classification: str | None = None,
    task: dict[str, Any] | None = None,
    repo_area: dict[str, Any] | None = None,
    sections: dict[str, Any] | None = None,
) -> str | None:
    """
    Create or refresh governance task + manifest for execute_prepared_notion_task (prod_mutation).

    Returns manifest_id, or None if enforcement is off or on error.
    """
    if not governance_agent_enforce_production():
        return None

    nid = (notion_task_id or "").strip()
    if not nid:
        return None

    try:
        from app.services.agent_telegram_approval import infer_risk_classification
        from app.services.governance_service import (
            ST_COMPLETED,
            ST_PATCH_READY,
            create_manifest,
            emit_plan_event,
            governance_task_has_plan_event,
            transition_task_state,
        )
        from app.models.governance_models import GovernanceTask

        rc = risk_classification or infer_risk_classification(
            sections=sections or {},
            task=task or ((prepared_task or {}).get("task") or {}),
            repo_area=repo_area or ((prepared_task or {}).get("repo_area") or {}),
        )
        g_risk = _risk_to_governance_level(rc)

        gov_tid, _stub_new = ensure_notion_governance_task_stub(
            db,
            nid,
            title=title,
            risk_level=g_risk,
            actor_id="execute_prepared_approval_sender",
        )
        if not gov_tid:
            return None
        grow = db.query(GovernanceTask).filter(GovernanceTask.task_id == gov_tid).first()
        if not grow:
            return None
        if not _stub_new:
            grow.risk_level = g_risk[:16]
            st = (grow.status or "").strip()
            if st == ST_COMPLETED:
                try:
                    transition_task_state(
                        db,
                        task_id=gov_tid,
                        to_state=ST_PATCH_READY,
                        actor_type="system",
                        actor_id="execute_prepared_approval_sender",
                        environment="prod",
                        reason="new execute_prepared cycle",
                        send_telegram=False,
                    )
                except ValueError as e:
                    logger.warning(
                        "governance_agent_bridge: could not move completed gov task to patch_ready %s: %s",
                        gov_tid,
                        e,
                    )
                    return None

        if not governance_task_has_plan_event(db, gov_tid):
            emit_plan_event(
                db,
                task_id=gov_tid,
                actor_type="system",
                actor_id="execute_prepared_approval_sender",
                environment="prod",
                summary=f"Governance task for Notion execution pipeline: {title[:120]}",
                steps=[
                    "Human approves agent task in Telegram",
                    "governance_executor runs agent_execute_prepared_pipeline (apply/validate/deploy callbacks)",
                ],
            )

        commands = build_execute_prepared_manifest_commands(prepared_task, callback_selection)
        scope = (
            f"Notion {nid[:12]}… execute_prepared_notion_task: apply_change → validate → optional deploy "
            f"({(callback_selection or {}).get('selection_reason', '')[:80]})"
        )
        mid, _ = create_manifest(
            db,
            task_id=gov_tid,
            commands=commands,
            scope_summary=scope[:2000],
            risk_level=g_risk,
            actor_type="system",
            actor_id="execute_prepared_approval_sender",
            environment="prod",
            attach_and_await_approval=True,
        )
        set_execute_manifest_id(db, nid, mid)
        logger.info(
            "governance_agent_bridge: ensured execute manifest notion_task_id=%s manifest_id=%s gov_task=%s",
            nid[:12],
            mid,
            gov_tid,
        )
        return mid
    except Exception as e:
        logger.exception("governance_agent_bridge: ensure_agent_execute_prepared_manifest failed: %s", e)
        return None
