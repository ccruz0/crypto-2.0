"""Orchestrate Jarvis initiative CRUD (human-controlled, read-only management layer)."""

from __future__ import annotations

import logging
from typing import Any, Literal

from app.jarvis.mvp.initiative_persistence import (
    get_initiative,
    record_initiative,
    update_initiative,
)

logger = logging.getLogger(__name__)

InitiativeStatus = Literal["planned", "active", "blocked", "completed", "cancelled"]
InitiativePriority = Literal["critical", "high", "medium", "low"]


def create_initiative(
    *,
    title: str,
    description: str = "",
    status: InitiativeStatus = "planned",
    priority: InitiativePriority = "medium",
    owner: str | None = None,
    target_date: str | None = None,
    source_type: str | None = None,
    source_id: str | None = None,
    progress_pct: int = 0,
    blocked_reason: str | None = None,
) -> dict[str, Any]:
    """Create a new initiative. No autonomous execution."""
    if not title.strip():
        raise ValueError("title is required")

    if status == "blocked" and not blocked_reason:
        blocked_reason = "Awaiting resolution"

    initiative_id = record_initiative(
        title=title.strip(),
        description=description,
        status=status,
        priority=priority,
        owner=owner,
        target_date=target_date,
        source_type=source_type or "manual",
        source_id=source_id,
        progress_pct=progress_pct,
        blocked_reason=blocked_reason,
    )

    stored = get_initiative(initiative_id)
    if stored is None:
        raise RuntimeError("Initiative persistence failed")

    logger.info(
        "initiative created initiative_id=%s status=%s priority=%s",
        initiative_id,
        status,
        priority,
    )
    return stored


def update_initiative_record(
    *,
    initiative_id: str,
    title: str | None = None,
    description: str | None = None,
    status: InitiativeStatus | None = None,
    priority: InitiativePriority | None = None,
    owner: str | None = None,
    target_date: str | None = None,
    source_type: str | None = None,
    source_id: str | None = None,
    progress_pct: int | None = None,
    blocked_reason: str | None = None,
) -> dict[str, Any]:
    """Update an existing initiative. Recalculates health automatically."""
    clear_blocked = status is not None and status != "blocked"

    updated = update_initiative(
        initiative_id=initiative_id,
        title=title,
        description=description,
        status=status,
        priority=priority,
        owner=owner,
        target_date=target_date,
        source_type=source_type,
        source_id=source_id,
        progress_pct=progress_pct,
        blocked_reason=blocked_reason,
        clear_blocked_reason=clear_blocked,
    )
    if not updated:
        raise ValueError(f"Initiative not found: {initiative_id}")

    stored = get_initiative(initiative_id)
    if stored is None:
        raise RuntimeError("Initiative retrieval failed after update")

    logger.info("initiative updated initiative_id=%s status=%s", initiative_id, stored.get("status"))
    return stored


def seed_sample_initiatives() -> list[dict[str, Any]]:
    """Create sample initiatives for validation (idempotent by title check)."""
    from datetime import datetime, timedelta, timezone

    from app.jarvis.mvp.initiative_persistence import list_all_initiatives

    today = datetime.now(timezone.utc).date()
    existing_titles = {i.get("title") for i in list_all_initiatives()}
    samples = [
        {
            "title": "Fix portfolio reconciliation",
            "description": "Resolve balance mismatch between exchange and dashboard portfolio values.",
            "status": "active",
            "priority": "critical",
            "owner": "Carlos",
            "target_date": (today + timedelta(days=-11)).isoformat(),
            "source_type": "crypto_audit",
            "progress_pct": 35,
        },
        {
            "title": "Secure exposed security groups",
            "description": "Review and restrict security groups with 0.0.0.0/0 ingress.",
            "status": "blocked",
            "priority": "high",
            "owner": "Carlos",
            "target_date": (today + timedelta(days=14)).isoformat(),
            "source_type": "aws_audit",
            "progress_pct": 10,
            "blocked_reason": "Awaiting change window approval",
        },
        {
            "title": "Reduce AWS spend",
            "description": "Remove unattached EBS volumes and release unused Elastic IPs.",
            "status": "active",
            "priority": "medium",
            "owner": "Carlos",
            "target_date": (today + timedelta(days=30)).isoformat(),
            "source_type": "aws_audit",
            "progress_pct": 60,
        },
        {
            "title": "Improve dashboard accuracy",
            "description": "Validate price feeds and refresh stale portfolio cache.",
            "status": "planned",
            "priority": "medium",
            "owner": "Carlos",
            "progress_pct": 0,
            "source_type": "manual",
        },
        {
            "title": "Complete crypto audit rollout",
            "description": "Establish weekly crypto audit cadence and reconciliation checks.",
            "status": "completed",
            "priority": "low",
            "owner": "Carlos",
            "progress_pct": 100,
            "source_type": "manual",
        },
    ]

    created: list[dict[str, Any]] = []
    for sample in samples:
        if sample["title"] in existing_titles:
            continue
        created.append(create_initiative(**sample))
    return created
