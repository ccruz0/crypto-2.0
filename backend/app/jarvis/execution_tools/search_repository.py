"""Topic-based repository search for Jarvis diagnostics."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.jarvis.agents.repository_agent import search_files

_TOPIC_QUERIES: dict[str, list[str]] = {
    "open_orders": [
        "getOpenOrders",
        "open-orders",
        "/orders/open",
        "OpenOrder",
        "open_orders",
    ],
    "orders": [
        "routes_orders",
        "exchange_orders",
        "ExchangeOrder",
        "order_intents",
    ],
    "positions": [
        "open_positions",
        "OpenPosition",
        "count_open_positions",
    ],
    "trade_history": [
        "order_history",
        "trade_history",
        "get_order_history",
        "exchange_orders",
    ],
    "dashboard_tabs": [
        "JarvisControlTab",
        "openOrders",
        "DashboardTab",
        "page.tsx",
    ],
    "api_routes": [
        "routes_orders",
        "routes_dashboard",
        "/orders/open",
        "get_open_orders",
    ],
    "portfolio": [
        "portfolio_cache",
        "get_portfolio_summary",
        "wallet_reconciliation",
        "total_usd",
    ],
    "websocket": [
        "websocket",
        "WebSocket",
        "price_feed",
        "market-updater",
    ],
    "credentials": [
        "credential_resolver",
        "EXCHANGE_CUSTOM_API_KEY",
        "runtime.env",
    ],
    "cache": [
        "open_orders_cache",
        "portfolio_cache",
        "last_updated",
    ],
    "jarvis": [
        "jarvis/execution",
        "investigation_runner",
        "JarvisControlTab",
    ],
    "result_validation": [
        "result_validation",
        "root_cause_present",
        "conclusion_present",
        "INSUFFICIENT_EVIDENCE",
        "validate_task_result",
    ],
    "repository_agent": [
        "repository_agent",
        "search_repository",
        "_detect_topics",
        "investigate_objective",
    ],
    "planner": [
        "planner_agent",
        "build_plan",
        "objective_classification",
    ],
}

_DEFAULT_FRAMEWORK_TOPICS: list[str] = ["jarvis", "result_validation", "planner", "repository_agent"]

_JARVIS_FRAMEWORK_TERMS: tuple[str, ...] = (
    "insufficient_evidence",
    "insufficient evidence",
    "result_validation",
    "root_cause_present",
    "conclusion_present",
    "validation pipeline",
    "validation framework",
    "safety classifier",
    "planner_agent",
    "repository_agent",
    "repository agent",
    "objective_classification",
    "jarvis internals",
    "framework audit",
    "framework-audit",
    "meta-investigation",
    "validate_task_result",
    "search_repository",
    "_detect_topics",
    "investigate_objective",
)

_TOPIC_EXPLANATIONS: dict[str, str] = {
    "open_orders": "Frontend hooks and backend routes that serve open orders to the dashboard",
    "orders": "Order models, API handlers, and exchange sync for order lifecycle",
    "positions": "Open position calculation and display components",
    "trade_history": "Historical trade/order endpoints and data models",
    "dashboard_tabs": "Dashboard UI tabs and state that render trading data",
    "api_routes": "FastAPI route modules exposing order and dashboard endpoints",
    "portfolio": "Portfolio cache, equity calculation, and wallet reconciliation",
    "websocket": "Websocket price feed and market updater modules",
    "credentials": "Exchange API credential resolution and runtime.env loading",
    "cache": "Dashboard cache layers for orders and portfolio data",
    "jarvis": "Jarvis execution framework and control UI",
    "result_validation": "Jarvis result validation, evidence gates, and completion checks",
    "repository_agent": "Repository agent and search_repository topic routing",
    "planner": "Jarvis planner agent and objective classification",
}


def _is_jarvis_framework_objective(text: str) -> bool:
    if any(term in text for term in _JARVIS_FRAMEWORK_TERMS):
        return True
    if "jarvis" in text and any(
        token in text for token in ("validation", "framework", "internals", "classifier", "planner", "execution")
    ):
        return True
    if "investigation task" in text and "insufficient" in text:
        return True
    if "topic generation" in text and "repository" in text:
        return True
    return False


def _detect_topics(*, topic: str | None = None, objective: str | None = None, action: str | None = None) -> list[str]:
    if topic and topic in _TOPIC_QUERIES:
        return [topic]

    text = " ".join(filter(None, [objective, action])).lower()
    topics: list[str] = []
    is_framework = _is_jarvis_framework_objective(text)

    if is_framework:
        topics.extend(["result_validation", "repository_agent", "planner", "jarvis"])

    has_open_orders = "open order" in text or "open_orders" in text
    has_orders_context = has_open_orders or "orders" in text or ("order" in text and not is_framework)

    if has_open_orders:
        topics.extend(["open_orders", "api_routes", "dashboard_tabs"])
    elif has_orders_context and ("api" in text or "route" in text):
        topics.extend(["open_orders", "api_routes"])
    elif has_orders_context:
        topics.append("orders")

    if "position" in text:
        topics.append("positions")
    if ("trade" in text or "history" in text) and not is_framework:
        topics.append("trade_history")
    if ("dashboard" in text or "tab" in text) and (has_orders_context or not is_framework):
        topics.append("dashboard_tabs")

    if not topics:
        topics = list(_DEFAULT_FRAMEWORK_TOPICS)

    seen: set[str] = set()
    ordered: list[str] = []
    for t in topics:
        if t not in seen:
            seen.add(t)
            ordered.append(t)
    return ordered[:4]


def _confidence_for_topic(topic: str, hit_count: int) -> str:
    if hit_count >= 5:
        return "high"
    if hit_count >= 2:
        return "medium"
    return "low"


def search_repository(
    *,
    topic: str | None = None,
    pattern: str | None = None,
    objective: str | None = None,
    action: str | None = None,
    max_results: int = 15,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Search repository for files/lines related to trading diagnostics."""
    topics = _detect_topics(topic=topic, objective=objective, action=action)
    matches: list[dict[str, Any]] = []

    if pattern:
        for hit in search_files(pattern, max_results=max_results):
            matches.append(
                {
                    "path": hit.get("path", ""),
                    "line": hit.get("line", ""),
                    "text": hit.get("text", ""),
                    "topic": "custom",
                    "confidence": "medium",
                }
            )

    for t in topics:
        explanation = _TOPIC_EXPLANATIONS.get(t, f"Matches for topic {t}")
        topic_hits: list[dict[str, str]] = []
        for query in _TOPIC_QUERIES.get(t, [t]):
            topic_hits.extend(search_files(query, max_results=5))
        confidence = _confidence_for_topic(t, len(topic_hits))
        for hit in topic_hits[:max_results]:
            matches.append(
                {
                    "path": hit.get("path", ""),
                    "line": hit.get("line", ""),
                    "text": hit.get("text", ""),
                    "topic": t,
                    "explanation": explanation,
                    "confidence": confidence,
                }
            )

    deduped: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    for m in matches:
        key = (m.get("path", ""), m.get("line", ""))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(m)
        if len(deduped) >= max_results:
            break

    return {
        "tool": "search_repository",
        "topics": topics,
        "match_count": len(deduped),
        "matches": deduped,
        "read_only": True,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
