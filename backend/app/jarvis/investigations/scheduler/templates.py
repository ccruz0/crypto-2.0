"""Recurring read-only investigation templates for Phase 6A."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RecurringInvestigationTemplate:
    schedule_id: str
    template_id: str
    title: str
    objective: str
    category: str
    enabled: bool = True


# Default recurring investigations — objectives match human quick-launch wording.
RECURRING_INVESTIGATION_TEMPLATES: tuple[RecurringInvestigationTemplate, ...] = (
    RecurringInvestigationTemplate(
        schedule_id="open_orders_health",
        template_id="open_orders_empty",
        title="Open orders health",
        objective="Why are open orders empty?",
        category="orders",
    ),
    RecurringInvestigationTemplate(
        schedule_id="portfolio_reconciliation",
        template_id="portfolio_reconciliation_mismatch",
        title="Portfolio reconciliation",
        objective="Investigate portfolio reconciliation mismatch",
        category="portfolio",
    ),
    RecurringInvestigationTemplate(
        schedule_id="api_health",
        template_id="jarvis_task_failing",
        title="API health checks",
        objective="Why is Jarvis task failing?",
        category="api",
    ),
    RecurringInvestigationTemplate(
        schedule_id="exchange_connectivity",
        template_id="dashboard_exchange_mismatch",
        title="Exchange connectivity",
        objective="Why does dashboard differ from exchange?",
        category="exchange",
    ),
    RecurringInvestigationTemplate(
        schedule_id="database_health",
        template_id="generic",
        title="Database health",
        objective="Check database health and recent query errors",
        category="database",
    ),
    RecurringInvestigationTemplate(
        schedule_id="websocket_health",
        template_id="websocket_prices_stale",
        title="WebSocket health",
        objective="Why are websocket prices stale?",
        category="websocket",
    ),
    RecurringInvestigationTemplate(
        schedule_id="error_log_analysis",
        template_id="generic",
        title="Error log analysis",
        objective="Analyze recent error logs for production incidents",
        category="api",
    ),
    RecurringInvestigationTemplate(
        schedule_id="deployment_verification",
        template_id="deployment_unhealthy",
        title="Deployment verification",
        objective="Why is deployment unhealthy?",
        category="deployment",
    ),
)


def get_recurring_template(schedule_id: str) -> RecurringInvestigationTemplate | None:
    for template in RECURRING_INVESTIGATION_TEMPLATES:
        if template.schedule_id == schedule_id:
            return template
    return None


def list_recurring_templates() -> list[RecurringInvestigationTemplate]:
    return list(RECURRING_INVESTIGATION_TEMPLATES)
