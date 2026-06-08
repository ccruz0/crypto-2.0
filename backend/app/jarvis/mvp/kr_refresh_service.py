"""Orchestrate read-only KR metric refresh from live data sources."""

from __future__ import annotations

import logging
from typing import Any

from app.jarvis.mvp.kr_metric_resolver import resolve_metric
from app.jarvis.mvp.kr_refresh_persistence import (
    get_latest_kr_refresh_run,
    list_key_results_with_metrics,
    list_kr_refresh_runs,
    record_kr_refresh_run,
    update_kr_from_metric,
)
from app.jarvis.mvp.objective_persistence import (
    calculate_kr_progress,
    calculate_kr_status,
    get_objective,
    record_objective_metric_snapshot,
    update_objective,
)
from app.jarvis.mvp.telegram_kr_alerts import send_kr_refresh_alerts

logger = logging.getLogger(__name__)


def _canonical_metric(metric_name: str) -> str:
    from app.jarvis.mvp.kr_metric_resolver import METRIC_ALIASES

    return METRIC_ALIASES.get(metric_name, metric_name)


def _should_alert_spend_exceeded(kr: dict[str, Any], current: float) -> bool:
    canonical = _canonical_metric(str(kr.get("metric_name") or ""))
    if canonical not in ("aws_monthly_spend", "aws_daily_spend"):
        return False
    if str(kr.get("direction") or "max") != "min":
        return False
    return current > float(kr.get("target_value") or 0)


def _should_alert_accuracy_below(kr: dict[str, Any], current: float) -> bool:
    canonical = _canonical_metric(str(kr.get("metric_name") or ""))
    if canonical != "crypto_reconciliation_accuracy_pct":
        return False
    if str(kr.get("direction") or "max") != "max":
        return False
    return current < float(kr.get("target_value") or 0)


def refresh_key_results(*, send_telegram: bool = True) -> dict[str, Any]:
    """
    Refresh all KRs with metric_name from read-only sources.

    Updates current_value, KR status, objective progress/health, and trend snapshots.
    """
    krs = list_key_results_with_metrics()
    updated_count = 0
    failed_count = 0
    errors: list[dict[str, Any]] = []
    alerts: list[dict[str, Any]] = []
    objectives_touched: set[str] = set()
    prior_health: dict[str, str] = {}

    for kr in krs:
        oid = kr["objective_id"]
        if oid not in prior_health:
            obj = get_objective(oid, include_relations=False)
            prior_health[oid] = str(obj.get("health") or "green") if obj else "green"

    for kr in krs:
        metric_name = str(kr.get("metric_name") or "")
        resolved = resolve_metric(metric_name)

        if resolved.get("error"):
            failed_count += 1
            errors.append({
                "kr_id": kr["kr_id"],
                "objective_id": kr["objective_id"],
                "metric_name": metric_name,
                "error": resolved["error"],
            })
            obj = get_objective(kr["objective_id"], include_relations=False)
            if obj and str(obj.get("health")) == "red":
                alerts.append({
                    "objective_title": obj.get("title") or kr["objective_id"],
                    "kr_title": kr.get("title") or metric_name,
                    "current_value": kr.get("current_value"),
                    "target_value": kr.get("target_value"),
                    "status": "refresh_failed",
                    "unit": kr.get("unit"),
                    "reason": f"Metric refresh failed: {resolved['error']}",
                })
            continue

        current = float(resolved["current_value"])
        target = float(kr.get("target_value") or 0)
        direction = str(kr.get("direction") or "max")
        progress = calculate_kr_progress(
            target_value=target,
            current_value=current,
            direction=direction,
        )
        status = calculate_kr_status(progress)

        ok = update_kr_from_metric(
            kr_id=kr["kr_id"],
            current_value=current,
            metric_source=str(resolved.get("source") or "unknown"),
            status=status,
        )
        if ok:
            updated_count += 1
            objectives_touched.add(kr["objective_id"])
        else:
            failed_count += 1
            errors.append({
                "kr_id": kr["kr_id"],
                "objective_id": kr["objective_id"],
                "metric_name": metric_name,
                "error": "database update failed",
            })
            continue

        obj = get_objective(kr["objective_id"], include_relations=False)
        obj_title = (obj or {}).get("title") or kr["objective_id"]

        if _should_alert_spend_exceeded(kr, current):
            alerts.append({
                "objective_title": obj_title,
                "kr_title": kr.get("title") or metric_name,
                "current_value": current,
                "target_value": target,
                "status": status,
                "unit": kr.get("unit"),
                "reason": "AWS spend exceeds target",
            })

        if _should_alert_accuracy_below(kr, current):
            alerts.append({
                "objective_title": obj_title,
                "kr_title": kr.get("title") or metric_name,
                "current_value": current,
                "target_value": target,
                "status": status,
                "unit": kr.get("unit"),
                "reason": "Portfolio accuracy below target",
            })

    for oid in objectives_touched:
        update_objective(objective_id=oid)
        record_objective_metric_snapshot(objective_id=oid)

        obj_after = get_objective(oid, include_relations=True)
        if not obj_after:
            continue

        new_health = str(obj_after.get("health") or "green")
        old_health = prior_health.get(oid, "green")
        if new_health == "red" and old_health != "red":
            worst_kr = None
            for k in obj_after.get("key_results") or []:
                if str(k.get("status")) == "behind":
                    worst_kr = k
                    break
            if worst_kr is None and obj_after.get("key_results"):
                worst_kr = obj_after["key_results"][0]

            alerts.append({
                "objective_title": obj_after.get("title") or oid,
                "kr_title": (worst_kr or {}).get("title") or "Objective health",
                "current_value": (worst_kr or {}).get("current_value", obj_after.get("progress_pct")),
                "target_value": (worst_kr or {}).get("target_value", 100),
                "status": "red",
                "unit": (worst_kr or {}).get("unit"),
                "reason": "Objective turned red",
            })

    refresh_id = record_kr_refresh_run(
        kr_count=len(krs),
        updated_count=updated_count,
        failed_count=failed_count,
        errors=errors,
    )

    telegram_sent = 0
    if send_telegram and alerts:
        telegram_sent = send_kr_refresh_alerts(alerts)

    logger.info(
        "kr_refresh complete refresh_id=%s kr_count=%s updated=%s failed=%s alerts=%s",
        refresh_id,
        len(krs),
        updated_count,
        failed_count,
        len(alerts),
    )

    return {
        "refresh_id": refresh_id,
        "kr_count": len(krs),
        "updated_count": updated_count,
        "failed_count": failed_count,
        "errors": errors,
        "alerts_queued": len(alerts),
        "telegram_sent": telegram_sent,
        "read_only": True,
        "execution_performed": False,
    }


def get_kr_refresh_status() -> dict[str, Any]:
    """Return latest refresh run for dashboard display."""
    latest = get_latest_kr_refresh_run()
    return {
        "last_refresh": latest,
        "read_only": True,
    }
