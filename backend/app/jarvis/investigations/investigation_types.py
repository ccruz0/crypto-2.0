"""Investigation categories, templates, and objective classification."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

InvestigationCategory = Literal[
    "exchange",
    "orders",
    "portfolio",
    "database",
    "dashboard",
    "api",
    "websocket",
    "deployment",
    "authentication",
    "performance",
]


class InvestigationStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    FAILED = "failed"


@dataclass(frozen=True)
class EvidenceCollector:
    """A read-only evidence source to invoke during an investigation."""

    tool: str
    action: str = ""
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InvestigationTemplate:
    """Template defining how to investigate a production incident."""

    template_id: str
    category: InvestigationCategory
    pattern: re.Pattern[str]
    title: str
    collectors: tuple[EvidenceCollector, ...]
    keywords: tuple[str, ...] = ()


# Ordered — first match wins.
INVESTIGATION_TEMPLATES: tuple[InvestigationTemplate, ...] = (
    InvestigationTemplate(
        template_id="open_orders_empty",
        category="orders",
        pattern=re.compile(
            r"why\s+are\s+open\s+orders\s+empty|open\s+orders\s+empty|empty\s+open\s+orders",
            re.IGNORECASE,
        ),
        title="Why are open orders empty?",
        collectors=(
            EvidenceCollector("diagnose_open_orders", "diagnose_open_orders"),
            EvidenceCollector("reconcile_crypto_com_open_orders", "reconcile_crypto_com_open_orders"),
            EvidenceCollector("query_database", "count_open_orders"),
            EvidenceCollector("search_logs", "search_logs", {"keywords": ("open orders", "sync", "cache")}),
            EvidenceCollector("search_repository", "search_repository", {"topic": "open_orders"}),
        ),
        keywords=("open orders", "empty", "zero"),
    ),
    InvestigationTemplate(
        template_id="dashboard_exchange_mismatch",
        category="dashboard",
        pattern=re.compile(
            r"dashboard\s+differ.*exchange|exchange.*differ.*dashboard|"
            r"zero\s+orders.*exchange|exchange.*one.*dashboard.*zero|"
            r"dashboard.*zero.*order.*exchange",
            re.IGNORECASE,
        ),
        title="Why does dashboard differ from exchange?",
        collectors=(
            EvidenceCollector("reconcile_crypto_com_open_orders", "reconcile_crypto_com_open_orders"),
            EvidenceCollector("diagnose_open_orders", "diagnose_open_orders"),
            EvidenceCollector("search_logs", "search_logs", {"keywords": ("trigger", "50001", "open_orders", "sync")}),
            EvidenceCollector("search_repository", "search_repository", {"topic": "open_orders"}),
            EvidenceCollector("inspect_health", "inspect_health"),
        ),
        keywords=("dashboard", "exchange", "mismatch", "reconcile"),
    ),
    InvestigationTemplate(
        template_id="portfolio_equity_derived",
        category="portfolio",
        pattern=re.compile(
            r"portfolio\s+equity\s+derived|equity\s+derived|exchange-reported",
            re.IGNORECASE,
        ),
        title="Why is portfolio equity derived instead of exchange-reported?",
        collectors=(
            EvidenceCollector("query_database", "open_positions"),
            EvidenceCollector("inspect_health", "inspect_health"),
            EvidenceCollector("search_repository", "search_repository", {"topic": "portfolio"}),
            EvidenceCollector("search_logs", "search_logs", {"keywords": ("portfolio", "equity", "balance")}),
            EvidenceCollector("inspect_runtime", "inspect_runtime"),
        ),
        keywords=("portfolio", "equity", "derived"),
    ),
    InvestigationTemplate(
        template_id="portfolio_value_incorrect",
        category="portfolio",
        pattern=re.compile(
            r"portfolio\s+value\s+incorrect|portfolio\s+equity|equity\s+derived|"
            r"portfolio\s+mismatch|wallet\s+balance\s+wrong",
            re.IGNORECASE,
        ),
        title="Why is portfolio value incorrect?",
        collectors=(
            EvidenceCollector("query_database", "open_positions"),
            EvidenceCollector("inspect_health", "inspect_health"),
            EvidenceCollector("search_repository", "search_repository", {"topic": "portfolio"}),
            EvidenceCollector("search_logs", "search_logs", {"keywords": ("portfolio", "equity", "balance", "cache")}),
            EvidenceCollector("inspect_runtime", "inspect_runtime"),
        ),
        keywords=("portfolio", "equity", "balance", "value"),
    ),
    InvestigationTemplate(
        template_id="websocket_prices_stale",
        category="websocket",
        pattern=re.compile(
            r"websocket\s+prices?\s+stale|stale\s+prices?|ws\s+prices?\s+stale|price\s+feed\s+stale",
            re.IGNORECASE,
        ),
        title="Why are websocket prices stale?",
        collectors=(
            EvidenceCollector("search_repository", "search_repository", {"topic": "websocket"}),
            EvidenceCollector("search_logs", "search_logs", {"keywords": ("websocket", "ws", "stale", "price")}),
            EvidenceCollector("inspect_health", "inspect_health"),
            EvidenceCollector("inspect_runtime", "inspect_runtime"),
        ),
        keywords=("websocket", "stale", "price"),
    ),
    InvestigationTemplate(
        template_id="jarvis_task_failing",
        category="api",
        pattern=re.compile(
            r"jarvis\s+task\s+failing|why\s+is\s+jarvis\s+task|jarvis\s+execution\s+fail",
            re.IGNORECASE,
        ),
        title="Why is Jarvis task failing?",
        collectors=(
            EvidenceCollector("search_logs", "search_logs", {"keywords": ("jarvis", "task", "failed", "error")}),
            EvidenceCollector("search_repository", "search_repository", {"topic": "jarvis"}),
            EvidenceCollector("inspect_health", "inspect_health"),
            EvidenceCollector("inspect_runtime", "inspect_runtime"),
        ),
        keywords=("jarvis", "task", "fail"),
    ),
    InvestigationTemplate(
        template_id="deployment_unhealthy",
        category="deployment",
        pattern=re.compile(
            r"deployment\s+unhealthy|unhealthy\s+deployment|why\s+is\s+deployment|service\s+unhealthy",
            re.IGNORECASE,
        ),
        title="Why is deployment unhealthy?",
        collectors=(
            EvidenceCollector("read_logs", "gather_logs"),
            EvidenceCollector("inspect_health", "inspect_health"),
            EvidenceCollector("inspect_runtime", "inspect_runtime"),
            EvidenceCollector("inspect_container", "inspect_container"),
            EvidenceCollector("search_logs", "search_logs", {"keywords": ("error", "unhealthy", "health")}),
        ),
        keywords=("deployment", "unhealthy", "health"),
    ),
    InvestigationTemplate(
        template_id="exchange_auth_failing",
        category="authentication",
        pattern=re.compile(
            r"exchange\s+auth\s+fail|crypto\.?com\s+auth\s+fail|authentication\s+fail|"
            r"40101|api\s+credential|auth\s+error",
            re.IGNORECASE,
        ),
        title="Why is exchange auth failing?",
        collectors=(
            EvidenceCollector("reconcile_crypto_com_open_orders", "reconcile_crypto_com_open_orders"),
            EvidenceCollector("search_logs", "search_logs", {"keywords": ("40101", "Authentication", "credential", "secret")}),
            EvidenceCollector("inspect_runtime", "inspect_runtime"),
            EvidenceCollector("search_repository", "search_repository", {"topic": "credentials"}),
        ),
        keywords=("auth", "40101", "credential", "secret"),
    ),
    InvestigationTemplate(
        template_id="dashboard_stale_data",
        category="dashboard",
        pattern=re.compile(
            r"dashboard\s+showing\s+stale|stale\s+data|cache\s+stale|data\s+stale",
            re.IGNORECASE,
        ),
        title="Why is dashboard showing stale data?",
        collectors=(
            EvidenceCollector("diagnose_open_orders", "diagnose_open_orders"),
            EvidenceCollector("inspect_health", "inspect_health"),
            EvidenceCollector("search_logs", "search_logs", {"keywords": ("cache", "stale", "sync", "last_updated")}),
            EvidenceCollector("search_repository", "search_repository", {"topic": "cache"}),
            EvidenceCollector("inspect_runtime", "inspect_runtime"),
        ),
        keywords=("stale", "cache", "dashboard"),
    ),
)

_DEFAULT_COLLECTORS: tuple[EvidenceCollector, ...] = (
    EvidenceCollector("read_logs", "gather_logs"),
    EvidenceCollector("inspect_health", "inspect_health"),
    EvidenceCollector("search_logs", "search_logs"),
    EvidenceCollector("search_repository", "search_repository"),
)


def match_investigation_template(objective: str) -> InvestigationTemplate | None:
    text = (objective or "").strip()
    for template in INVESTIGATION_TEMPLATES:
        if template.pattern.search(text):
            return template
    return None


def classify_investigation(objective: str) -> tuple[InvestigationCategory, str, InvestigationTemplate | None]:
    """Return (category, template_id, template) for an objective."""
    template = match_investigation_template(objective)
    if template:
        return template.category, template.template_id, template

    text = (objective or "").lower()
    category_rules: list[tuple[InvestigationCategory, tuple[str, ...]]] = [
        ("orders", ("order", "open order")),
        ("portfolio", ("portfolio", "equity", "balance")),
        ("authentication", ("auth", "credential", "40101")),
        ("websocket", ("websocket", "ws", "price")),
        ("deployment", ("deploy", "container", "health")),
        ("dashboard", ("dashboard", "cache", "stale")),
        ("exchange", ("exchange", "crypto.com")),
        ("database", ("database", "sql", "table")),
        ("api", ("api", "endpoint", "route")),
        ("performance", ("slow", "latency", "performance")),
    ]
    for category, keywords in category_rules:
        if any(kw in text for kw in keywords):
            return category, "generic", None
    return "api", "generic", None


def get_collectors_for_objective(objective: str) -> tuple[InvestigationCategory, str, tuple[EvidenceCollector, ...]]:
    """Resolve evidence collectors for an investigation objective."""
    category, template_id, template = classify_investigation(objective)
    if template:
        return category, template_id, template.collectors
    return category, template_id, _DEFAULT_COLLECTORS


# Preset objectives for UI quick-launch.
DIAGNOSTIC_PRESETS: tuple[dict[str, str], ...] = tuple(
    {"id": t.template_id, "label": t.title, "objective": t.title}
    for t in INVESTIGATION_TEMPLATES
)
