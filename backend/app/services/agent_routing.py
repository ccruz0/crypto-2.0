"""
Multi-agent routing: maps Notion tasks to specialized analysis agents.

Agents are for analysis, diagnosis, and patch proposal — NOT for trading execution.
Routing is explicit and config-driven. Used by select_default_callbacks_for_task.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Agent IDs (must match AGENT_DEFINITIONS.md)
AGENT_TELEGRAM_ALERTS = "telegram_alerts"
AGENT_EXECUTION_STATE = "execution_state"
AGENT_TRADING_SIGNAL = "trading_signal"
AGENT_SYSTEM_HEALTH = "system_health"
AGENT_DOCS_RULES = "docs_rules"
AGENT_ARCHITECTURE = "architecture"

# Save subdirs per agent (must exist under docs/agents/ or docs/runbooks/)
AGENT_SAVE_SUBDIRS: dict[str, str] = {
    AGENT_TELEGRAM_ALERTS: "docs/agents/telegram-alerts",
    AGENT_EXECUTION_STATE: "docs/agents/execution-state",
    AGENT_TRADING_SIGNAL: "docs/agents/trading-signal",
    AGENT_SYSTEM_HEALTH: "docs/agents/system-health",
    AGENT_DOCS_RULES: "docs/agents/generated-notes",
    AGENT_ARCHITECTURE: "docs/agents/architecture",
}

# File prefix per agent (artifact: {prefix}-{task_id}.md)
AGENT_FILE_PREFIXES: dict[str, str] = {
    AGENT_TELEGRAM_ALERTS: "notion-telegram",
    AGENT_EXECUTION_STATE: "notion-execution",
    AGENT_TRADING_SIGNAL: "notion-signal",
    AGENT_SYSTEM_HEALTH: "notion-health",
    AGENT_DOCS_RULES: "notion-task",
    AGENT_ARCHITECTURE: "notion-arch",
}


def _task_blob(prepared_task: dict[str, Any]) -> str:
    """Lowercase blob of task fields for keyword matching."""
    task = (prepared_task or {}).get("task") or {}
    repo_area = (prepared_task or {}).get("repo_area") or {}
    parts = [
        str(task.get("type") or ""),
        str(task.get("task") or ""),
        str(task.get("details") or ""),
        str(task.get("project") or ""),
        str(repo_area.get("area_name") or ""),
    ]
    return " ".join(parts).lower()


def route_task(prepared_task: dict[str, Any]) -> str | None:
    """
    Route a prepared task to the appropriate agent.

    Returns agent_id if a specialized agent matches, else None (fallback to existing logic).
    Priority order matches ROUTING_CONFIG.md.
    """
    blob = _task_blob(prepared_task)
    task = (prepared_task or {}).get("task") or {}
    task_type = str(task.get("type") or "").strip().lower()

    # 1. Telegram and Alerts
    if task_type in ("telegram", "alerts", "notification"):
        logger.info("agent_routing: matched agent=telegram_alerts reason=task_type task_type=%r", task_type)
        return AGENT_TELEGRAM_ALERTS
    for k in ("telegram", "alert", "notification", "throttle", "dedup", "kill switch",
              "telegraph", "chat_id", "not being sent", "alerts not sent",
              "repeated alerts", "missing alerts", "approval noise", "duplicate alert"):
        if k in blob:
            logger.info("agent_routing: matched agent=telegram_alerts reason=keyword keyword=%r", k)
            return AGENT_TELEGRAM_ALERTS

    # 2. Execution and State
    if task_type in ("execution", "order", "sync", "order lifecycle"):
        logger.info("agent_routing: matched agent=execution_state reason=task_type task_type=%r", task_type)
        return AGENT_EXECUTION_STATE
    for k in ("order", "execution", "sync", "exchange", "executed", "canceled",
              "open orders", "order history", "lifecycle", "order not found",
              "missing order", "sl/tp", "stop loss", "take profit",
              "dashboard mismatch", "db mismatch", "state reconciliation"):
        if k in blob:
            logger.info("agent_routing: matched agent=execution_state reason=keyword keyword=%r", k)
            return AGENT_EXECUTION_STATE

    # 3. Trading Signal (scaffolded)
    if task_type in ("signal", "trading", "strategy"):
        return AGENT_TRADING_SIGNAL
    if any(k in blob for k in (
        "signal", "buy", "sell", "strategy", "watchlist", "rsi", "ma ",
        "trade_enabled", "alert_enabled",
    )):
        return AGENT_TRADING_SIGNAL

    # 4. System Health (scaffolded)
    if task_type in ("health", "monitoring", "infra", "infrastructure"):
        return AGENT_SYSTEM_HEALTH
    if any(k in blob for k in (
        "health", "nginx", "502", "504", "ssm", "docker", "market updater",
        "disk", "connectionlost", "connection lost",
    )):
        return AGENT_SYSTEM_HEALTH

    # 5. Docs and Rules (scaffolded)
    if task_type in ("doc", "documentation"):
        return AGENT_DOCS_RULES
    if any(k in blob for k in ("doc", "runbook", "readme", "cursor rule")):
        return AGENT_DOCS_RULES

    # 6. Architecture and Refactor (scaffolded)
    if task_type in ("architecture", "refactor"):
        return AGENT_ARCHITECTURE
    if any(k in blob for k in (
        "architecture", "refactor", "dead code", "tech debt", "duplicate",
    )):
        return AGENT_ARCHITECTURE

    logger.debug("agent_routing: no match task_type=%r blob_preview=%r", task_type, blob[:120])
    return None


def route_task_with_reason(prepared_task: dict[str, Any]) -> tuple[str | None, str]:
    """
    Route a prepared task and return (agent_id, reason).

    reason is a short diagnostic: "task_type:telegram", "keyword:alert", or "no_match".
    """
    blob = _task_blob(prepared_task)
    task = (prepared_task or {}).get("task") or {}
    task_type = str(task.get("type") or "").strip().lower()

    # 1. Telegram and Alerts
    if task_type in ("telegram", "alerts", "notification"):
        return AGENT_TELEGRAM_ALERTS, f"task_type:{task_type}"
    for k in ("telegram", "alert", "notification", "throttle", "dedup", "kill switch",
              "telegraph", "chat_id", "not being sent", "alerts not sent",
              "repeated alerts", "missing alerts", "approval noise", "duplicate alert"):
        if k in blob:
            return AGENT_TELEGRAM_ALERTS, f"keyword:{k}"

    # 2. Execution and State
    if task_type in ("execution", "order", "sync", "order lifecycle"):
        return AGENT_EXECUTION_STATE, f"task_type:{task_type}"
    for k in ("order", "execution", "sync", "exchange", "executed", "canceled",
              "open orders", "order history", "lifecycle", "order not found",
              "missing order", "sl/tp", "stop loss", "take profit",
              "dashboard mismatch", "db mismatch", "state reconciliation"):
        if k in blob:
            return AGENT_EXECUTION_STATE, f"keyword:{k}"

    # 3–6. Scaffolded agents (same logic as route_task)
    if task_type in ("signal", "trading", "strategy"):
        return AGENT_TRADING_SIGNAL, f"task_type:{task_type}"
    if any(k in blob for k in ("signal", "buy", "sell", "strategy", "watchlist", "rsi", "ma ",
                               "trade_enabled", "alert_enabled")):
        return AGENT_TRADING_SIGNAL, "keyword:signal/strategy"

    if task_type in ("health", "monitoring", "infra", "infrastructure"):
        return AGENT_SYSTEM_HEALTH, f"task_type:{task_type}"
    if any(k in blob for k in ("health", "nginx", "502", "504", "ssm", "docker", "market updater",
                               "disk", "connectionlost", "connection lost")):
        return AGENT_SYSTEM_HEALTH, "keyword:health/infra"

    if task_type in ("doc", "documentation"):
        return AGENT_DOCS_RULES, f"task_type:{task_type}"
    if any(k in blob for k in ("doc", "runbook", "readme", "cursor rule")):
        return AGENT_DOCS_RULES, "keyword:doc"

    if task_type in ("architecture", "refactor"):
        return AGENT_ARCHITECTURE, f"task_type:{task_type}"
    if any(k in blob for k in ("architecture", "refactor", "dead code", "tech debt", "duplicate")):
        return AGENT_ARCHITECTURE, "keyword:architecture"

    return None, "no_match"


def get_save_subdir(agent_id: str) -> str:
    """Return save subdir for agent artifact."""
    return AGENT_SAVE_SUBDIRS.get(agent_id, "docs/agents/generated-notes")


def get_file_prefix(agent_id: str) -> str:
    """Return file prefix for agent artifact."""
    return AGENT_FILE_PREFIXES.get(agent_id, "notion-task")
