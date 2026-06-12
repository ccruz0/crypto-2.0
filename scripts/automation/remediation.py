"""Auto-remediation for Jarvis production automations (health checks, task auditor)."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from scripts.automation.common import (
    REPO_ROOT,
    backend_base,
    exchange_integration_optional,
    is_exchange_credential_warning,
    state_dir,
    utc_now_iso,
)
from scripts.automation.remediation_safety import (
    ACTION_CREATE_NOTION_INCIDENT,
    ACTION_POST_HEALTH_FIX,
    ACTION_RESTART_BACKEND,
    ACTION_RESTART_FRONTEND,
    ACTION_RESTART_MARKET_UPDATER,
    COMPOSE_SERVICE_TO_ACTION,
    SafetyLevel,
    assert_command_safe,
    auto_remediation_dry_run,
    classify_action,
    is_auto_action_allowed,
    jarvis_agent_investigation_only,
    log_audit,
    planned_actions_for_health_failures,
)

logger = logging.getLogger(__name__)

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_GRACE_SECONDS = 30


def auto_remediation_enabled() -> bool:
    """When true, Jarvis automations attempt fixes and dispatch agents before alerting."""
    raw = os.getenv("JARVIS_AUTO_REMEDIATION_ENABLED", "false").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _max_attempts() -> int:
    try:
        return max(1, int(os.getenv("JARVIS_REMEDIATION_MAX_ATTEMPTS", str(DEFAULT_MAX_ATTEMPTS))))
    except ValueError:
        return DEFAULT_MAX_ATTEMPTS


def _grace_seconds() -> int:
    try:
        return max(0, int(os.getenv("JARVIS_REMEDIATION_GRACE_SECONDS", str(DEFAULT_GRACE_SECONDS))))
    except ValueError:
        return DEFAULT_GRACE_SECONDS


@dataclass
class RemediationAction:
    check_name: str
    action: str
    ok: bool
    detail: str
    dry_run: bool = False
    approval_required: bool = False


@dataclass
class FailureItem:
    name: str
    detail: str

    @classmethod
    def from_check(cls, item: Any) -> FailureItem:
        return cls(name=str(getattr(item, "name", "") or ""), detail=str(getattr(item, "detail", "") or ""))

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "detail": self.detail[:500]}


def filter_false_positive_failures(failures: list[Any]) -> list[Any]:
    """Drop optional exchange-credential noise from backend_recent_errors failures."""
    filtered: list[Any] = []
    for item in failures:
        name = str(getattr(item, "name", "") or "")
        detail = str(getattr(item, "detail", "") or "")
        if name == "backend_recent_errors":
            lines = [part.strip() for part in detail.split(";") if part.strip()]
            real_errors = [line for line in lines if not is_exchange_credential_warning(line)]
            if not real_errors:
                continue
            if exchange_integration_optional():
                continue
        filtered.append(item)
    return filtered


def should_trigger_remediation(failures: list[FailureItem]) -> bool:
    """True when failures warrant safe auto-remediation (never for exchange-only noise)."""
    if not failures:
        return False
    names = {f.name for f in failures}
    return bool(planned_actions_for_health_failures(names))


def _state_path() -> Path:
    return state_dir() / "remediation_state.json"


def _load_state() -> dict[str, Any]:
    path = _state_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(data: dict[str, Any]) -> None:
    path = _state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.warning("remediation state write failed path=%s err=%s", path, exc)


def _incident_key(failures: list[FailureItem]) -> str:
    return "|".join(sorted(f.name for f in failures))


def should_attempt_remediation(failures: list[FailureItem]) -> bool:
    if not failures:
        return False
    if not should_trigger_remediation(failures):
        return False
    key = _incident_key(failures)
    state = _load_state()
    entry = state.get(key) or {}
    attempts = int(entry.get("attempts") or 0)
    return attempts < _max_attempts()


def mark_remediation_attempt(failures: list[FailureItem]) -> int:
    key = _incident_key(failures)
    state = _load_state()
    entry = state.get(key) or {}
    attempts = int(entry.get("attempts") or 0) + 1
    state[key] = {"attempts": attempts, "last_attempt_ts": utc_now_iso()}
    _save_state(state)
    return attempts


def clear_remediation_state(failures: list[FailureItem] | None = None) -> None:
    if failures is None:
        _save_state({})
        return
    key = _incident_key(failures)
    state = _load_state()
    state.pop(key, None)
    _save_state(state)


def _http_post(url: str, payload: dict[str, Any], *, timeout: float = 30.0) -> tuple[bool, str, int | None]:
    try:
        body = json.dumps(payload).encode("utf-8")
        req = Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": "atp-jarvis-automation/1.0"},
            method="POST",
        )
        with urlopen(req, timeout=timeout) as resp:
            code = resp.getcode()
            text = resp.read(8192).decode("utf-8", errors="replace")
            if 200 <= code < 300:
                return True, text[:300], code
            return False, f"HTTP {code}: {text[:200]}", code
    except HTTPError as exc:
        body = exc.read(256).decode("utf-8", errors="replace") if exc.fp else ""
        return False, f"HTTP {exc.code}: {body[:200]}", exc.code
    except URLError as exc:
        return False, str(exc.reason)[:200], None
    except Exception as exc:  # pragma: no cover
        return False, str(exc)[:200], None


def _post_health_fix(*, dry_run: bool, failure_label: str) -> RemediationAction:
    action_id = ACTION_POST_HEALTH_FIX
    if not is_auto_action_allowed(action_id):
        log_audit(
            detected_failure=failure_label,
            action_attempted=action_id,
            result="blocked_not_allowlisted",
            agent_triggered=False,
            approval_required=True,
            dry_run=dry_run,
            source="health_check",
        )
        return RemediationAction("backend_services", action_id, False, "not allowlisted", dry_run=dry_run)

    if dry_run:
        log_audit(
            detected_failure=failure_label,
            action_attempted=action_id,
            result="dry_run_skipped",
            agent_triggered=False,
            approval_required=False,
            dry_run=True,
            detail="POST /api/health/fix",
            source="health_check",
        )
        return RemediationAction("backend_services", action_id, True, "dry-run: would POST /api/health/fix", dry_run=True)

    base = backend_base()
    ok, detail, _ = _http_post(f"{base}/api/health/fix", {})
    log_audit(
        detected_failure=failure_label,
        action_attempted=action_id,
        result="ok" if ok else "fail",
        agent_triggered=False,
        approval_required=False,
        dry_run=False,
        detail=detail,
        source="health_check",
    )
    return RemediationAction("backend_services", action_id, ok, detail)


def _restart_compose_service(service: str, *, dry_run: bool, failure_label: str) -> RemediationAction:
    action_id = COMPOSE_SERVICE_TO_ACTION.get(service, f"restart_{service}")
    level = classify_action(action_id)
    if not is_auto_action_allowed(action_id):
        log_audit(
            detected_failure=failure_label,
            action_attempted=action_id,
            result="blocked_not_allowlisted",
            agent_triggered=False,
            approval_required=level != SafetyLevel.SAFE_AUTO,
            dry_run=dry_run,
            detail=f"service={service}",
            source="health_check",
        )
        return RemediationAction(service, action_id, False, "not allowlisted", dry_run=dry_run)

    cmd = ["docker", "compose", "--profile", "aws", "restart", service]
    try:
        assert_command_safe(cmd)
    except ValueError as exc:
        log_audit(
            detected_failure=failure_label,
            action_attempted=action_id,
            result="blocked_unsafe_command",
            agent_triggered=False,
            approval_required=True,
            dry_run=dry_run,
            detail=str(exc),
            source="health_check",
        )
        return RemediationAction(service, action_id, False, str(exc)[:200], dry_run=dry_run)

    if dry_run:
        log_audit(
            detected_failure=failure_label,
            action_attempted=action_id,
            result="dry_run_skipped",
            agent_triggered=False,
            approval_required=False,
            dry_run=True,
            detail=" ".join(cmd),
            source="health_check",
        )
        return RemediationAction(service, action_id, True, f"dry-run: would run {' '.join(cmd)}", dry_run=True)

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(REPO_ROOT),
            check=False,
        )
        ok = proc.returncode == 0
        detail = (proc.stdout or proc.stderr or "restart finished")[:200]
        log_audit(
            detected_failure=failure_label,
            action_attempted=action_id,
            result="ok" if ok else "fail",
            agent_triggered=False,
            approval_required=False,
            dry_run=False,
            detail=detail,
            source="health_check",
        )
        return RemediationAction(service, action_id, ok, detail)
    except Exception as exc:
        log_audit(
            detected_failure=failure_label,
            action_attempted=action_id,
            result="error",
            agent_triggered=False,
            approval_required=False,
            dry_run=False,
            detail=str(exc)[:200],
            source="health_check",
        )
        return RemediationAction(service, action_id, False, str(exc)[:200])


def remediate_health_failures(
    failures: list[FailureItem],
    *,
    dry_run: bool | None = None,
    log: logging.Logger | None = None,
) -> list[RemediationAction]:
    """Run safe, allowlisted fixes for known Jarvis health check failures."""
    log = log or logger
    effective_dry_run = auto_remediation_dry_run() if dry_run is None else dry_run
    actions: list[RemediationAction] = []
    names = {f.name for f in failures}
    failure_label = "|".join(sorted(names)) or "unknown"
    planned = planned_actions_for_health_failures(names)

    if not planned:
        log.info("remediation skipped: no allowlisted actions for failures=%s", sorted(names))
        return actions

    log.info(
        "remediation planned actions=%s dry_run=%s failures=%s",
        planned,
        effective_dry_run,
        sorted(names),
    )

    for action_id in planned:
        if action_id == ACTION_POST_HEALTH_FIX:
            actions.append(_post_health_fix(dry_run=effective_dry_run, failure_label=failure_label))
        elif action_id == ACTION_RESTART_BACKEND:
            actions.append(_restart_compose_service("backend-aws", dry_run=effective_dry_run, failure_label=failure_label))
        elif action_id == ACTION_RESTART_FRONTEND:
            actions.append(_restart_compose_service("frontend-aws", dry_run=effective_dry_run, failure_label=failure_label))
        elif action_id == ACTION_RESTART_MARKET_UPDATER:
            actions.append(_restart_compose_service("market-updater", dry_run=effective_dry_run, failure_label=failure_label))

    for action in actions:
        status = "ok" if action.ok else "fail"
        log.info(
            "remediation action=%s check=%s status=%s dry_run=%s detail=%s",
            action.action,
            action.check_name,
            status,
            action.dry_run,
            action.detail[:160],
        )

    grace = _grace_seconds()
    if grace > 0 and actions and not effective_dry_run:
        log.info("remediation grace_sleep=%ss", grace)
        time.sleep(grace)

    return actions


def dispatch_agent_for_incident(
    failures: list[FailureItem],
    *,
    source: str,
    category: str = "health_check",
    dry_run: bool | None = None,
    log: logging.Logger | None = None,
) -> dict[str, Any]:
    """Create a Notion incident task and trigger one agent scheduler cycle (investigation only)."""
    log = log or logger
    if not failures:
        return {"ok": False, "reason": "no_failures"}

    effective_dry_run = auto_remediation_dry_run() if dry_run is None else dry_run
    investigation_only = jarvis_agent_investigation_only()
    failure_label = "|".join(sorted(f.name for f in failures)) or category

    payload = {
        "source": source,
        "category": category,
        "failures": [f.to_dict() for f in failures],
        "timestamp": utc_now_iso(),
        "investigation_only": investigation_only,
    }

    if effective_dry_run:
        log.info("DRY-RUN would dispatch agent incident payload=%s", json.dumps(payload)[:400])
        log_audit(
            detected_failure=failure_label,
            action_attempted=ACTION_CREATE_NOTION_INCIDENT,
            result="dry_run_skipped",
            agent_triggered=False,
            approval_required=investigation_only,
            dry_run=True,
            detail=json.dumps(payload)[:300],
            source=source,
        )
        return {"ok": True, "dry_run": True, "investigation_only": investigation_only}

    url = f"{backend_base()}/api/monitoring/jarvis-incident"
    ok, detail, code = _http_post(url, payload, timeout=60.0)
    if not ok:
        log.warning("agent dispatch failed code=%s detail=%s", code, detail[:200])
        log_audit(
            detected_failure=failure_label,
            action_attempted=ACTION_CREATE_NOTION_INCIDENT,
            result="fail",
            agent_triggered=False,
            approval_required=investigation_only,
            dry_run=False,
            detail=detail,
            source=source,
        )
        return {"ok": False, "reason": detail, "http_code": code}

    try:
        parsed = json.loads(detail)
    except json.JSONDecodeError:
        parsed = {"raw": detail}

    agent_triggered = bool(parsed.get("scheduler"))
    log_audit(
        detected_failure=failure_label,
        action_attempted=ACTION_CREATE_NOTION_INCIDENT,
        result="ok",
        agent_triggered=agent_triggered,
        approval_required=investigation_only,
        dry_run=False,
        detail=str(parsed.get("notion_task_id") or "")[:80],
        source=source,
    )
    log.info("agent dispatch ok notion_task_id=%s", (parsed.get("notion_task_id") or "")[:12])
    return {"ok": True, **parsed, "investigation_only": investigation_only}


def remediate_audit_findings(
    findings: list[Any],
    *,
    dry_run: bool | None = None,
    log: logging.Logger | None = None,
) -> dict[str, Any]:
    """Turn task-auditor findings into agent-dispatched incidents (deduped per category)."""
    log = log or logger
    if not findings:
        return {"ok": True, "dispatched": 0}

    effective_dry_run = auto_remediation_dry_run() if dry_run is None else dry_run
    by_category: dict[str, list[FailureItem]] = {}
    for item in findings:
        category = str(getattr(item, "category", "") or "unknown")
        detail = str(getattr(item, "detail", "") or "")
        by_category.setdefault(category, []).append(FailureItem(name=category, detail=detail))

    dispatched = 0
    results: list[dict[str, Any]] = []
    for category, items in by_category.items():
        if category == "high_cost":
            continue
        if not should_attempt_remediation(items):
            log.info("remediation skip category=%s (max attempts reached)", category)
            continue
        attempt = mark_remediation_attempt(items)
        log.info("task_auditor remediation category=%s attempt=%s", category, attempt)
        result = dispatch_agent_for_incident(
            items,
            source="jarvis-task-auditor",
            category=f"task_auditor:{category}",
            dry_run=effective_dry_run,
            log=log,
        )
        results.append(result)
        if result.get("ok"):
            dispatched += 1

    return {"ok": True, "dispatched": dispatched, "results": results}
