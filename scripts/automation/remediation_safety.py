"""Safety policy for Jarvis auto-remediation — allowlist, levels, and audit."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from scripts.automation.common import state_dir, utc_now_iso

logger = logging.getLogger(__name__)

AUDIT_LOG_NAME = "remediation_audit.jsonl"


class SafetyLevel(str, Enum):
    """Remediation action safety classification."""

    SAFE_AUTO = "safe_auto"
    NEEDS_APPROVAL = "needs_approval"
    FORBIDDEN = "forbidden"


# Canonical action identifiers (single source of truth for allowlist).
ACTION_RESTART_BACKEND = "restart_backend"
ACTION_RESTART_FRONTEND = "restart_frontend"
ACTION_RESTART_MARKET_UPDATER = "restart_market_updater"
ACTION_POST_HEALTH_FIX = "post_health_fix"
ACTION_RUN_READONLY_DIAGNOSTICS = "run_readonly_diagnostics"
ACTION_RUN_OPENCLAW_GUARD = "run_openclaw_guard"
ACTION_SEND_TELEGRAM = "send_telegram"
ACTION_CREATE_NOTION_INCIDENT = "create_notion_incident"

ALLOWED_AUTO_ACTIONS: frozenset[str] = frozenset(
    {
        ACTION_RESTART_BACKEND,
        ACTION_RESTART_FRONTEND,
        ACTION_RESTART_MARKET_UPDATER,
        ACTION_POST_HEALTH_FIX,
        ACTION_RUN_READONLY_DIAGNOSTICS,
        ACTION_RUN_OPENCLAW_GUARD,
        ACTION_SEND_TELEGRAM,
        ACTION_CREATE_NOTION_INCIDENT,
    }
)

# Map compose service names to canonical action ids.
COMPOSE_SERVICE_TO_ACTION: dict[str, str] = {
    "backend-aws": ACTION_RESTART_BACKEND,
    "frontend-aws": ACTION_RESTART_FRONTEND,
    "market-updater-aws": ACTION_RESTART_MARKET_UPDATER,
}

# Health-check failure names -> safe auto actions (only allowlisted actions).
HEALTH_FAILURE_ACTIONS: dict[str, list[str]] = {
    "backend_ping_fast": [ACTION_POST_HEALTH_FIX, ACTION_RESTART_BACKEND],
    "jarvis_tasks_api": [ACTION_POST_HEALTH_FIX, ACTION_RESTART_BACKEND],
    "websocket_prices": [ACTION_POST_HEALTH_FIX, ACTION_RESTART_BACKEND],
    "backend_recent_errors": [ACTION_POST_HEALTH_FIX, ACTION_RESTART_BACKEND],
    "frontend_dashboard": [ACTION_RESTART_FRONTEND],
    "docker_market-updater": [ACTION_RESTART_MARKET_UPDATER],
}

# Patterns / action ids requiring human approval before execution.
_NEEDS_APPROVAL_ACTIONS: frozenset[str] = frozenset(
    {
        "deploy",
        "code_change",
        "env_change",
        "secrets_change",
        "database_write",
        "nginx_change",
        "ops_config_change",
        "update_runtime_env",
        "fix_credentials_path",
    }
)

# Agent-proposed action keywords -> safety level (investigation outcomes).
_AGENT_ACTION_KEYWORDS: tuple[tuple[tuple[str, ...], SafetyLevel], ...] = (
    (("place_order", "trading_order", "execute_trade", "submit_order", "cancel_order"), SafetyLevel.FORBIDDEN),
    (("delete_volume", "docker volume rm", "drop table", "truncate ", "delete from "), SafetyLevel.FORBIDDEN),
    (("disable_security", "openclaw_public", "expose openclaw", "0.0.0.0/0"), SafetyLevel.FORBIDDEN),
    (
        ("deploy", "code_change", "nginx", "docker-compose.yml", "runtime.env", "secret", "database write", "migration"),
        SafetyLevel.NEEDS_APPROVAL,
    ),
)

# Substrings that must never appear in executed shell commands during auto-remediation.
_FORBIDDEN_COMMAND_SUBSTRINGS: tuple[str, ...] = (
    " rm ",
    " volume rm",
    "docker rm",
    "drop table",
    "truncate ",
    "delete from ",
    "deploy",
    "git push",
    "git commit",
    "place_order",
    "execute_trade",
    "nginx -s reload",
)


def auto_remediation_dry_run() -> bool:
    """When true, remediation logs actions but does not restart services or call mutating APIs."""
    raw = os.getenv("JARVIS_AUTO_REMEDIATION_DRY_RUN", "true").strip().lower()
    return raw in ("1", "true", "yes", "on")


def jarvis_agent_investigation_only() -> bool:
    """When true, jarvis-incident dispatches agents for investigation only (no prod mutation)."""
    raw = os.getenv("JARVIS_AGENT_INVESTIGATION_ONLY", "true").strip().lower()
    return raw in ("1", "true", "yes", "on")


def classify_action(action_id: str, *, context: str = "") -> SafetyLevel:
    """Classify a remediation or agent action by id and optional context text."""
    aid = (action_id or "").strip().lower()
    ctx = (context or "").lower()
    combined = f"{aid} {ctx}"

    for keywords, level in _AGENT_ACTION_KEYWORDS:
        if any(kw in combined for kw in keywords):
            return level

    if aid in ALLOWED_AUTO_ACTIONS:
        return SafetyLevel.SAFE_AUTO

    if aid in _NEEDS_APPROVAL_ACTIONS or any(
        kw in combined for kw in ("deploy", "nginx", "code_change", "secret", "env_change", "database_write")
    ):
        return SafetyLevel.NEEDS_APPROVAL

    return SafetyLevel.NEEDS_APPROVAL


def is_auto_action_allowed(action_id: str) -> bool:
    """True only for hard-allowlisted automation actions."""
    return (action_id or "").strip() in ALLOWED_AUTO_ACTIONS


def assert_command_safe(command: list[str]) -> None:
    """Raise ValueError if a shell command is not permitted during auto-remediation."""
    joined = " ".join(command).lower()
    for forbidden in _FORBIDDEN_COMMAND_SUBSTRINGS:
        if forbidden in joined:
            raise ValueError(f"forbidden command fragment: {forbidden!r}")
    if "docker" in joined and "compose" in joined and "restart" in joined:
        for service, action_id in COMPOSE_SERVICE_TO_ACTION.items():
            if service in joined:
                if is_auto_action_allowed(action_id):
                    return
        raise ValueError("docker compose restart only allowed for backend-aws, frontend-aws, market-updater-aws")
    if "compose" not in joined and "restart" in joined:
        raise ValueError("bare docker restart not allowed in auto-remediation")


def planned_actions_for_health_failures(failure_names: set[str]) -> list[str]:
    """Return ordered, deduplicated allowlisted actions for health check failures."""
    planned: list[str] = []
    seen: set[str] = set()
    for name in sorted(failure_names):
        for action_id in HEALTH_FAILURE_ACTIONS.get(name, []):
            if action_id in seen:
                continue
            if is_auto_action_allowed(action_id):
                seen.add(action_id)
                planned.append(action_id)
    return planned


@dataclass
class AuditRecord:
    """One auditable remediation event."""

    timestamp: str
    detected_failure: str
    action_attempted: str
    result: str
    agent_triggered: bool
    approval_required: bool
    dry_run: bool = False
    detail: str = ""
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "detected_failure": self.detected_failure,
            "action_attempted": self.action_attempted,
            "result": self.result,
            "agent_triggered": self.agent_triggered,
            "approval_required": self.approval_required,
            "dry_run": self.dry_run,
            "detail": self.detail[:500],
            "source": self.source,
        }


@dataclass
class RemediationAuditLog:
    """Append-only JSONL audit log for remediation actions."""

    path: Path = field(default_factory=lambda: state_dir() / AUDIT_LOG_NAME)

    def append(self, record: AuditRecord) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("remediation audit write failed path=%s err=%s", self.path, exc)

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        rows: list[dict[str, Any]] = []
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                rows.append(json.loads(line))
        except (OSError, json.JSONDecodeError):
            return rows
        return rows


def audit_log() -> RemediationAuditLog:
    return RemediationAuditLog(path=state_dir() / AUDIT_LOG_NAME)


def log_audit(
    *,
    detected_failure: str,
    action_attempted: str,
    result: str,
    agent_triggered: bool,
    approval_required: bool,
    dry_run: bool = False,
    detail: str = "",
    source: str = "",
) -> AuditRecord:
    """Write one audit record and return it."""
    record = AuditRecord(
        timestamp=utc_now_iso(),
        detected_failure=detected_failure,
        action_attempted=action_attempted,
        result=result,
        agent_triggered=agent_triggered,
        approval_required=approval_required,
        dry_run=dry_run,
        detail=detail,
        source=source,
    )
    audit_log().append(record)
    logger.info(
        "remediation_audit failure=%s action=%s result=%s agent=%s approval_required=%s dry_run=%s",
        detected_failure[:80],
        action_attempted,
        result,
        agent_triggered,
        approval_required,
        dry_run,
    )
    return record
