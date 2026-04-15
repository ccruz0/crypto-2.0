"""
Deterministic ATP operational review (read-only, no Bedrock, no external writes).

Unified ``actions`` list: one actionable item per detected issue.
"""

from __future__ import annotations

import os
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.environment import getRuntimeEnv, is_atp_trading_only, is_aws

try:
    from app.jarvis.runtime_env import get_jarvis_env
except ImportError:  # pragma: no cover - thin checkout

    def get_jarvis_env() -> str:
        raw = (os.environ.get("JARVIS_ENV") or "").strip().lower()
        if not raw:
            return "dev"
        if raw in ("dev", "lab", "prod"):
            return raw
        return "dev"


try:
    from app.services.required_secrets_registry import (
        MARKETING_SETTINGS_ENV_VARS,
        compute_missing_settings,
        evaluate_requirements,
    )
except ImportError:  # pragma: no cover - thin checkout
    MARKETING_SETTINGS_ENV_VARS = frozenset()

    def compute_missing_settings() -> list[dict[str, Any]]:
        return []

    def evaluate_requirements() -> dict[str, Any]:
        return {"missing": []}


try:
    from app.services.secret_recovery import recovery_status_payload
except ImportError:  # pragma: no cover

    def recovery_status_payload() -> dict[str, Any]:
        return {"auto_restart_enabled": False, "recovery_runnable": False}


try:
    from app.utils.runtime_env_file import get_effective_settings, parse_runtime_env_file
except ImportError:  # pragma: no cover

    def parse_runtime_env_file(*_a: Any, **_k: Any) -> dict[str, str]:
        return {}

    def get_effective_settings(keys: list[str], **_k: Any) -> dict[str, str | None]:
        return {k: None for k in keys}


ActionPriority = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]


class RunAtpSystemReviewArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment: Literal["prod", "lab"] = Field(default="lab")
    scope: Literal["full", "quick"] = Field(default="quick")


def _norm_dedupe_key(message: str) -> str:
    return " ".join((message or "").strip().lower().split())


def _add_action(
    actions: list[dict[str, Any]],
    seen: set[str],
    message: str,
    priority: ActionPriority,
    source: str | None = None,
) -> None:
    key = _norm_dedupe_key(message)
    if not key or key in seen:
        return
    seen.add(key)
    item: dict[str, Any] = {"message": message.strip(), "priority": priority}
    if source:
        item["source"] = source
    actions.append(item)


def _load_system_health() -> dict[str, Any] | None:
    try:
        from app.database import SessionLocal
        from app.services.system_health import get_system_health

        db = SessionLocal()
        try:
            return get_system_health(db)
        finally:
            db.close()
    except Exception:
        return None


def _telegram_poller_hint() -> str | None:
    try:
        from app.services import telegram_commands as tc

        streak = int(getattr(tc, "_GET_UPDATES_409_STREAK", 0) or 0)
        if streak >= 2:
            return (
                f"Telegram getUpdates 409 streak={streak} — possible duplicate poller/webhook. "
                "Run duplicate-consumer diagnostics on the host."
            )
    except Exception:
        return None
    return None


def _runtime_env_matches_target(target: str) -> tuple[bool, str]:
    je = get_jarvis_env()
    if target == "prod":
        return je == "prod", je
    return je in ("lab", "dev"), je


def _full_runtime_env_file_notes() -> list[str]:
    rt = parse_runtime_env_file()
    out: list[str] = []
    for var in sorted(MARKETING_SETTINGS_ENV_VARS):
        proc = (os.environ.get(var) or "").strip()
        file_v = (rt.get(var) or "").strip()
        if not proc and file_v:
            out.append(f"{var}: value only in runtime.env (not in process env)")
    return out


def _build_summary(actions: list[dict[str, Any]]) -> str:
    if not actions:
        return "No issues detected for this review scope."
    prios = [str(a.get("priority") or "") for a in actions]
    if "CRITICAL" in prios:
        base = "System needs immediate attention due to critical failures."
    elif "HIGH" in prios:
        base = "System is running but has high-priority configuration gaps."
    elif "MEDIUM" in prios or "LOW" in prios:
        base = "System is healthy with a few issues to address."
    else:
        base = "Review complete."
    return f"{base} ({len(actions)} action(s))."


def _status_from_actions(actions: list[dict[str, Any]]) -> Literal["ok", "degraded", "critical"]:
    prios = {str(a.get("priority") or "") for a in actions}
    if "CRITICAL" in prios:
        return "critical"
    if prios & {"HIGH", "MEDIUM", "LOW"}:
        return "degraded"
    return "ok"


def run_atp_system_review(**kwargs: Any) -> dict[str, Any]:
    args = RunAtpSystemReviewArgs.model_validate(kwargs)
    target = args.environment
    scope = args.scope

    actions: list[dict[str, Any]] = []
    seen: set[str] = set()

    runtime_env = getRuntimeEnv()
    aws = is_aws()
    trading_only = is_atp_trading_only()

    match_ok, jarvis_env = _runtime_env_matches_target(target)
    if not match_ok:
        _add_action(
            actions,
            seen,
            (
                f"Review target is {target.upper()} but JARVIS_ENV={jarvis_env} "
                f"(ENVIRONMENT={runtime_env}, aws={aws}) — align JARVIS_ENV with the stack you mean to review."
            ),
            "MEDIUM",
            "runtime",
        )

    health = _load_system_health()
    if health is None:
        _add_action(
            actions,
            seen,
            "System health check failed (DB unavailable or error) — check /api/health/system and database connectivity.",
            "CRITICAL",
            "health",
        )
    else:
        g = str(health.get("global_status") or "").upper()
        if g == "FAIL":
            _add_action(
                actions,
                seen,
                "Global system health is FAIL — check /api/health/system and component breakdown.",
                "CRITICAL",
                "health",
            )
        elif g and g != "PASS":
            _add_action(
                actions,
                seen,
                f"Global system health is {g} — check /api/health/system.",
                "HIGH",
                "health",
            )

        if health.get("db_status") == "down":
            _add_action(
                actions,
                seen,
                "Database connectivity is down — restore Postgres before trading or agents rely on it.",
                "CRITICAL",
                "health",
            )

        for comp, label, crit_on_fail in (
            ("market_data", "Market data", False),
            ("market_updater", "Market updater", False),
            ("signal_monitor", "Signal monitor", False),
            ("telegram", "Telegram", False),
            ("trade_system", "Trade system", True),
        ):
            block = health.get(comp)
            if not isinstance(block, dict):
                continue
            st = str(block.get("status") or "").upper()
            if st == "FAIL":
                pri: ActionPriority = "CRITICAL" if crit_on_fail else "HIGH"
                _add_action(
                    actions,
                    seen,
                    f"{label} health is FAIL — check /api/health/system ({comp}).",
                    pri,
                    "health",
                )
            elif st and st != "PASS" and scope == "full":
                _add_action(
                    actions,
                    seen,
                    f"{label} health is {st} — review /api/health/system when convenient.",
                    "MEDIUM",
                    "health",
                )

    req_eval = evaluate_requirements()
    for row in (req_eval.get("missing") or [])[:12]:
        if not isinstance(row, dict):
            continue
        ev = str(row.get("env_var") or row.get("id") or "?")
        svc = str(row.get("blocked_service") or "service")
        _add_action(
            actions,
            seen,
            f"Required secret/config missing: {ev} ({svc}) — set via dashboard, SSM, or secrets/runtime.env.",
            "HIGH",
            "config",
        )

    if trading_only and (req_eval.get("missing") or []):
        _add_action(
            actions,
            seen,
            "ATP_TRADING_ONLY is on but automation-related secrets are still missing — fill when enabling agents.",
            "MEDIUM",
            "config",
        )

    for m in compute_missing_settings()[:12]:
        if not isinstance(m, dict):
            continue
        lbl = str(m.get("label") or m.get("key") or "?")
        _add_action(
            actions,
            seen,
            f"{lbl} not set — add in trading dashboard (Missing marketing settings) or runtime.env.",
            "HIGH",
            "config",
        )

    poller = _telegram_poller_hint()
    if poller:
        _add_action(actions, seen, poller, "MEDIUM", "runtime")

    if scope == "full":
        eff = get_effective_settings(list(MARKETING_SETTINGS_ENV_VARS))
        missing_eff = [k for k, v in eff.items() if not (v or "").strip()]
        if missing_eff:
            _add_action(
                actions,
                seen,
                (
                    f"{len(missing_eff)} marketing-related env var(s) unset in effective merge "
                    "(process + runtime.env) — configure in dashboard or runtime.env."
                ),
                "MEDIUM",
                "config",
            )

        for note in _full_runtime_env_file_notes()[:8]:
            _add_action(
                actions,
                seen,
                f"{note} — prefer setting in process env for clarity, or document override.",
                "LOW",
                "runtime",
            )

        rec = recovery_status_payload()
        if rec.get("auto_restart_enabled") and not rec.get("recovery_runnable"):
            _add_action(
                actions,
                seen,
                "Secret auto-recovery is enabled but compose project dir is not configured — fix DOCKER_COMPOSE_PROJECT_DIR if needed.",
                "LOW",
                "runtime",
            )

        runbook = os.getenv("ATP_OPS_RUNBOOK_PATH", "").strip() or "docs/runbooks/ATP_PROD_LAB_OPERATIONS.md"
        if os.path.isfile(runbook):
            _add_action(
                actions,
                seen,
                f"Ops runbook present: {runbook} — use for PROD/LAB procedures.",
                "LOW",
                "runtime",
            )

    summary = _build_summary(actions)
    status = _status_from_actions(actions)

    return {
        "status": status,
        "environment": target,
        "scope": scope,
        "summary": summary,
        "actions": actions,
    }
