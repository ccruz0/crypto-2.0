"""
Read-only resolver: map governance_task_id, notion_page_id, or manifest_id to timeline handles.

Uses existing tables only — no second source of truth.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.governance_models import GovernanceManifest, GovernanceTask
from app.services.governance_agent_bridge import notion_to_governance_task_id
from app.services.governance_refs import timeline_paths_and_urls
from app.services.governance_timeline import notion_page_id_from_governance_task_id


def resolve_governance_task(
    db: Session,
    *,
    governance_task_id: str | None = None,
    notion_page_id: str | None = None,
    manifest_id: str | None = None,
) -> dict[str, Any] | None:
    """
    Resolve exactly one identifier to task row + manifest hints + timeline paths.

    Returns None if the governing row cannot be found (caller maps to 404).
    """
    gid_in = (governance_task_id or "").strip() or None
    nid_in = (notion_page_id or "").strip() or None
    mid_in = (manifest_id or "").strip() or None
    n_provided = sum(1 for x in (gid_in, nid_in, mid_in) if x)
    if n_provided != 1:
        raise ValueError("provide exactly one of task_id, notion_page_id, manifest_id")

    gid: str
    if gid_in:
        gid = gid_in
    elif nid_in:
        gid = notion_to_governance_task_id(nid_in)
    else:
        mrow = db.query(GovernanceManifest).filter(GovernanceManifest.manifest_id == mid_in).first()
        if not mrow:
            return None
        gid = mrow.task_id

    task = db.query(GovernanceTask).filter(GovernanceTask.task_id == gid).first()
    if not task:
        return None

    latest = (
        db.query(GovernanceManifest)
        .filter(GovernanceManifest.task_id == gid)
        .order_by(GovernanceManifest.created_at.desc())
        .first()
    )
    notion_out = notion_page_id_from_governance_task_id(gid)
    paths = timeline_paths_and_urls(gid, notion_out)

    return {
        "governance_task_id": gid,
        "notion_page_id": notion_out,
        "current_status": task.status,
        "current_manifest_id": task.current_manifest_id,
        "latest_manifest_id": latest.manifest_id if latest else None,
        **paths,
    }
