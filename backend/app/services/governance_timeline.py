"""
Read-only governance task timeline (control-plane view model).

Aggregates existing rows only — no new source of truth. See docs/governance/CONTROL_PLANE_TASK_VIEW.md.
"""

from __future__ import annotations

import json
import re
from typing import Any

# Read-model signal labels (timeline API + UI). Not lifecycle state — derived from payloads/types only.
TIMELINE_SIGNAL_FAILED = "failed"
TIMELINE_SIGNAL_DRIFT = "drift"
TIMELINE_SIGNAL_CLASSIFICATION_CONFLICT = "classification_conflict"
TIMELINE_SIGNAL_BLOCKED = "blocked"

_SIGNAL_COUNT_KEYS = (
    TIMELINE_SIGNAL_FAILED,
    TIMELINE_SIGNAL_DRIFT,
    TIMELINE_SIGNAL_CLASSIFICATION_CONFLICT,
    TIMELINE_SIGNAL_BLOCKED,
)

_VALID_SIGNAL_HINTS = frozenset(_SIGNAL_COUNT_KEYS)

# Stored on governance_events.payload_json; timeline prefers this over pattern derivation.
PAYLOAD_SIGNAL_HINT_KEY = "signal_hint"

from sqlalchemy.orm import Session

from app.services.governance_agent_bridge import notion_to_governance_task_id
from app.services.governance_service import (
    EVENT_ACTION,
    EVENT_DECISION,
    EVENT_ERROR,
    EVENT_FINDING,
    EVENT_PLAN,
    EVENT_RESULT,
    ST_APPLYING,
    ST_AWAITING_APPROVAL,
    ST_COMPLETED,
    ST_FAILED,
    ST_INVESTIGATING,
    ST_PLANNED,
    ST_REQUESTED,
    ST_VALIDATING,
)

GOV_NOTION_PREFIX = "gov-notion-"


def notion_page_id_from_governance_task_id(governance_task_id: str) -> str | None:
    """Extract Notion page id when task_id uses ``gov-notion-<page_id>``."""
    tid = (governance_task_id or "").strip()
    if tid.startswith(GOV_NOTION_PREFIX):
        return tid[len(GOV_NOTION_PREFIX) :].strip() or None
    return None


def _hash_prefix(value: str | None, *, hex_chars: int = 14) -> str | None:
    """Shorten sha256:… digests for display; returns None if missing."""
    if not value or not isinstance(value, str):
        return None
    v = value.strip()
    if v.startswith("sha256:"):
        hx = v[7:]
        if len(hx) <= hex_chars:
            return v
        return f"sha256:{hx[:hex_chars]}…"
    if len(v) <= 24:
        return v
    return v[:24] + "…"


def _safe_json_obj(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        out = json.loads(raw)
        return out if isinstance(out, dict) else {}
    except json.JSONDecodeError:
        return {}


def _phase_for_event(
    event_type: str,
    payload: dict[str, Any],
    task_current_status: str,
) -> str:
    if event_type == EVENT_PLAN:
        return ST_PLANNED
    if event_type == EVENT_FINDING:
        return ST_INVESTIGATING
    if event_type == EVENT_DECISION:
        return ST_AWAITING_APPROVAL
    if event_type == EVENT_ERROR:
        return ST_FAILED
    if event_type == EVENT_RESULT:
        out = payload.get("outcome")
        if out is True or str(out).lower() in ("success", "ok", "completed"):
            return ST_COMPLETED
        if payload.get("success") is True:
            return ST_COMPLETED
        return ST_VALIDATING
    if event_type == EVENT_ACTION:
        name = (payload.get("name") or "").strip().lower()
        if name == "state_transition":
            return (payload.get("to_state") or task_current_status or ST_REQUESTED).strip()
        if name == "task_created":
            return ST_REQUESTED
        if "manifest" in name or payload.get("manifest_id"):
            return ST_AWAITING_APPROVAL
        if name in ("execute_step", "governed_execute", "executor"):
            return ST_APPLYING
        return ST_APPLYING
    return (task_current_status or ST_REQUESTED).strip()


def _summary_for_event(event_type: str, payload: dict[str, Any]) -> str:
    if event_type == EVENT_PLAN:
        return (payload.get("summary") or "plan")[:500]
    if event_type == EVENT_FINDING:
        return (payload.get("title") or "finding")[:500]
    if event_type == EVENT_DECISION:
        d = payload.get("decision") or "decision"
        mid = payload.get("manifest_id") or ""
        return f"{d}" + (f" manifest={mid}" if mid else "")
    if event_type == EVENT_RESULT:
        return (payload.get("summary") or payload.get("outcome") or "result")[:500]
    if event_type == EVENT_ERROR:
        return (payload.get("message") or payload.get("error") or "error")[:500]
    if event_type == EVENT_ACTION:
        name = payload.get("name") or "action"
        st = payload.get("status") or ""
        return f"{name} ({st})"[:500]
    return event_type


def derive_timeline_event_signal(
    event_type: str,
    phase: str,
    payload: dict[str, Any],
    summary_text: str,
) -> str | None:
    """
    Single primary signal per event for control-plane UI (read model).

    Priority: failed > classification_conflict > drift > blocked.
    Uses the same payload surface area the UI previously scanned client-side.
    """
    try:
        payload_json = json.dumps(payload, ensure_ascii=False, default=str).lower()
    except (TypeError, ValueError):
        payload_json = ""
    st = (summary_text or "").lower()
    et = (event_type or "").strip().lower()
    ph = (phase or "").strip().lower()
    blob = f"{st} {et} {ph} {payload_json}"

    if et == EVENT_ERROR or ph == ST_FAILED.lower() or re.search(r"\bfailed\b", blob):
        return TIMELINE_SIGNAL_FAILED
    if re.search(
        r"classification_conflict|governance_classification_conflict|conflicting classification",
        blob,
    ):
        return TIMELINE_SIGNAL_CLASSIFICATION_CONFLICT
    if re.search(r"bundle_drift|governance_bundle_drift|drift_detected|bundle drift", blob):
        return TIMELINE_SIGNAL_DRIFT
    if re.search(
        r"governance_execution_blocked|prod_mutation_blocked|execution_blocked|blocked_send_task_approval",
        blob,
    ) or re.search(r"\bblocked\b", blob):
        return TIMELINE_SIGNAL_BLOCKED
    return None


def resolve_timeline_event_signal(
    event_type: str,
    phase: str,
    payload: dict[str, Any],
    summary_text: str,
) -> str | None:
    """
    Effective signal for one event: explicit ``payload['signal_hint']`` when valid,
    else :func:`derive_timeline_event_signal` (backward compatible for older rows).
    """
    hint = payload.get(PAYLOAD_SIGNAL_HINT_KEY)
    if isinstance(hint, str):
        h = hint.strip().lower()
        if h in _VALID_SIGNAL_HINTS:
            return h
    return derive_timeline_event_signal(event_type, phase, payload, summary_text)


def _empty_signal_counts() -> dict[str, int]:
    return {k: 0 for k in _SIGNAL_COUNT_KEYS}


def _compact_payload(payload: dict[str, Any], max_keys: int = 12) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for i, (k, v) in enumerate(payload.items()):
        if i >= max_keys:
            out["_truncated"] = True
            break
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v
        elif isinstance(v, dict) and len(json.dumps(v)) < 400:
            out[k] = v
        elif isinstance(v, list) and len(v) < 8:
            out[k] = v
        else:
            out[k] = f"<{type(v).__name__}>"
    return out


def _links_for_event(
    payload: dict[str, Any],
    *,
    governance_task_id: str,
    notion_page_id: str | None,
    digest_by_manifest_id: dict[str, str],
) -> dict[str, Any]:
    links: dict[str, Any] = {
        "governance_task_id": governance_task_id,
        "notion_page_id": notion_page_id,
    }
    mid = payload.get("manifest_id") or payload.get("approved_manifest_id")
    if mid:
        links["manifest_id"] = str(mid)
        d = digest_by_manifest_id.get(str(mid))
        if d:
            links["manifest_digest_prefix"] = _hash_prefix(d)
    audit = payload.get("audit")
    if isinstance(audit, dict):
        bf = audit.get("bundle_fingerprint")
        if bf:
            links["bundle_fingerprint_prefix"] = _hash_prefix(str(bf))
    bf2 = payload.get("bundle_fingerprint")
    if bf2 and "bundle_fingerprint_prefix" not in links:
        links["bundle_fingerprint_prefix"] = _hash_prefix(str(bf2))
    return {k: v for k, v in links.items() if v is not None}


def _manifest_row_public(m: Any) -> dict[str, Any]:
    bundle_fp_prefix = None
    try:
        cmds = json.loads(m.commands_json or "[]")
        if isinstance(cmds, list) and cmds and isinstance(cmds[0], dict):
            audit = cmds[0].get("audit") or {}
            if isinstance(audit, dict) and audit.get("bundle_fingerprint"):
                bundle_fp_prefix = _hash_prefix(str(audit.get("bundle_fingerprint")))
    except (json.JSONDecodeError, TypeError):
        pass
    return {
        "manifest_id": m.manifest_id,
        "digest": m.digest,
        "digest_prefix": _hash_prefix(m.digest),
        "approval_status": m.approval_status,
        "scope_summary": (m.scope_summary or "")[:500] or None,
        "risk_level": m.risk_level,
        "approved_by": m.approved_by,
        "approved_at": m.approved_at.isoformat() if m.approved_at else None,
        "expires_at": m.expires_at.isoformat() if m.expires_at else None,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "bundle_fingerprint_prefix": bundle_fp_prefix,
    }


def _agent_bundle_summary(row: Any) -> dict[str, Any]:
    bundle = _safe_json_obj(getattr(row, "prepared_bundle_json", None))
    fp = bundle.get("bundle_fingerprint")
    ident = bundle.get("bundle_identity") if isinstance(bundle.get("bundle_identity"), dict) else {}
    return {
        "notion_task_id": row.task_id,
        "approval_row_status": row.status,
        "execution_status": row.execution_status,
        "bundle_fingerprint": fp,
        "bundle_fingerprint_prefix": _hash_prefix(fp) if fp else None,
        "governance_action_class": bundle.get("governance_action_class"),
        "selection_reason": ident.get("selection_reason") if isinstance(ident, dict) else None,
    }


def _timeline_scope(
    *,
    notion_linked: bool,
    agent_bundle_present: bool,
    has_events: bool,
    has_manifests: bool,
) -> str:
    if notion_linked and agent_bundle_present:
        return "full"
    if notion_linked:
        return "partial"
    if not has_events and not has_manifests:
        return "partial"
    return "governed_only"


def build_governance_timeline(db: Session, governance_task_id: str) -> dict[str, Any] | None:
    """
    Build a read-only timeline for one governance task.

    Returns None if the governance task row does not exist.
    """
    from app.models.agent_approval_state import AgentApprovalState
    from app.models.governance_models import GovernanceEvent, GovernanceManifest, GovernanceTask

    tid = (governance_task_id or "").strip()
    if not tid:
        return None

    task = db.query(GovernanceTask).filter(GovernanceTask.task_id == tid).first()
    if not task:
        return None

    notion_page_id = notion_page_id_from_governance_task_id(tid)

    manifests = (
        db.query(GovernanceManifest)
        .filter(GovernanceManifest.task_id == tid)
        .order_by(GovernanceManifest.created_at.asc())
        .all()
    )
    digest_by_manifest_id = {m.manifest_id: m.digest for m in manifests}

    events = (
        db.query(GovernanceEvent)
        .filter(GovernanceEvent.task_id == tid)
        .order_by(GovernanceEvent.ts.asc())
        .all()
    )

    agent_row = None
    if notion_page_id:
        agent_row = (
            db.query(AgentApprovalState).filter(AgentApprovalState.task_id == notion_page_id).first()
        )

    agent_bundle_present = agent_row is not None
    agent_bundle = _agent_bundle_summary(agent_row) if agent_row else None

    notion_linked = notion_page_id is not None
    has_events = len(events) > 0
    has_manifests = len(manifests) > 0

    task_status = (task.status or ST_REQUESTED).strip()

    timeline: list[dict[str, Any]] = []
    signal_counts = _empty_signal_counts()
    for ev in events:
        payload = _safe_json_obj(ev.payload_json)
        phase = _phase_for_event(ev.type, payload, task_status)
        summary = _summary_for_event(ev.type, payload)
        sig = resolve_timeline_event_signal(ev.type, phase, payload, summary)
        if sig in signal_counts:
            signal_counts[sig] += 1
        item = {
            "ts": ev.ts.isoformat() if ev.ts else None,
            "phase": phase,
            "event_type": ev.type,
            "source": "governance_events",
            "actor": {"type": ev.actor_type, "id": ev.actor_id},
            "environment": ev.environment,
            "summary": summary,
            "signal": sig,
            "links": _links_for_event(
                payload,
                governance_task_id=tid,
                notion_page_id=notion_page_id,
                digest_by_manifest_id=digest_by_manifest_id,
            ),
            "payload_ref": f"governance_events:{ev.event_id}",
            "compact_payload": _compact_payload(payload),
        }
        timeline.append(item)

    scope = _timeline_scope(
        notion_linked=notion_linked,
        agent_bundle_present=agent_bundle_present,
        has_events=has_events,
        has_manifests=has_manifests,
    )

    return {
        "correlation_id": tid,
        "governance_task_id": tid,
        "notion_page_id": notion_page_id,
        "current_status": task_status,
        "risk_level": task.risk_level,
        "source_type": task.source_type,
        "source_ref": task.source_ref,
        "current_manifest_id": task.current_manifest_id,
        "task_created_at": task.created_at.isoformat() if task.created_at else None,
        "task_updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "coverage": {
            "governance_task_present": True,
            "agent_bundle_present": agent_bundle_present,
            "notion_linked": notion_linked,
            "has_manifests": has_manifests,
            "has_events": has_events,
            "timeline_scope": scope,
        },
        "manifests": [_manifest_row_public(m) for m in manifests],
        "agent_bundle": agent_bundle,
        "signal_counts": signal_counts,
        "timeline": timeline,
    }


def build_governance_timeline_for_notion(db: Session, notion_page_id: str) -> dict[str, Any] | None:
    """Resolve Notion page id to ``gov-notion-<page_id>`` and build timeline."""
    nid = (notion_page_id or "").strip()
    if not nid:
        return None
    gid = notion_to_governance_task_id(nid)
    return build_governance_timeline(db, gid)
