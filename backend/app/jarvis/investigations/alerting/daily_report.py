"""Daily health summary generation for Phase 6B."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.jarvis.investigations.alerting.persistence import (
    count_alerts_since,
    get_daily_report_for_date,
    save_daily_report,
    top_recurring_issues,
)
from app.jarvis.investigations.alerting.telegram import send_daily_health_report
from app.jarvis.investigations.scheduler.persistence import (
    average_runtime_ms_since,
    count_tasks_by_status_since,
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def build_daily_report_summary(*, report_date: date | None = None) -> dict[str, Any]:
    """Build daily health summary for the given UTC date (default: today)."""
    target_date = report_date or _now_utc().date()
    day_start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)

    counts = count_tasks_by_status_since(since=day_start)
    completed = int(counts.get("completed", 0))
    failed = int(counts.get("failed", 0))
    terminal = completed + failed
    success_rate = (completed / terminal * 100.0) if terminal else 0.0
    avg_runtime = average_runtime_ms_since(since=day_start)

    warnings = count_alerts_since(since=day_start, severity="WARNING")
    critical_alerts = count_alerts_since(since=day_start, severity="CRITICAL")
    recurring = top_recurring_issues(since=day_start, limit=5)

    return {
        "report_date": target_date.isoformat(),
        "generated_at": _now_utc().isoformat(),
        "period_start": day_start.isoformat(),
        "period_end": day_end.isoformat(),
        "investigations_executed": terminal,
        "success_rate_pct": round(success_rate, 2),
        "failures": failed,
        "warnings": warnings,
        "critical_alerts": critical_alerts,
        "average_runtime_ms": round(avg_runtime, 2),
        "task_counts": counts,
        "top_recurring_issues": recurring,
    }


def generate_and_store_daily_report(
    *,
    report_date: date | None = None,
    send_telegram: bool = True,
) -> dict[str, Any]:
    """Generate, persist, and optionally Telegram-send the daily health report."""
    summary = build_daily_report_summary(report_date=report_date)
    target_date = date.fromisoformat(summary["report_date"])
    stored = save_daily_report(report_date=target_date, summary=summary)
    telegram_sent = False
    if send_telegram:
        telegram_sent = send_daily_health_report(summary)
    return {
        **stored,
        "telegram_sent": telegram_sent,
    }


def maybe_generate_daily_report(*, force: bool = False) -> dict[str, Any] | None:
    """
    Generate today's report once per UTC day after the configured hour.

    Returns None when not due or already generated.
    """
    from app.jarvis.investigations.alerting import config as alert_config

    if not alert_config.jarvis_daily_report_enabled():
        return None

    now = _now_utc()
    if not force and now.hour < alert_config.jarvis_daily_report_hour_utc():
        return None

    today = now.date()
    existing = get_daily_report_for_date(today)
    if existing and not force:
        return None

    return generate_and_store_daily_report(report_date=today, send_telegram=True)
