"""Daily executive metrics collection and persistence (read-only)."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from app.database import engine, ensure_jarvis_daily_metrics_table

logger = logging.getLogger(__name__)


def _isoformat(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _fetch_aws_daily_cost() -> float:
    """Read-only: last 24h AWS spend estimate via Cost Explorer."""
    try:
        from app.jarvis.mvp.aws_auditor_tools import _client

        ce = _client("ce")
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=1)
        resp = ce.get_cost_and_usage(
            TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
            Granularity="DAILY",
            Metrics=["UnblendedCost"],
        )
        total = 0.0
        for period in resp.get("ResultsByTime") or []:
            total += float(
                (period.get("Total") or {})
                .get("UnblendedCost", {})
                .get("Amount", 0)
                or 0
            )
        return round(total, 2)
    except Exception as exc:
        logger.warning("collect_daily_metrics aws_daily_cost failed: %s", exc)
        return 0.0


def _fetch_aws_monthly_cost() -> float:
    try:
        from app.jarvis.mvp.aws_auditor_tools import get_cost_summary

        result = get_cost_summary()
        if result.get("success"):
            return float(result.get("total_usd") or 0.0)
    except Exception as exc:
        logger.warning("collect_daily_metrics aws_monthly_cost failed: %s", exc)
    return 0.0


def _fetch_aws_resource_counts() -> dict[str, int]:
    counts = {"ec2_count": 0, "ebs_count": 0, "snapshot_count": 0, "eip_count": 0}
    try:
        from app.jarvis.mvp.aws_auditor_tools import (
            get_ebs_inventory,
            get_ec2_inventory,
            get_eip_inventory,
            get_snapshot_inventory,
        )

        ec2 = get_ec2_inventory()
        if ec2.get("success"):
            counts["ec2_count"] = int(ec2.get("total") or 0)
        ebs = get_ebs_inventory()
        if ebs.get("success"):
            counts["ebs_count"] = int(ebs.get("total") or 0)
        snaps = get_snapshot_inventory()
        if snaps.get("success"):
            counts["snapshot_count"] = int(snaps.get("total") or 0)
        eips = get_eip_inventory()
        if eips.get("success"):
            counts["eip_count"] = int(eips.get("total") or 0)
    except Exception as exc:
        logger.warning("collect_daily_metrics aws_resources failed: %s", exc)
    return counts


def _fetch_security_metrics() -> dict[str, Any]:
    from app.jarvis.mvp.audit_persistence import list_audit_runs

    open_findings = 0
    critical_findings = 0
    sg_exposed = 0
    untagged = 0
    last_audit_date = None

    audits = list_audit_runs(limit=1)
    if audits:
        last_audit_date = audits[0].get("created_at")
        detail_id = audits[0].get("audit_id")
        if detail_id:
            from app.jarvis.mvp.audit_persistence import get_audit_run

            detail = get_audit_run(detail_id) or {}
            cost = detail.get("cost_findings") or []
            security = detail.get("security_findings") or []
            resource = detail.get("resource_findings") or []
            open_findings = len(cost) + len(security) + len(resource)
            for group in (cost, security, resource):
                for item in group:
                    if str(item.get("severity") or "").lower() == "high":
                        critical_findings += 1
                    if item.get("category") == "security_groups":
                        sg_exposed += int(item.get("count") or 0)
                    if item.get("category") == "tagging":
                        untagged += int(item.get("count") or 0)

    try:
        from app.jarvis.mvp.aws_auditor_tools import get_security_group_inventory, get_resource_tag_audit

        sgs = get_security_group_inventory()
        if sgs.get("success"):
            sg_exposed = max(sg_exposed, int(sgs.get("risky_count") or 0))
        tags = get_resource_tag_audit()
        if tags.get("success"):
            untagged = max(untagged, int(tags.get("untagged_count") or 0))
    except Exception as exc:
        logger.warning("collect_daily_metrics security live failed: %s", exc)

    return {
        "open_findings": open_findings,
        "critical_findings": critical_findings,
        "sg_exposed_0_0_0_0": sg_exposed,
        "untagged_resources": untagged,
        "last_aws_audit_date": last_audit_date,
    }


def _fetch_jarvis_activity() -> dict[str, Any]:
    if engine is None:
        return {
            "task_count": 0,
            "audit_count": 0,
            "task_success_rate": 0.0,
            "failed_tasks": 0,
            "avg_task_cost": 0.0,
            "bedrock_cost": 0.0,
        }
    try:
        from app.database import ensure_jarvis_audit_runs_table, ensure_jarvis_task_runs_table

        if not ensure_jarvis_task_runs_table(engine):
            return {"task_count": 0, "audit_count": 0, "task_success_rate": 0.0, "failed_tasks": 0, "avg_task_cost": 0.0, "bedrock_cost": 0.0}

        with engine.connect() as conn:
            task_row = conn.execute(
                text(
                    """
                    SELECT
                        COUNT(*) AS total,
                        SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
                        SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,
                        COALESCE(AVG(estimated_cost_usd), 0) AS avg_cost,
                        COALESCE(SUM(estimated_cost_usd), 0) AS total_cost
                    FROM jarvis_task_runs
                    WHERE completed_at IS NOT NULL
                    """
                )
            ).fetchone()
            audit_count = 0
            if ensure_jarvis_audit_runs_table(engine):
                audit_count = conn.execute(text("SELECT COUNT(*) FROM jarvis_audit_runs")).scalar() or 0

        mapping = task_row._mapping if task_row and hasattr(task_row, "_mapping") else {}
        total = int(mapping.get("total") or 0)
        completed = int(mapping.get("completed") or 0)
        failed = int(mapping.get("failed") or 0)
        success_rate = round(completed / total * 100, 2) if total > 0 else 0.0
        return {
            "task_count": total,
            "audit_count": int(audit_count),
            "task_success_rate": success_rate,
            "failed_tasks": failed,
            "avg_task_cost": round(float(mapping.get("avg_cost") or 0), 4),
            "bedrock_cost": round(float(mapping.get("total_cost") or 0), 4),
        }
    except Exception as exc:
        logger.warning("collect_daily_metrics jarvis_activity failed: %s", exc)
        return {
            "task_count": 0,
            "audit_count": 0,
            "task_success_rate": 0.0,
            "failed_tasks": 0,
            "avg_task_cost": 0.0,
            "bedrock_cost": 0.0,
        }


def _fetch_crypto_health() -> dict[str, Any]:
    from app.jarvis.mvp.crypto_audit_persistence import get_latest_crypto_audit_run

    latest = get_latest_crypto_audit_run()
    if latest:
        summary = latest.get("summary") or {}
        return {
            "last_reconciliation_date": latest.get("created_at"),
            "dashboard_portfolio_value": float(summary.get("dashboard_total_usd") or 0),
            "exchange_portfolio_value": float(summary.get("exchange_total_usd") or 0),
            "portfolio_difference_pct": float(latest.get("portfolio_difference_pct") or 0),
            "reconciliation_status": summary.get("reconciliation_status", "unknown"),
        }

    try:
        from app.jarvis.mvp.crypto_auditor_tools import get_dashboard_portfolio, get_exchange_wallet

        dash = get_dashboard_portfolio()
        ex = get_exchange_wallet()
        dash_val = float(dash.get("total_usd") or 0) if dash.get("success") else 0.0
        ex_val = float(ex.get("total_usd") or 0) if ex.get("success") else 0.0
        diff_pct = round(abs(ex_val - dash_val) / ex_val * 100, 2) if ex_val > 0 else 0.0
        status = "pass" if abs(ex_val - dash_val) <= 1.0 else "mismatch"
        return {
            "last_reconciliation_date": None,
            "dashboard_portfolio_value": dash_val,
            "exchange_portfolio_value": ex_val,
            "portfolio_difference_pct": diff_pct,
            "reconciliation_status": status,
        }
    except Exception as exc:
        logger.warning("collect_daily_metrics crypto_health failed: %s", exc)
        return {
            "last_reconciliation_date": None,
            "dashboard_portfolio_value": 0.0,
            "exchange_portfolio_value": 0.0,
            "portfolio_difference_pct": 0.0,
            "reconciliation_status": "unknown",
        }


def collect_daily_metrics(*, metric_date: date | None = None) -> dict[str, Any]:
    """
    Collect read-only executive metrics for a single day and persist to jarvis_daily_metrics.
    Returns the metrics dict (does not modify trading, balances, or AWS resources).
    """
    target_date = metric_date or datetime.now(timezone.utc).date()
    aws_resources = _fetch_aws_resource_counts()
    security = _fetch_security_metrics()
    jarvis = _fetch_jarvis_activity()
    crypto = _fetch_crypto_health()

    metrics = {
        "metric_date": target_date.isoformat(),
        "aws_monthly_cost": _fetch_aws_monthly_cost(),
        "aws_daily_cost": _fetch_aws_daily_cost(),
        "ec2_count": aws_resources["ec2_count"],
        "ebs_count": aws_resources["ebs_count"],
        "snapshot_count": aws_resources["snapshot_count"],
        "eip_count": aws_resources["eip_count"],
        "open_findings": security["open_findings"],
        "critical_findings": security["critical_findings"],
        "task_count": jarvis["task_count"],
        "audit_count": jarvis["audit_count"],
        "task_success_rate": jarvis["task_success_rate"],
        "bedrock_cost": jarvis["bedrock_cost"],
        "dashboard_portfolio_value": crypto["dashboard_portfolio_value"],
        "exchange_portfolio_value": crypto["exchange_portfolio_value"],
        "portfolio_difference_pct": crypto["portfolio_difference_pct"],
    }

    if engine is not None and ensure_jarvis_daily_metrics_table(engine):
        try:
            with engine.begin() as conn:
                if engine.dialect.name == "sqlite":
                    conn.execute(
                        text(
                            """
                            INSERT OR REPLACE INTO jarvis_daily_metrics (
                                metric_date, aws_monthly_cost, aws_daily_cost,
                                ec2_count, ebs_count, snapshot_count, eip_count,
                                open_findings, critical_findings,
                                task_count, audit_count, task_success_rate, bedrock_cost,
                                dashboard_portfolio_value, exchange_portfolio_value,
                                portfolio_difference_pct
                            ) VALUES (
                                :metric_date, :aws_monthly_cost, :aws_daily_cost,
                                :ec2_count, :ebs_count, :snapshot_count, :eip_count,
                                :open_findings, :critical_findings,
                                :task_count, :audit_count, :task_success_rate, :bedrock_cost,
                                :dashboard_portfolio_value, :exchange_portfolio_value,
                                :portfolio_difference_pct
                            )
                            """
                        ),
                        metrics,
                    )
                else:
                    conn.execute(
                        text(
                            """
                            INSERT INTO jarvis_daily_metrics (
                                metric_date, aws_monthly_cost, aws_daily_cost,
                                ec2_count, ebs_count, snapshot_count, eip_count,
                                open_findings, critical_findings,
                                task_count, audit_count, task_success_rate, bedrock_cost,
                                dashboard_portfolio_value, exchange_portfolio_value,
                                portfolio_difference_pct
                            ) VALUES (
                                :metric_date, :aws_monthly_cost, :aws_daily_cost,
                                :ec2_count, :ebs_count, :snapshot_count, :eip_count,
                                :open_findings, :critical_findings,
                                :task_count, :audit_count, :task_success_rate, :bedrock_cost,
                                :dashboard_portfolio_value, :exchange_portfolio_value,
                                :portfolio_difference_pct
                            )
                            ON CONFLICT (metric_date) DO UPDATE SET
                                aws_monthly_cost = EXCLUDED.aws_monthly_cost,
                                aws_daily_cost = EXCLUDED.aws_daily_cost,
                                ec2_count = EXCLUDED.ec2_count,
                                ebs_count = EXCLUDED.ebs_count,
                                snapshot_count = EXCLUDED.snapshot_count,
                                eip_count = EXCLUDED.eip_count,
                                open_findings = EXCLUDED.open_findings,
                                critical_findings = EXCLUDED.critical_findings,
                                task_count = EXCLUDED.task_count,
                                audit_count = EXCLUDED.audit_count,
                                task_success_rate = EXCLUDED.task_success_rate,
                                bedrock_cost = EXCLUDED.bedrock_cost,
                                dashboard_portfolio_value = EXCLUDED.dashboard_portfolio_value,
                                exchange_portfolio_value = EXCLUDED.exchange_portfolio_value,
                                portfolio_difference_pct = EXCLUDED.portfolio_difference_pct
                            """
                        ),
                        metrics,
                    )
        except Exception as exc:
            logger.warning("collect_daily_metrics persist failed: %s", exc)

    return {
        **metrics,
        "sg_exposed_0_0_0_0": security["sg_exposed_0_0_0_0"],
        "untagged_resources": security["untagged_resources"],
        "last_aws_audit_date": security["last_aws_audit_date"],
        "failed_tasks": jarvis["failed_tasks"],
        "avg_task_cost": jarvis["avg_task_cost"],
        "last_reconciliation_date": crypto["last_reconciliation_date"],
        "reconciliation_status": crypto["reconciliation_status"],
        "read_only": True,
    }


def list_daily_metrics(*, days: int = 30) -> list[dict[str, Any]]:
    """Return daily metric snapshots for trend charts."""
    if engine is None or not ensure_jarvis_daily_metrics_table(engine):
        return []

    safe_days = max(1, min(days, 90))
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT *
                FROM jarvis_daily_metrics
                ORDER BY metric_date DESC
                LIMIT :limit
                """
            ),
            {"limit": safe_days},
        ).fetchall()

    results: list[dict[str, Any]] = []
    for row in rows:
        mapping = row._mapping if hasattr(row, "_mapping") else row
        results.append(
            {
                "metric_date": _isoformat(mapping.get("metric_date")),
                "aws_monthly_cost": float(mapping.get("aws_monthly_cost") or 0),
                "aws_daily_cost": float(mapping.get("aws_daily_cost") or 0),
                "ec2_count": int(mapping.get("ec2_count") or 0),
                "ebs_count": int(mapping.get("ebs_count") or 0),
                "snapshot_count": int(mapping.get("snapshot_count") or 0),
                "eip_count": int(mapping.get("eip_count") or 0),
                "open_findings": int(mapping.get("open_findings") or 0),
                "critical_findings": int(mapping.get("critical_findings") or 0),
                "task_count": int(mapping.get("task_count") or 0),
                "audit_count": int(mapping.get("audit_count") or 0),
                "task_success_rate": float(mapping.get("task_success_rate") or 0),
                "bedrock_cost": float(mapping.get("bedrock_cost") or 0),
                "dashboard_portfolio_value": float(mapping.get("dashboard_portfolio_value") or 0),
                "exchange_portfolio_value": float(mapping.get("exchange_portfolio_value") or 0),
                "portfolio_difference_pct": float(mapping.get("portfolio_difference_pct") or 0),
                "created_at": _isoformat(mapping.get("created_at")),
            }
        )
    return list(reversed(results))


def get_executive_dashboard() -> dict[str, Any]:
    """Build executive dashboard payload with current metrics and trends."""
    current = collect_daily_metrics()
    trends = list_daily_metrics(days=30)

    decision_intelligence: dict[str, Any] = {
        "decision_success_rate": 0.0,
        "approved_count": 0,
        "rejected_count": 0,
        "deferred_count": 0,
        "successful_outcomes": 0,
        "failed_outcomes": 0,
        "most_common_rejected_recommendation": None,
        "most_successful_recommendation_type": None,
        "repeated_findings_count": 0,
    }
    try:
        from app.jarvis.mvp.decision_analytics import get_decision_analytics

        decision_intelligence = get_decision_analytics()
    except Exception as exc:
        logger.warning("get_executive_dashboard decision_intelligence failed: %s", exc)

    execution: dict[str, Any] = {
        "active_initiatives": 0,
        "blocked_initiatives": 0,
        "overdue_initiatives": 0,
        "completed_this_month": 0,
        "top_risk": None,
    }
    try:
        from app.jarvis.mvp.initiative_persistence import get_execution_review, list_all_initiatives

        review = get_execution_review(initiatives=list_all_initiatives())
        execution = {
            "active_initiatives": review["active"],
            "blocked_initiatives": review["blocked"],
            "overdue_initiatives": review["overdue"],
            "completed_this_month": review["completed_this_month"],
            "top_risk": review.get("top_risk"),
        }
    except Exception as exc:
        logger.warning("get_executive_dashboard execution failed: %s", exc)

    followups: dict[str, Any] = {
        "open_followups": 0,
        "critical_followups": 0,
        "high_followups": 0,
        "overdue_followups": 0,
        "acknowledged_followups": 0,
        "resolved_this_week": 0,
    }
    try:
        from app.jarvis.mvp.followup_persistence import get_followup_summary

        followups = get_followup_summary()
    except Exception as exc:
        logger.warning("get_executive_dashboard followups failed: %s", exc)

    strategic_objectives: dict[str, Any] = {
        "objectives_on_track": 0,
        "objectives_at_risk": 0,
        "objectives_completed": 0,
        "average_progress_pct": 0,
    }
    try:
        from app.jarvis.mvp.objective_persistence import get_strategic_summary

        strategic_objectives = get_strategic_summary()
    except Exception as exc:
        logger.warning("get_executive_dashboard strategic_objectives failed: %s", exc)

    return {
        "infrastructure": {
            "aws_monthly_spend": current.get("aws_monthly_cost"),
            "aws_daily_spend": current.get("aws_daily_cost"),
            "ec2_instances": current.get("ec2_count"),
            "ebs_volumes": current.get("ebs_count"),
            "snapshots": current.get("snapshot_count"),
            "elastic_ips": current.get("eip_count"),
            "last_aws_audit_date": current.get("last_aws_audit_date"),
        },
        "security": {
            "open_findings": current.get("open_findings"),
            "critical_findings": current.get("critical_findings"),
            "security_groups_exposed_0_0_0_0": current.get("sg_exposed_0_0_0_0"),
            "untagged_resources": current.get("untagged_resources"),
        },
        "jarvis_activity": {
            "total_tasks_executed": current.get("task_count"),
            "total_audits_executed": current.get("audit_count"),
            "success_rate": current.get("task_success_rate"),
            "failed_tasks": current.get("failed_tasks"),
            "average_task_cost": current.get("avg_task_cost"),
            "total_bedrock_cost": current.get("bedrock_cost"),
        },
        "crypto_health": {
            "last_reconciliation_date": current.get("last_reconciliation_date"),
            "dashboard_portfolio_value": current.get("dashboard_portfolio_value"),
            "exchange_portfolio_value": current.get("exchange_portfolio_value"),
            "difference_pct": current.get("portfolio_difference_pct"),
            "reconciliation_status": current.get("reconciliation_status"),
        },
        "trends": {
            "aws_spend": [
                {"date": t["metric_date"], "monthly": t["aws_monthly_cost"], "daily": t["aws_daily_cost"]}
                for t in trends
            ],
            "findings": [
                {"date": t["metric_date"], "open": t["open_findings"], "critical": t["critical_findings"]}
                for t in trends
            ],
            "task_volume": [
                {"date": t["metric_date"], "tasks": t["task_count"], "audits": t["audit_count"]}
                for t in trends
            ],
        },
        "decision_intelligence": decision_intelligence,
        "execution": execution,
        "followups": followups,
        "strategic_objectives": strategic_objectives,
        "read_only": True,
    }
