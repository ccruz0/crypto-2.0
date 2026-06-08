"""Orchestrate Jarvis strategic objectives (human-controlled, read-only)."""

from __future__ import annotations

import logging
from typing import Any, Literal

from app.jarvis.mvp.objective_persistence import (
    LinkedType,
    get_objective,
    record_key_result,
    record_objective,
    record_objective_link,
    record_objective_metric_snapshot,
    update_key_result,
    update_objective,
)

logger = logging.getLogger(__name__)

ObjectiveStatus = Literal["planned", "active", "completed", "cancelled"]
KrDirection = Literal["max", "min"]


def create_objective(
    *,
    title: str,
    description: str = "",
    status: ObjectiveStatus = "planned",
    owner: str | None = None,
    target_date: str | None = None,
) -> dict[str, Any]:
    if not title.strip():
        raise ValueError("title is required")

    objective_id = record_objective(
        title=title.strip(),
        description=description,
        status=status,
        owner=owner,
        target_date=target_date,
    )
    record_objective_metric_snapshot(objective_id=objective_id)

    stored = get_objective(objective_id)
    if stored is None:
        raise RuntimeError("Objective persistence failed")

    logger.info("objective created objective_id=%s status=%s", objective_id, status)
    return stored


def update_objective_record(
    *,
    objective_id: str,
    title: str | None = None,
    description: str | None = None,
    status: ObjectiveStatus | None = None,
    owner: str | None = None,
    target_date: str | None = None,
) -> dict[str, Any]:
    updated = update_objective(
        objective_id=objective_id,
        title=title,
        description=description,
        status=status,
        owner=owner,
        target_date=target_date,
    )
    if not updated:
        raise ValueError(f"Objective not found: {objective_id}")

    record_objective_metric_snapshot(objective_id=objective_id)
    stored = get_objective(objective_id)
    if stored is None:
        raise RuntimeError("Objective retrieval failed after update")
    return stored


def add_key_result(
    *,
    objective_id: str,
    title: str,
    metric_name: str | None = None,
    target_value: float = 0,
    current_value: float = 0,
    unit: str | None = None,
    direction: KrDirection = "max",
) -> dict[str, Any]:
    kr_id = record_key_result(
        objective_id=objective_id,
        title=title,
        metric_name=metric_name,
        target_value=target_value,
        current_value=current_value,
        unit=unit,
        direction=direction,
    )
    record_objective_metric_snapshot(objective_id=objective_id)
    stored = get_objective(objective_id)
    if stored is None:
        raise ValueError(f"Objective not found: {objective_id}")

    kr = next((k for k in stored.get("key_results", []) if k["kr_id"] == kr_id), None)
    if kr is None:
        raise RuntimeError("Key result persistence failed")
    return kr


def update_key_result_record(
    *,
    kr_id: str,
    title: str | None = None,
    current_value: float | None = None,
    target_value: float | None = None,
) -> dict[str, Any]:
    from app.jarvis.mvp.objective_persistence import list_key_results_for_objective
    from sqlalchemy import text
    from app.database import engine, ensure_jarvis_key_results_table

    if engine is None or not ensure_jarvis_key_results_table(engine):
        raise RuntimeError("Database unavailable")

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT objective_id FROM jarvis_key_results WHERE kr_id = :kr_id"),
            {"kr_id": kr_id},
        ).fetchone()
    if row is None:
        raise ValueError(f"Key result not found: {kr_id}")

    objective_id = row._mapping["objective_id"]  # type: ignore[union-attr]
    ok = update_key_result(
        kr_id=kr_id,
        title=title,
        current_value=current_value,
        target_value=target_value,
    )
    if not ok:
        raise ValueError(f"Key result not found: {kr_id}")

    record_objective_metric_snapshot(objective_id=objective_id)
    krs = list_key_results_for_objective(objective_id)
    kr = next((k for k in krs if k["kr_id"] == kr_id), None)
    if kr is None:
        raise RuntimeError("Key result retrieval failed")
    return kr


def link_to_objective(
    *,
    objective_id: str,
    linked_type: LinkedType,
    linked_id: str,
) -> dict[str, Any]:
    link_id = record_objective_link(
        objective_id=objective_id,
        linked_type=linked_type,
        linked_id=linked_id,
    )
    stored = get_objective(objective_id)
    if stored is None:
        raise ValueError(f"Objective not found: {objective_id}")

    link = next(
        (l for l in stored.get("links", []) if l["link_id"] == link_id),
        {"link_id": link_id, "objective_id": objective_id, "linked_type": linked_type, "linked_id": linked_id},
    )
    return link


def refresh_objective_metrics() -> dict[str, Any]:
    """Record metric snapshots for all active objectives."""
    from app.jarvis.mvp.objective_persistence import list_all_objectives

    count = 0
    for obj in list_all_objectives():
        if str(obj.get("status")) in ("cancelled",):
            continue
        if record_objective_metric_snapshot(objective_id=obj["objective_id"]):
            count += 1
    return {"snapshots_recorded": count, "read_only": True, "execution_performed": False}


def seed_sample_objectives() -> dict[str, Any]:
    """Create sample objectives, key results, and initiative links for validation."""
    from datetime import datetime, timedelta, timezone

    from app.jarvis.mvp.initiative_persistence import list_all_initiatives, record_initiative
    from app.jarvis.mvp.objective_persistence import list_all_objectives

    today = datetime.now(timezone.utc).date()
    existing_titles = {o.get("title") for o in list_all_objectives()}
    created: list[dict[str, Any]] = []

    samples = [
        {
            "title": "Reduce AWS spend",
            "description": "Reduce AWS spend by 30% through cost optimization.",
            "status": "active",
            "owner": "Carlos",
            "target_date": (today + timedelta(days=90)).isoformat(),
            "key_results": [
                {
                    "title": "Monthly AWS spend below $120",
                    "metric_name": "aws_monthly_spend",
                    "target_value": 120,
                    "current_value": 0,
                    "unit": "USD",
                    "direction": "min",
                },
                {
                    "title": "Zero unattached EBS volumes",
                    "metric_name": "aws_unattached_ebs_count",
                    "target_value": 0,
                    "current_value": 0,
                    "unit": "count",
                    "direction": "min",
                },
                {
                    "title": "Zero unused Elastic IPs",
                    "metric_name": "aws_unused_eip_count",
                    "target_value": 0,
                    "current_value": 0,
                    "unit": "count",
                    "direction": "min",
                },
            ],
        },
        {
            "title": "Improve portfolio accuracy",
            "description": "Achieve portfolio reconciliation accuracy above 99%.",
            "status": "active",
            "owner": "Carlos",
            "target_date": (today + timedelta(days=60)).isoformat(),
            "key_results": [
                {
                    "title": "Portfolio reconciliation accuracy above 99%",
                    "metric_name": "crypto_reconciliation_accuracy_pct",
                    "target_value": 99,
                    "current_value": 0,
                    "unit": "%",
                    "direction": "max",
                },
                {
                    "title": "Portfolio difference below 1%",
                    "metric_name": "crypto_portfolio_difference_pct",
                    "target_value": 1,
                    "current_value": 0,
                    "unit": "%",
                    "direction": "min",
                },
            ],
        },
        {
            "title": "Improve security posture",
            "description": "Maintain security posture with zero critical findings.",
            "status": "active",
            "owner": "Carlos",
            "target_date": (today + timedelta(days=45)).isoformat(),
            "key_results": [
                {
                    "title": "Zero critical AWS findings",
                    "metric_name": "aws_critical_findings",
                    "target_value": 0,
                    "current_value": 0,
                    "unit": "count",
                    "direction": "min",
                },
                {
                    "title": "Zero critical crypto findings",
                    "metric_name": "crypto_critical_findings",
                    "target_value": 0,
                    "current_value": 0,
                    "unit": "count",
                    "direction": "min",
                },
                {
                    "title": "Zero exposed security groups (0.0.0.0/0)",
                    "metric_name": "aws_open_security_groups",
                    "target_value": 0,
                    "current_value": 0,
                    "unit": "count",
                    "direction": "min",
                },
            ],
        },
    ]

    initiative_by_title = {i.get("title"): i for i in list_all_initiatives()}
    initiative_links = {
        "Reduce AWS spend": "Reduce AWS spend",
        "Improve portfolio accuracy": "Fix portfolio reconciliation",
        "Improve security posture": "Secure exposed security groups",
    }

    for sample in samples:
        if sample["title"] in existing_titles:
            obj = next(o for o in list_all_objectives() if o.get("title") == sample["title"])
            created.append(obj)
            continue

        obj = create_objective(
            title=sample["title"],
            description=sample["description"],
            status=sample["status"],  # type: ignore[arg-type]
            owner=sample["owner"],
            target_date=sample["target_date"],
        )
        for kr in sample["key_results"]:
            add_key_result(
                objective_id=obj["objective_id"],
                title=kr["title"],
                metric_name=kr.get("metric_name"),
                target_value=kr["target_value"],
                current_value=kr["current_value"],
                unit=kr.get("unit"),
                direction=kr.get("direction", "max"),  # type: ignore[arg-type]
            )

        init_title = initiative_links.get(sample["title"])
        initiative = initiative_by_title.get(init_title) if init_title else None
        if initiative is None and init_title:
            iid = record_initiative(
                title=init_title,
                status="active",
                priority="high",
                owner="Carlos",
                source_type="objective",
                source_id=obj["objective_id"],
                progress_pct=int(obj.get("progress_pct") or 0),
            )
            initiative = {"initiative_id": iid}
        if initiative:
            link_to_objective(
                objective_id=obj["objective_id"],
                linked_type="initiative",
                linked_id=initiative["initiative_id"],
            )

        created.append(get_objective(obj["objective_id"]) or obj)

    refresh_objective_metrics()
    return {
        "objectives": created,
        "count": len(created),
        "read_only": True,
        "execution_performed": False,
    }
