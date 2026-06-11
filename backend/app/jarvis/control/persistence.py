"""PostgreSQL/SQLite persistence for Jarvis Control Center tables."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from app.database import engine, ensure_jarvis_control_center_tables
from app.jarvis.control.constants import (
    ACTOR_TYPES,
    APPROVAL_STATUSES,
    CONTROL_DOMAINS,
    CONTROL_ENVIRONMENTS,
    CONTROL_MODES,
    DEFAULT_DOMAIN,
    DEFAULT_ENVIRONMENT,
    DEFAULT_MODE,
    DEFAULT_SESSION_STATUS,
    DEFAULT_TASK_STATUS,
    RISK_LEVELS,
    SESSION_STATUSES,
    TASK_STATUSES,
)

logger = logging.getLogger(__name__)


def _new_session_id() -> str:
    return f"jcs-{uuid.uuid4()}"


def _new_task_id() -> str:
    return f"jcc-{uuid.uuid4()}"


def _new_approval_id() -> str:
    return f"jca-{uuid.uuid4()}"


def _new_event_id() -> str:
    return f"jce-{uuid.uuid4()}"


def _isoformat(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value)


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _json_loads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _ensure_db() -> None:
    if engine is None or not ensure_jarvis_control_center_tables(engine):
        raise RuntimeError("Database unavailable for Jarvis Control Center persistence")


def _normalize_mode(mode: str) -> str:
    m = (mode or DEFAULT_MODE).strip().lower()
    if m not in CONTROL_MODES:
        raise ValueError(f"invalid mode {mode!r}; expected one of {sorted(CONTROL_MODES)}")
    return m


def _normalize_domain(domain: str) -> str:
    d = (domain or DEFAULT_DOMAIN).strip().lower()
    if d not in CONTROL_DOMAINS:
        raise ValueError(f"invalid domain {domain!r}; expected one of {sorted(CONTROL_DOMAINS)}")
    return d


def _normalize_environment(environment: str) -> str:
    e = (environment or DEFAULT_ENVIRONMENT).strip().lower()
    if e not in CONTROL_ENVIRONMENTS:
        raise ValueError(f"invalid environment {environment!r}; expected one of {sorted(CONTROL_ENVIRONMENTS)}")
    return e


def create_control_session(
    *,
    created_by: str,
    default_mode: str = DEFAULT_MODE,
    environment: str = DEFAULT_ENVIRONMENT,
    domain: str = DEFAULT_DOMAIN,
    status: str = DEFAULT_SESSION_STATUS,
    metadata: dict[str, Any] | None = None,
    session_id: str | None = None,
) -> str:
    """Insert a control session row. Returns session_id."""
    _ensure_db()
    sid = (session_id or _new_session_id()).strip()
    if not sid:
        raise ValueError("session_id required")
    st = (status or DEFAULT_SESSION_STATUS).strip().lower()
    if st not in SESSION_STATUSES:
        raise ValueError(f"invalid session status {status!r}")

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO jarvis_control_sessions (
                    session_id, created_by, default_mode, environment, domain,
                    status, metadata_json
                ) VALUES (
                    :session_id, :created_by, :default_mode, :environment, :domain,
                    :status, :metadata_json
                )
                """
            ),
            {
                "session_id": sid,
                "created_by": (created_by or "system")[:255],
                "default_mode": _normalize_mode(default_mode),
                "environment": _normalize_environment(environment),
                "domain": _normalize_domain(domain),
                "status": st,
                "metadata_json": _json_dumps(metadata or {}),
            },
        )
    return sid


def create_control_task(
    *,
    session_id: str,
    prompt: str,
    mode: str = DEFAULT_MODE,
    domain: str = DEFAULT_DOMAIN,
    status: str = DEFAULT_TASK_STATUS,
    risk_level: str = "low",
    dry_run: bool = True,
    plan: list[Any] | None = None,
    tool_results: list[Any] | None = None,
    final_answer: str = "",
    estimated_cost_usd: float | None = None,
    builder_artifact: dict[str, Any] | None = None,
    governance_task_id: str | None = None,
    legacy_task_run_id: str | None = None,
    error: str | None = None,
    task_id: str | None = None,
) -> str:
    """Insert a control task row. Returns task_id."""
    _ensure_db()
    sid = (session_id or "").strip()
    if not sid:
        raise ValueError("session_id required")
    tid = (task_id or _new_task_id()).strip()
    if not tid:
        raise ValueError("task_id required")
    st = (status or DEFAULT_TASK_STATUS).strip().lower()
    if st not in TASK_STATUSES:
        raise ValueError(f"invalid task status {status!r}")
    rl = (risk_level or "low").strip().lower()
    if rl not in RISK_LEVELS:
        raise ValueError(f"invalid risk_level {risk_level!r}")

    artifact_version = 1 if builder_artifact else 0
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO jarvis_control_tasks (
                    task_id, session_id, mode, domain, prompt, status, risk_level, dry_run,
                    plan_json, tool_results_json, final_answer, estimated_cost_usd,
                    builder_artifact_json, artifact_version, artifact_updated_at,
                    governance_task_id, legacy_task_run_id, error
                ) VALUES (
                    :task_id, :session_id, :mode, :domain, :prompt, :status, :risk_level, :dry_run,
                    :plan_json, :tool_results_json, :final_answer, :estimated_cost_usd,
                    :builder_artifact_json, :artifact_version,
                    CASE WHEN :builder_artifact_json IS NOT NULL THEN CURRENT_TIMESTAMP ELSE NULL END,
                    :governance_task_id, :legacy_task_run_id, :error
                )
                """
            ),
            {
                "task_id": tid,
                "session_id": sid,
                "mode": _normalize_mode(mode),
                "domain": _normalize_domain(domain),
                "prompt": prompt or "",
                "status": st,
                "risk_level": rl,
                "dry_run": bool(dry_run),
                "plan_json": _json_dumps(plan if plan is not None else []),
                "tool_results_json": _json_dumps(tool_results if tool_results is not None else []),
                "final_answer": final_answer or "",
                "estimated_cost_usd": estimated_cost_usd,
                "builder_artifact_json": _json_dumps(builder_artifact) if builder_artifact else None,
                "artifact_version": artifact_version,
                "governance_task_id": governance_task_id,
                "legacy_task_run_id": legacy_task_run_id,
                "error": error,
            },
        )
    return tid


def _row_to_task_detail(row: Any) -> dict[str, Any]:
    mapping = row._mapping if hasattr(row, "_mapping") else row
    return {
        "task_id": mapping["task_id"],
        "session_id": mapping["session_id"],
        "mode": mapping["mode"],
        "domain": mapping["domain"],
        "prompt": mapping["prompt"],
        "status": mapping["status"],
        "risk_level": mapping["risk_level"],
        "dry_run": bool(mapping["dry_run"]),
        "plan": _json_loads(mapping.get("plan_json"), []),
        "tool_results": _json_loads(mapping.get("tool_results_json"), []),
        "final_answer": mapping.get("final_answer") or "",
        "estimated_cost_usd": float(mapping["estimated_cost_usd"])
        if mapping.get("estimated_cost_usd") is not None
        else None,
        "builder_artifact": _json_loads(mapping.get("builder_artifact_json"), None),
        "artifact_version": int(mapping.get("artifact_version") or 0),
        "artifact_updated_at": _isoformat(mapping.get("artifact_updated_at")),
        "governance_task_id": mapping.get("governance_task_id"),
        "legacy_task_run_id": mapping.get("legacy_task_run_id"),
        "error": mapping.get("error"),
        "created_at": _isoformat(mapping.get("created_at")),
        "completed_at": _isoformat(mapping.get("completed_at")),
        "updated_at": _isoformat(mapping.get("updated_at")),
    }


def get_control_task(task_id: str) -> dict[str, Any] | None:
    """Return one control task with parsed JSON fields, or None."""
    if engine is None or not ensure_jarvis_control_center_tables(engine):
        return None
    tid = (task_id or "").strip()
    if not tid:
        return None
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM jarvis_control_tasks WHERE task_id = :task_id"),
            {"task_id": tid},
        ).fetchone()
    if row is None:
        return None
    return _row_to_task_detail(row)


def list_control_tasks(
    *,
    session_id: str | None = None,
    mode: str | None = None,
    status: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """List control task summaries, newest first."""
    if engine is None or not ensure_jarvis_control_center_tables(engine):
        return []

    safe_limit = max(1, min(limit, 100))
    clauses = ["1=1"]
    params: dict[str, Any] = {"limit": safe_limit}

    if session_id:
        clauses.append("session_id = :session_id")
        params["session_id"] = session_id.strip()
    if mode:
        clauses.append("mode = :mode")
        params["mode"] = _normalize_mode(mode)
    if status:
        st = status.strip().lower()
        if st not in TASK_STATUSES:
            raise ValueError(f"invalid task status filter {status!r}")
        clauses.append("status = :status")
        params["status"] = st

    where = " AND ".join(clauses)
    sql = f"""
        SELECT task_id, session_id, mode, domain, status, risk_level, dry_run,
               estimated_cost_usd, created_at, completed_at, updated_at
        FROM jarvis_control_tasks
        WHERE {where}
        ORDER BY created_at DESC
        LIMIT :limit
    """
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).fetchall()

    out: list[dict[str, Any]] = []
    for row in rows:
        mapping = row._mapping if hasattr(row, "_mapping") else row
        out.append(
            {
                "task_id": mapping["task_id"],
                "session_id": mapping["session_id"],
                "mode": mapping["mode"],
                "domain": mapping["domain"],
                "status": mapping["status"],
                "risk_level": mapping["risk_level"],
                "dry_run": bool(mapping["dry_run"]),
                "estimated_cost_usd": float(mapping["estimated_cost_usd"])
                if mapping.get("estimated_cost_usd") is not None
                else None,
                "created_at": _isoformat(mapping.get("created_at")),
                "completed_at": _isoformat(mapping.get("completed_at")),
                "updated_at": _isoformat(mapping.get("updated_at")),
            }
        )
    return out


def update_control_task_status(
    task_id: str,
    status: str,
    *,
    error: str | None = None,
    final_answer: str | None = None,
    builder_artifact: dict[str, Any] | None = None,
    completed: bool | None = None,
) -> bool:
    """Update task status and optional fields. Returns True if a row was updated."""
    _ensure_db()
    tid = (task_id or "").strip()
    if not tid:
        return False
    st = (status or "").strip().lower()
    if st not in TASK_STATUSES:
        raise ValueError(f"invalid task status {status!r}")

    set_completed = completed
    if set_completed is None:
        set_completed = st in ("completed", "failed", "cancelled")

    params: dict[str, Any] = {
        "task_id": tid,
        "status": st,
        "error": error,
        "final_answer": final_answer,
        "builder_artifact_json": _json_dumps(builder_artifact) if builder_artifact is not None else None,
        "set_completed": bool(set_completed),
    }

    with engine.begin() as conn:
        result = conn.execute(
            text(
                """
                UPDATE jarvis_control_tasks SET
                    status = :status,
                    error = COALESCE(:error, error),
                    final_answer = COALESCE(:final_answer, final_answer),
                    builder_artifact_json = COALESCE(:builder_artifact_json, builder_artifact_json),
                    completed_at = CASE
                        WHEN :set_completed THEN CURRENT_TIMESTAMP
                        ELSE completed_at
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE task_id = :task_id
                """
            ),
            params,
        )
    return result.rowcount > 0


def persist_builder_artifact(
    task_id: str,
    artifact: dict[str, Any],
    *,
    merge: bool = False,
) -> dict[str, Any] | None:
    """Write builder artifact JSON and bump version. Returns updated task detail or None."""
    _ensure_db()
    tid = (task_id or "").strip()
    if not tid:
        return None
    existing = get_control_task(tid)
    if existing is None or existing.get("mode") != "builder":
        return None

    current_artifact = existing.get("builder_artifact")
    if not isinstance(current_artifact, dict):
        current_artifact = {}
    next_artifact = {**current_artifact, **artifact} if merge else dict(artifact)
    next_version = max(1, int(existing.get("artifact_version") or 0) + 1)

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE jarvis_control_tasks SET
                    builder_artifact_json = :builder_artifact_json,
                    artifact_version = :artifact_version,
                    artifact_updated_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE task_id = :task_id AND mode = 'builder'
                """
            ),
            {
                "task_id": tid,
                "builder_artifact_json": _json_dumps(next_artifact),
                "artifact_version": next_version,
            },
        )
    return get_control_task(tid)


def append_control_audit_event(
    event_type: str,
    *,
    task_id: str | None = None,
    session_id: str | None = None,
    approval_id: str | None = None,
    actor_type: str = "system",
    actor_id: str | None = None,
    environment: str = DEFAULT_ENVIRONMENT,
    payload: dict[str, Any] | None = None,
    event_id: str | None = None,
    ts: datetime | None = None,
) -> str:
    """Append one audit event. Returns event_id."""
    _ensure_db()
    eid = (event_id or _new_event_id()).strip()
    et = (event_type or "").strip()
    if not et:
        raise ValueError("event_type required")
    at = (actor_type or "system").strip().lower()
    if at not in ACTOR_TYPES:
        raise ValueError(f"invalid actor_type {actor_type!r}")

    event_ts = ts or datetime.now(timezone.utc)

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO jarvis_control_audit_events (
                    event_id, task_id, session_id, approval_id, ts, type,
                    actor_type, actor_id, environment, payload_json
                ) VALUES (
                    :event_id, :task_id, :session_id, :approval_id, :ts, :type,
                    :actor_type, :actor_id, :environment, :payload_json
                )
                """
            ),
            {
                "event_id": eid,
                "task_id": (task_id or "").strip() or None,
                "session_id": (session_id or "").strip() or None,
                "approval_id": (approval_id or "").strip() or None,
                "ts": event_ts,
                "type": et[:64],
                "actor_type": at,
                "actor_id": (actor_id or "")[:255] or None,
                "environment": _normalize_environment(environment),
                "payload_json": _json_dumps(payload or {}),
            },
        )
    return eid


class ControlTaskTransitionError(ValueError):
    """Raised when a control task status transition is not allowed."""


def _row_to_approval(row: Any) -> dict[str, Any]:
    mapping = row._mapping if hasattr(row, "_mapping") else row
    return {
        "approval_id": mapping["approval_id"],
        "task_id": mapping["task_id"],
        "action_id": mapping.get("action_id"),
        "approval_status": mapping["approval_status"],
        "execution_status": mapping.get("execution_status") or "not_executed",
        "risk_level": mapping.get("risk_level") or "medium",
        "scope_summary": mapping.get("scope_summary"),
        "digest": mapping.get("digest"),
        "allowed_envs": mapping.get("allowed_envs"),
        "requested_by": mapping.get("requested_by") or "jarvis",
        "approved_by": mapping.get("approved_by"),
        "approved_at": _isoformat(mapping.get("approved_at")),
        "comment": mapping.get("comment"),
        "expires_at": _isoformat(mapping.get("expires_at")),
        "governance_manifest_id": mapping.get("governance_manifest_id"),
        "created_at": _isoformat(mapping.get("created_at")),
        "updated_at": _isoformat(mapping.get("updated_at")),
    }


def get_control_approvals(task_id: str) -> list[dict[str, Any]]:
    """Return approval rows for a control task, newest first."""
    if engine is None or not ensure_jarvis_control_center_tables(engine):
        return []
    tid = (task_id or "").strip()
    if not tid:
        return []
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT * FROM jarvis_control_approvals
                WHERE task_id = :task_id
                ORDER BY created_at DESC
                """
            ),
            {"task_id": tid},
        ).fetchall()
    return [_row_to_approval(row) for row in rows]


def transition_control_task_status(
    task_id: str,
    *,
    expected_status: str,
    new_status: str,
    completed: bool | None = None,
) -> bool:
    """Atomically update task status when current status matches expected."""
    _ensure_db()
    tid = (task_id or "").strip()
    if not tid:
        return False
    expected = (expected_status or "").strip().lower()
    new_st = (new_status or "").strip().lower()
    if new_st not in TASK_STATUSES:
        raise ValueError(f"invalid task status {new_status!r}")

    set_completed = completed
    if set_completed is None:
        set_completed = new_st in ("completed", "failed", "cancelled", "approved", "rejected")

    with engine.begin() as conn:
        result = conn.execute(
            text(
                """
                UPDATE jarvis_control_tasks SET
                    status = :new_status,
                    completed_at = CASE
                        WHEN :set_completed THEN CURRENT_TIMESTAMP
                        ELSE completed_at
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE task_id = :task_id AND status = :expected_status
                """
            ),
            {
                "task_id": tid,
                "expected_status": expected,
                "new_status": new_st,
                "set_completed": bool(set_completed),
            },
        )
    return result.rowcount > 0


def insert_builder_approval_decision(
    task_id: str,
    *,
    decision: str,
    actor_id: str,
    comment: str | None,
    risk_level: str,
    expected_task_status: str,
) -> dict[str, Any]:
    """Insert approval row and transition task status in one transaction."""
    _ensure_db()
    tid = (task_id or "").strip()
    if not tid:
        raise ValueError("task_id required")
    decision_status = (decision or "").strip().lower()
    if decision_status not in ("approved", "rejected"):
        raise ValueError(f"invalid approval decision {decision!r}")

    actor = (actor_id or "dashboard").strip() or "dashboard"
    approval_id = _new_approval_id()
    comment_text = (comment or "").strip() or None
    rl = (risk_level or "medium").strip().lower()
    expected = (expected_task_status or "").strip().lower()

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO jarvis_control_approvals (
                    approval_id, task_id, approval_status, execution_status,
                    risk_level, scope_summary, requested_by, approved_by, approved_at, comment
                ) VALUES (
                    :approval_id, :task_id, :approval_status, 'not_executed',
                    :risk_level, :scope_summary, :requested_by, :approved_by, CURRENT_TIMESTAMP, :comment
                )
                """
            ),
            {
                "approval_id": approval_id,
                "task_id": tid,
                "approval_status": decision_status,
                "risk_level": rl,
                "scope_summary": f"Builder task {decision_status} by {actor}"[:2000],
                "requested_by": actor,
                "approved_by": actor,
                "comment": comment_text,
            },
        )
        result = conn.execute(
            text(
                """
                UPDATE jarvis_control_tasks SET
                    status = :new_status,
                    completed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE task_id = :task_id AND status = :expected_status
                """
            ),
            {
                "task_id": tid,
                "new_status": decision_status,
                "expected_status": expected,
            },
        )
        if result.rowcount != 1:
            raise ControlTaskTransitionError(f"task status changed during {decision_status}")

    approvals = get_control_approvals(tid)
    return approvals[0] if approvals else {"approval_id": approval_id, "task_id": tid}


def get_builder_workflow_context(task_id: str) -> dict[str, Any] | None:
    """Fetch builder task, approvals, and audit timeline in bounded queries."""
    task = get_control_task(task_id)
    if task is None or task.get("mode") != "builder":
        return None
    approvals = get_control_approvals(task_id)
    audit_events = list_control_audit_events(task_id=task_id, limit=200)
    timeline_entries: list[dict[str, Any]] = []
    seen_approval_ids: set[str] = set()

    for event in audit_events:
        approval_id = event.get("approval_id")
        if approval_id:
            seen_approval_ids.add(approval_id)
        timeline_entries.append(
            {
                "kind": "audit",
                "ts": event.get("ts"),
                "type": event.get("type"),
                "actor_type": event.get("actor_type"),
                "actor_id": event.get("actor_id"),
                "event_id": event.get("event_id"),
                "approval_id": approval_id,
                "payload": event.get("payload") or {},
            }
        )

    for approval in approvals:
        approval_id = approval.get("approval_id")
        if approval_id and approval_id in seen_approval_ids:
            continue
        timeline_entries.append(
            {
                "kind": "approval",
                "ts": approval.get("approved_at") or approval.get("created_at"),
                "type": f"approval_{approval.get('approval_status')}",
                "actor_type": "human",
                "actor_id": approval.get("approved_by") or approval.get("requested_by"),
                "approval_id": approval_id,
                "payload": {
                    "approval_status": approval.get("approval_status"),
                    "comment": approval.get("comment"),
                },
            }
        )

    timeline_entries.sort(key=lambda item: item.get("ts") or "", reverse=True)
    return {
        "task": task,
        "approvals": approvals,
        "timeline_entries": timeline_entries,
    }


def approve_control_task(
    task_id: str,
    *,
    actor_id: str,
    comment: str | None = None,
) -> dict[str, Any]:
    """Record dashboard approval for a builder task (delegates to workflow)."""
    from app.jarvis.control import workflow as wfl

    try:
        return wfl.approve_builder_task(task_id, actor_id=actor_id, comment=comment)
    except wfl.BuilderWorkflowNotFoundError as exc:
        raise LookupError(str(exc)) from exc
    except wfl.BuilderWorkflowConflictError as exc:
        raise ControlTaskTransitionError(str(exc)) from exc


def reject_control_task(
    task_id: str,
    *,
    actor_id: str,
    comment: str | None = None,
) -> dict[str, Any]:
    """Record dashboard rejection for a builder task (delegates to workflow)."""
    from app.jarvis.control import workflow as wfl

    try:
        return wfl.reject_builder_task(task_id, actor_id=actor_id, comment=comment)
    except wfl.BuilderWorkflowNotFoundError as exc:
        raise LookupError(str(exc)) from exc
    except wfl.BuilderWorkflowConflictError as exc:
        raise ControlTaskTransitionError(str(exc)) from exc


def create_control_approval(
    *,
    task_id: str,
    scope_summary: str = "",
    risk_level: str = "medium",
    digest: str | None = None,
    allowed_envs: str | None = None,
    requested_by: str = "jarvis",
    action_id: str | None = None,
    approval_status: str = "pending",
    expires_at: datetime | None = None,
    governance_manifest_id: str | None = None,
    approval_id: str | None = None,
) -> str:
    """Insert a pending approval row. Returns approval_id."""
    _ensure_db()
    tid = (task_id or "").strip()
    if not tid:
        raise ValueError("task_id required")
    aid = (approval_id or _new_approval_id()).strip()
    ap = (approval_status or "pending").strip().lower()
    if ap not in APPROVAL_STATUSES:
        raise ValueError(f"invalid approval_status {approval_status!r}")
    rl = (risk_level or "medium").strip().lower()
    if rl not in RISK_LEVELS:
        raise ValueError(f"invalid risk_level {risk_level!r}")

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO jarvis_control_approvals (
                    approval_id, task_id, action_id, approval_status, execution_status,
                    risk_level, scope_summary, digest, allowed_envs, requested_by,
                    expires_at, governance_manifest_id
                ) VALUES (
                    :approval_id, :task_id, :action_id, :approval_status, 'not_executed',
                    :risk_level, :scope_summary, :digest, :allowed_envs, :requested_by,
                    :expires_at, :governance_manifest_id
                )
                """
            ),
            {
                "approval_id": aid,
                "task_id": tid,
                "action_id": action_id,
                "approval_status": ap,
                "risk_level": rl,
                "scope_summary": (scope_summary or "")[:2000],
                "digest": digest,
                "allowed_envs": allowed_envs,
                "requested_by": (requested_by or "jarvis")[:255],
                "expires_at": expires_at,
                "governance_manifest_id": governance_manifest_id,
            },
        )
    return aid


def _row_to_audit_event(row: Any) -> dict[str, Any]:
    mapping = row._mapping if hasattr(row, "_mapping") else row
    return {
        "event_id": mapping["event_id"],
        "task_id": mapping.get("task_id"),
        "session_id": mapping.get("session_id"),
        "approval_id": mapping.get("approval_id"),
        "ts": _isoformat(mapping.get("ts")),
        "type": mapping["type"],
        "actor_type": mapping["actor_type"],
        "actor_id": mapping.get("actor_id"),
        "environment": mapping["environment"],
        "payload": _json_loads(mapping.get("payload_json"), {}),
        "created_at": _isoformat(mapping.get("created_at")),
    }


def list_control_audit_events(
    *,
    task_id: str | None = None,
    session_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List audit events, newest first."""
    if engine is None or not ensure_jarvis_control_center_tables(engine):
        return []

    safe_limit = max(1, min(limit, 200))
    clauses = ["1=1"]
    params: dict[str, Any] = {"limit": safe_limit}

    if task_id:
        clauses.append("task_id = :task_id")
        params["task_id"] = task_id.strip()
    if session_id:
        clauses.append("session_id = :session_id")
        params["session_id"] = session_id.strip()

    where = " AND ".join(clauses)
    sql = f"""
        SELECT * FROM jarvis_control_audit_events
        WHERE {where}
        ORDER BY ts DESC
        LIMIT :limit
    """
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).fetchall()
    return [_row_to_audit_event(row) for row in rows]
