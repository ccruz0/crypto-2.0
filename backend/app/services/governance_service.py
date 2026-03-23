"""
Governance: task lifecycle, manifest digest, approvals, structured events.

Env:
  ATP_GOVERNANCE_ENFORCE — default false. When true on AWS runtime, unapproved PROD mutation
  entrypoints (e.g. monitoring backend restart) are blocked; use governance executor instead.

  ATP_GOVERNANCE_AGENT_ENFORCE — see governance_agent_bridge.py (release-candidate Telegram deploy +
  execute_prepared_notion_task prod_mutation path on AWS).

Approval TTL after approve (minutes) by manifest/task risk_level:
  low=30, medium=20, high=10, critical=5
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.environment import is_aws

logger = logging.getLogger(__name__)

ENV_GOVERNANCE_ENFORCE = "ATP_GOVERNANCE_ENFORCE"

# Lifecycle states
ST_REQUESTED = "requested"
ST_PLANNED = "planned"
ST_INVESTIGATING = "investigating"
ST_FINDINGS_READY = "findings_ready"
ST_PATCH_READY = "patch_ready"
ST_AWAITING_APPROVAL = "awaiting_approval"
ST_APPLYING = "applying"
ST_VALIDATING = "validating"
ST_COMPLETED = "completed"
ST_FAILED = "failed"

ALL_STATES = frozenset({
    ST_REQUESTED,
    ST_PLANNED,
    ST_INVESTIGATING,
    ST_FINDINGS_READY,
    ST_PATCH_READY,
    ST_AWAITING_APPROVAL,
    ST_APPLYING,
    ST_VALIDATING,
    ST_COMPLETED,
    ST_FAILED,
})

# Allowed transitions: from_state -> {to_states}
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    ST_REQUESTED: frozenset({ST_PLANNED, ST_INVESTIGATING, ST_AWAITING_APPROVAL, ST_FAILED}),
    ST_PLANNED: frozenset({ST_INVESTIGATING, ST_FINDINGS_READY, ST_AWAITING_APPROVAL, ST_FAILED}),
    ST_INVESTIGATING: frozenset({ST_FINDINGS_READY, ST_PATCH_READY, ST_AWAITING_APPROVAL, ST_FAILED}),
    ST_FINDINGS_READY: frozenset({ST_PATCH_READY, ST_AWAITING_APPROVAL, ST_FAILED}),
    ST_PATCH_READY: frozenset({ST_AWAITING_APPROVAL, ST_FAILED}),
    ST_AWAITING_APPROVAL: frozenset({ST_APPLYING, ST_PATCH_READY, ST_FAILED, ST_PLANNED}),
    ST_APPLYING: frozenset({ST_VALIDATING, ST_FAILED}),
    ST_VALIDATING: frozenset({ST_COMPLETED, ST_FAILED, ST_APPLYING}),
    # Allow a new deploy approval cycle after a prior governed run completed
    ST_COMPLETED: frozenset({ST_PATCH_READY, ST_FAILED}),
    ST_FAILED: frozenset({ST_REQUESTED, ST_PLANNED, ST_INVESTIGATING, ST_PATCH_READY}),
}

APPROVAL_STATUS_PENDING = "pending"
APPROVAL_STATUS_APPROVED = "approved"
APPROVAL_STATUS_DENIED = "denied"
APPROVAL_STATUS_EXPIRED = "expired"
APPROVAL_STATUS_INVALIDATED = "invalidated"

EVENT_PLAN = "plan"
EVENT_ACTION = "action"
EVENT_FINDING = "finding"
EVENT_DECISION = "decision"
EVENT_RESULT = "result"
EVENT_ERROR = "error"

GOVERNANCE_APPROVAL_TTL_MINUTES: dict[str, int] = {
    "low": 30,
    "medium": 20,
    "high": 10,
    "critical": 5,
}


def governance_enforcement_enabled() -> bool:
    raw = (os.environ.get(ENV_GOVERNANCE_ENFORCE) or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def is_production_runtime_for_governance() -> bool:
    """Enforcement applies when stack identifies as AWS deployment."""
    return is_aws()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def compute_manifest_digest(commands: list[dict[str, Any]], scope_summary: str, risk_level: str) -> str:
    """
    SHA256 of canonical JSON for commands + scope + risk.
    Any change to commands or scope invalidates prior approvals.
    """
    canonical = {
        "commands": commands,
        "scope_summary": (scope_summary or "").strip(),
        "risk_level": (risk_level or "medium").strip().lower(),
    }
    body = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    h = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return f"sha256:{h}"


def _ttl_minutes(risk_level: str) -> int:
    r = (risk_level or "medium").strip().lower()
    return GOVERNANCE_APPROVAL_TTL_MINUTES.get(r, GOVERNANCE_APPROVAL_TTL_MINUTES["medium"])


def _mirror_agent_activity_jsonl(envelope: dict[str, Any]) -> None:
    try:
        from app.services.agent_activity_log import log_agent_event
        log_agent_event(
            f"governance_{envelope.get('type', 'event')}",
            task_id=envelope.get("task_id"),
            details={"governance": envelope},
        )
    except Exception as e:
        logger.debug("governance mirror agent_activity.jsonl skipped: %s", e)


def emit_governance_event(
    db: Session,
    *,
    task_id: str,
    event_type: str,
    actor_type: str,
    actor_id: str | None,
    environment: str,
    payload: dict[str, Any],
    mirror_jsonl: bool = True,
) -> str:
    """
    Persist one governance_events row. Returns event_id.

    Payload may include ``signal_hint`` (``failed`` | ``drift`` | ``classification_conflict`` |
    ``blocked``); the timeline API prefers it over pattern derivation. Prefer ``signal_hint=`` on
    ``emit_error_event`` / ``emit_decision_event`` / ``emit_result_event`` when emitting.
    """
    from app.models.governance_models import GovernanceEvent

    event_id = _new_id("evt")
    now = _utcnow()
    row = GovernanceEvent(
        task_id=task_id,
        event_id=event_id,
        ts=now,
        type=event_type,
        actor_type=actor_type,
        actor_id=(actor_id or "")[:255] or None,
        environment=(environment or "prod")[:16],
        payload_json=json.dumps(payload, ensure_ascii=False, default=str),
    )
    db.add(row)
    db.flush()

    envelope = {
        "event_id": event_id,
        "ts": now.isoformat().replace("+00:00", "Z"),
        "task_id": task_id,
        "type": event_type,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "environment": environment,
        "payload": payload,
    }
    if mirror_jsonl:
        _mirror_agent_activity_jsonl(envelope)
    return event_id


def emit_plan_event(
    db: Session,
    *,
    task_id: str,
    actor_type: str,
    actor_id: str | None,
    environment: str,
    summary: str,
    steps: list[str],
    **extra: Any,
) -> str:
    payload = {"summary": summary, "steps": steps, **extra}
    return emit_governance_event(
        db,
        task_id=task_id,
        event_type=EVENT_PLAN,
        actor_type=actor_type,
        actor_id=actor_id,
        environment=environment,
        payload=payload,
    )


def emit_action_event(
    db: Session,
    *,
    task_id: str,
    actor_type: str,
    actor_id: str | None,
    environment: str,
    name: str,
    status: str,
    target: str,
    **extra: Any,
) -> str:
    payload = {"name": name, "status": status, "target": target, **extra}
    return emit_governance_event(
        db,
        task_id=task_id,
        event_type=EVENT_ACTION,
        actor_type=actor_type,
        actor_id=actor_id,
        environment=environment,
        payload=payload,
    )


def emit_finding_event(
    db: Session,
    *,
    task_id: str,
    actor_type: str,
    actor_id: str | None,
    environment: str,
    title: str,
    severity: str,
    evidence: dict[str, Any] | None = None,
) -> str:
    payload = {"title": title, "severity": severity, "evidence": evidence or {}}
    return emit_governance_event(
        db,
        task_id=task_id,
        event_type=EVENT_FINDING,
        actor_type=actor_type,
        actor_id=actor_id,
        environment=environment,
        payload=payload,
    )


def emit_decision_event(
    db: Session,
    *,
    task_id: str,
    actor_type: str,
    actor_id: str | None,
    environment: str,
    decision: str,
    manifest_id: str | None = None,
    notes: str | None = None,
    signal_hint: str | None = None,
    **extra: Any,
) -> str:
    payload = {"decision": decision, "manifest_id": manifest_id, "notes": notes, **extra}
    if signal_hint is not None:
        payload["signal_hint"] = signal_hint
    return emit_governance_event(
        db,
        task_id=task_id,
        event_type=EVENT_DECISION,
        actor_type=actor_type,
        actor_id=actor_id,
        environment=environment,
        payload=payload,
    )


def emit_result_event(
    db: Session,
    *,
    task_id: str,
    actor_type: str,
    actor_id: str | None,
    environment: str,
    outcome: str,
    summary: str,
    signal_hint: str | None = None,
    **extra: Any,
) -> str:
    payload = {"outcome": outcome, "summary": summary, **extra}
    if signal_hint is not None:
        payload["signal_hint"] = signal_hint
    return emit_governance_event(
        db,
        task_id=task_id,
        event_type=EVENT_RESULT,
        actor_type=actor_type,
        actor_id=actor_id,
        environment=environment,
        payload=payload,
    )


def emit_error_event(
    db: Session,
    *,
    task_id: str,
    actor_type: str,
    actor_id: str | None,
    environment: str,
    phase: str,
    message: str,
    retryable: bool = False,
    signal_hint: str | None = None,
    **extra: Any,
) -> str:
    payload = {"phase": phase, "message": message, "retryable": retryable, **extra}
    if signal_hint is not None:
        payload["signal_hint"] = signal_hint
    return emit_governance_event(
        db,
        task_id=task_id,
        event_type=EVENT_ERROR,
        actor_type=actor_type,
        actor_id=actor_id,
        environment=environment,
        payload=payload,
    )


def governance_task_has_plan_event(db: Session, task_id: str) -> bool:
    """True if this governance task already has a persisted ``plan`` timeline row."""
    from app.models.governance_models import GovernanceEvent

    tid = (task_id or "").strip()
    if not tid:
        return False
    return (
        db.query(GovernanceEvent)
        .filter(GovernanceEvent.task_id == tid, GovernanceEvent.type == EVENT_PLAN)
        .first()
        is not None
    )


def emit_visibility_error_if_governance_task_exists(
    db: Session,
    *,
    governance_task_id: str,
    phase: str,
    message: str,
    signal_hint: str,
    actor_type: str = "system",
    actor_id: str = "agent_pipeline",
    environment: str = "prod",
    **extra: Any,
) -> bool:
    """
    Emit a governance ``error`` event for operator timeline when a ``governance_tasks`` row exists.

    Used for agent-path signals (classification conflict, bundle drift, execution blocked) so they
    appear in the unified timeline alongside executor events. Returns ``False`` if the task row is
    missing (callers retain JSONL / logs only). Does not create tasks.
    """
    from app.models.governance_models import GovernanceTask

    tid = (governance_task_id or "").strip()
    if not tid:
        return False
    if db.query(GovernanceTask).filter(GovernanceTask.task_id == tid).first() is None:
        return False
    emit_error_event(
        db,
        task_id=tid,
        actor_type=actor_type,
        actor_id=actor_id,
        environment=environment,
        phase=(phase or "visibility")[:128],
        message=(message or "")[:4000],
        signal_hint=signal_hint,
        **extra,
    )
    return True


def create_governance_task(
    db: Session,
    *,
    task_id: str | None = None,
    source_type: str = "manual",
    source_ref: str | None = None,
    risk_level: str = "medium",
    title: str | None = None,
    actor_type: str = "human",
    actor_id: str | None = None,
    environment: str = "prod",
) -> tuple[str, Any]:
    """Create task in requested state. Returns (task_id, GovernanceTask row)."""
    from app.models.governance_models import GovernanceTask

    tid = (task_id or "").strip() or _new_id("gov")
    row = GovernanceTask(
        task_id=tid,
        source_type=(source_type or "manual")[:64],
        source_ref=(source_ref or "")[:512] or None,
        status=ST_REQUESTED,
        risk_level=(risk_level or "medium")[:16],
    )
    db.add(row)
    db.flush()
    payload: dict[str, Any] = {"title": title} if title else {}
    emit_action_event(
        db,
        task_id=tid,
        actor_type=actor_type,
        actor_id=actor_id,
        environment=environment,
        name="task_created",
        status="completed",
        target="governance_tasks",
        **payload,
    )
    return tid, row


def transition_task_state(
    db: Session,
    *,
    task_id: str,
    to_state: str,
    actor_type: str,
    actor_id: str | None,
    environment: str = "prod",
    reason: str | None = None,
    send_telegram: bool = True,
) -> None:
    """Validate transition, update row, emit action event, optional Telegram for key states."""
    from app.models.governance_models import GovernanceTask

    tid = (task_id or "").strip()
    if not tid:
        raise ValueError("task_id required")
    to_state = (to_state or "").strip()
    if to_state not in ALL_STATES:
        raise ValueError(f"invalid state {to_state!r}")

    row = db.query(GovernanceTask).filter(GovernanceTask.task_id == tid).first()
    if not row:
        raise ValueError(f"unknown task_id {tid!r}")

    fr = (row.status or "").strip()
    allowed = ALLOWED_TRANSITIONS.get(fr, frozenset())
    if to_state not in allowed:
        raise ValueError(f"transition not allowed: {fr!r} -> {to_state!r}")

    row.status = to_state
    row.updated_at = _utcnow()
    db.flush()

    emit_action_event(
        db,
        task_id=tid,
        actor_type=actor_type,
        actor_id=actor_id,
        environment=environment,
        name="state_transition",
        status="completed",
        target="governance_tasks",
        from_state=fr,
        to_state=to_state,
        reason=reason,
    )

    if send_telegram:
        try:
            from app.services.governance_telegram import send_governance_telegram_summary
            if to_state == ST_AWAITING_APPROVAL:
                send_governance_telegram_summary(
                    "awaiting_approval",
                    task_id=tid,
                    lines=[
                        f"State: {ST_AWAITING_APPROVAL}",
                        (reason or "Approval required before PROD execution")[:200],
                    ],
                )
        except Exception as e:
            logger.debug("governance telegram on transition skipped: %s", e)


def create_manifest(
    db: Session,
    *,
    task_id: str,
    commands: list[dict[str, Any]],
    scope_summary: str,
    risk_level: str,
    actor_type: str = "agent",
    actor_id: str | None = None,
    environment: str = "lab",
    attach_and_await_approval: bool = True,
) -> tuple[str, Any]:
    """
    Create manifest with digest. Optionally set task.current_manifest_id and move to awaiting_approval.
    """
    from app.models.governance_models import GovernanceManifest, GovernanceTask

    tid = (task_id or "").strip()
    task = db.query(GovernanceTask).filter(GovernanceTask.task_id == tid).first()
    if not task:
        raise ValueError(f"unknown task_id {tid!r}")

    digest = compute_manifest_digest(commands, scope_summary, risk_level)
    body = json.dumps(commands, ensure_ascii=False, default=str)
    mid = _new_id("mfst")

    row = GovernanceManifest(
        task_id=tid,
        manifest_id=mid,
        digest=digest,
        commands_json=body,
        scope_summary=(scope_summary or "")[:2000],
        risk_level=(risk_level or task.risk_level or "medium")[:16],
        approval_status=APPROVAL_STATUS_PENDING,
    )
    db.add(row)
    db.flush()

    emit_action_event(
        db,
        task_id=tid,
        actor_type=actor_type,
        actor_id=actor_id,
        environment=environment,
        name="manifest_created",
        status="completed",
        target="governance_manifests",
        manifest_id=mid,
        digest=digest,
    )

    if attach_and_await_approval:
        task.current_manifest_id = mid
        task.updated_at = _utcnow()
        st = (task.status or "").strip()
        if st != ST_AWAITING_APPROVAL:
            transition_task_state(
                db,
                task_id=tid,
                to_state=ST_AWAITING_APPROVAL,
                actor_type=actor_type,
                actor_id=actor_id,
                environment=environment,
                reason=f"manifest {mid} attached",
                send_telegram=True,
            )
        else:
            try:
                from app.services.governance_telegram import send_governance_telegram_summary
                send_governance_telegram_summary(
                    "awaiting_approval",
                    task_id=tid,
                    manifest_id=mid,
                    lines=[
                        (scope_summary or "")[:200],
                    ],
                )
            except Exception as e:
                logger.debug("telegram for new manifest skipped: %s", e)

    return mid, row


def invalidate_manifest_if_digest_mismatch(db: Session, manifest_row: Any) -> bool:
    """If stored JSON no longer matches stored digest, mark invalidated. Returns True if invalidated."""
    from app.models.governance_models import GovernanceManifest

    if not manifest_row:
        return False
    try:
        cmds = json.loads(manifest_row.commands_json or "[]")
    except json.JSONDecodeError:
        cmds = []
    expected = compute_manifest_digest(
        cmds if isinstance(cmds, list) else [],
        manifest_row.scope_summary or "",
        manifest_row.risk_level or "medium",
    )
    if expected != manifest_row.digest:
        manifest_row.approval_status = APPROVAL_STATUS_INVALIDATED
        manifest_row.updated_at = _utcnow()
        db.flush()
        emit_error_event(
            db,
            task_id=manifest_row.task_id,
            actor_type="system",
            actor_id="digest_check",
            environment="prod",
            phase="manifest_integrity",
            message="commands_json no longer matches digest; approval invalidated",
            manifest_id=manifest_row.manifest_id,
            signal_hint="failed",
        )
        return True
    return False


def _expire_if_needed(db: Session, manifest_row: Any) -> None:
    exp = _as_utc_aware(manifest_row.expires_at)
    if (
        manifest_row.approval_status == APPROVAL_STATUS_APPROVED
        and exp is not None
        and _utcnow() > exp
    ):
        manifest_row.approval_status = APPROVAL_STATUS_EXPIRED
        manifest_row.updated_at = _utcnow()
        db.flush()
        emit_decision_event(
            db,
            task_id=manifest_row.task_id,
            actor_type="system",
            actor_id="expiry",
            environment="prod",
            decision="expired",
            manifest_id=manifest_row.manifest_id,
            signal_hint="blocked",
        )


def is_manifest_approved_and_valid(db: Session, manifest_id: str, expected_commands: list[dict[str, Any]] | None = None) -> tuple[bool, str]:
    """
    Returns (ok, reason).
    If expected_commands is provided, digest must match that exact list (executor proof).
    """
    from app.models.governance_models import GovernanceManifest

    mid = (manifest_id or "").strip()
    row = db.query(GovernanceManifest).filter(GovernanceManifest.manifest_id == mid).first()
    if not row:
        return False, "manifest not found"

    if invalidate_manifest_if_digest_mismatch(db, row):
        return False, "manifest invalidated (digest mismatch)"

    _expire_if_needed(db, row)
    db.refresh(row)

    if row.approval_status != APPROVAL_STATUS_APPROVED:
        return False, f"not approved (status={row.approval_status})"

    exp = _as_utc_aware(row.expires_at)
    if exp is not None and _utcnow() > exp:
        return False, "approval expired"

    if expected_commands is not None:
        live_digest = compute_manifest_digest(
            expected_commands,
            row.scope_summary or "",
            row.risk_level or "medium",
        )
        if live_digest != row.digest:
            return False, "command list does not match approved digest"

    return True, "ok"


def approve_manifest(
    db: Session,
    *,
    manifest_id: str,
    approved_by: str,
    actor_type: str = "human",
    actor_id: str | None = None,
    environment: str = "prod",
) -> None:
    from app.models.governance_models import GovernanceManifest

    mid = (manifest_id or "").strip()
    row = db.query(GovernanceManifest).filter(GovernanceManifest.manifest_id == mid).first()
    if not row:
        raise ValueError("manifest not found")

    if invalidate_manifest_if_digest_mismatch(db, row):
        raise ValueError("manifest digest integrity failed")

    # Invalidate other approved manifests for same task
    others = (
        db.query(GovernanceManifest)
        .filter(
            GovernanceManifest.task_id == row.task_id,
            GovernanceManifest.manifest_id != mid,
            GovernanceManifest.approval_status == APPROVAL_STATUS_APPROVED,
        )
        .all()
    )
    for o in others:
        o.approval_status = APPROVAL_STATUS_INVALIDATED
        o.updated_at = _utcnow()
        emit_decision_event(
            db,
            task_id=o.task_id,
            actor_type="system",
            actor_id="superseded",
            environment=environment,
            decision="invalidated",
            manifest_id=o.manifest_id,
            notes=f"superseded by approval of {mid}",
            signal_hint="blocked",
        )

    now = _utcnow()
    ttl = _ttl_minutes(row.risk_level or "medium")
    row.approval_status = APPROVAL_STATUS_APPROVED
    row.approved_by = (approved_by or "unknown")[:255]
    row.approved_at = now
    row.expires_at = now + timedelta(minutes=ttl)
    row.updated_at = now
    db.flush()

    emit_decision_event(
        db,
        task_id=row.task_id,
        actor_type=actor_type,
        actor_id=actor_id or approved_by,
        environment=environment,
        decision="approved",
        manifest_id=mid,
        notes=f"ttl_minutes={ttl}",
    )
    try:
        from app.services.governance_telegram import send_governance_telegram_summary
        send_governance_telegram_summary(
            "approved",
            task_id=row.task_id,
            manifest_id=mid,
            lines=[
                f"By: {approved_by}",
                f"Expires: {row.expires_at.isoformat() if row.expires_at else 'n/a'}",
            ],
        )
    except Exception as e:
        logger.debug("governance telegram approve skipped: %s", e)


def deny_manifest(
    db: Session,
    *,
    manifest_id: str,
    denied_by: str,
    reason: str | None = None,
    actor_type: str = "human",
    actor_id: str | None = None,
    environment: str = "prod",
) -> None:
    from app.models.governance_models import GovernanceManifest

    mid = (manifest_id or "").strip()
    row = db.query(GovernanceManifest).filter(GovernanceManifest.manifest_id == mid).first()
    if not row:
        raise ValueError("manifest not found")

    row.approval_status = APPROVAL_STATUS_DENIED
    row.approved_by = (denied_by or "")[:255] or None
    row.approved_at = _utcnow()
    row.updated_at = _utcnow()
    db.flush()

    emit_decision_event(
        db,
        task_id=row.task_id,
        actor_type=actor_type,
        actor_id=actor_id or denied_by,
        environment=environment,
        decision="denied",
        manifest_id=mid,
        notes=reason,
        signal_hint="blocked",
    )
    try:
        from app.services.governance_telegram import send_governance_telegram_summary
        send_governance_telegram_summary(
            "denied",
            task_id=row.task_id,
            manifest_id=mid,
            lines=[(reason or "denied")[:200]],
        )
    except Exception as e:
        logger.debug("governance telegram deny skipped: %s", e)


def prod_mutation_blocked_message(action_name: str) -> str | None:
    """
    If enforcement is on in AWS, return user-facing block message; else None.
    Used by monitoring restart and similar hooks.
    """
    if not governance_enforcement_enabled():
        return None
    if not is_production_runtime_for_governance():
        return None
    return (
        f"{action_name} blocked: ATP_GOVERNANCE_ENFORCE=true on AWS. "
        "Use POST /api/governance/execute with an approved manifest, or disable enforcement in non-prod."
    )
