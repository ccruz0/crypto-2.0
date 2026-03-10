"""
Post-deploy smoke-check gate for task lifecycle progression.

Runs lightweight health checks against the deployed service and
conditionally advances tasks through the extended lifecycle:

    deploying  →  done     (if smoke check passes)
    deploying  →  blocked  (if smoke check fails)

The module is intentionally decoupled from the executor and from any
specific deployment mechanism.  Smoke checks can be triggered by:
    - the executor (after deploy_fn succeeds)
    - a Telegram command or callback
    - a scheduler / cron job
    - a CI/CD webhook

Health checks reuse existing infrastructure:
    - ``/api/health``  (quick liveness)
    - ``/api/health/system`` (full component status)

No side effects on trading, exchange, or deployment systems beyond
Notion status updates and activity logging.

Env vars:
    SMOKE_CHECK_SYSTEM_HEALTH_RETRIES — retries for system_health when FAIL (default 3).
    SMOKE_CHECK_SYSTEM_HEALTH_RETRY_DELAY_S — delay between retries (default 30).
    When system_health fails (e.g. signal_monitor not running yet), retries allow
    subsystems to become ready after deploy restart.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DEFAULT_HEALTH_URL = "http://127.0.0.1:8002"

SMOKE_CHECK_TIMEOUT_S = 15
SMOKE_CHECK_RETRIES = 12
SMOKE_CHECK_RETRY_DELAY_S = 15
# Backend healthcheck has start_period 180s; wait before first attempt so deploy has time to restart
SMOKE_CHECK_INITIAL_DELAY_S = 120
# Retries for system_health when FAIL (handles signal_monitor/market_updater startup timing)
SMOKE_CHECK_SYSTEM_HEALTH_RETRIES = 3
SMOKE_CHECK_SYSTEM_HEALTH_RETRY_DELAY_S = 30


def _health_base_url() -> str:
    """Resolve the base URL for health checks from env or default."""
    for var in ("ATP_HEALTH_BASE", "API_BASE_URL"):
        val = (os.environ.get(var) or "").strip().rstrip("/")
        if val:
            return val
    return _DEFAULT_HEALTH_URL


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# ---------------------------------------------------------------------------
# Individual check runners
# ---------------------------------------------------------------------------


def check_endpoint(
    url: str,
    *,
    label: str = "",
    timeout_s: float = SMOKE_CHECK_TIMEOUT_S,
) -> dict[str, Any]:
    """Hit a single HTTP endpoint and return a structured result.

    Returns ``{"ok": bool, "label": str, "status_code": int|None,
    "latency_ms": float, "detail": str}``.
    """
    label = label or url
    t0 = time.monotonic()
    try:
        resp = httpx.get(url, timeout=timeout_s, follow_redirects=True)
        latency_ms = (time.monotonic() - t0) * 1000
        ok = 200 <= resp.status_code < 300
        return {
            "ok": ok,
            "label": label,
            "status_code": resp.status_code,
            "latency_ms": round(latency_ms, 1),
            "detail": f"{label}: HTTP {resp.status_code} ({latency_ms:.0f}ms)",
        }
    except httpx.TimeoutException:
        latency_ms = (time.monotonic() - t0) * 1000
        return {
            "ok": False,
            "label": label,
            "status_code": None,
            "latency_ms": round(latency_ms, 1),
            "detail": f"{label}: timeout after {timeout_s}s",
        }
    except Exception as exc:
        latency_ms = (time.monotonic() - t0) * 1000
        return {
            "ok": False,
            "label": label,
            "status_code": None,
            "latency_ms": round(latency_ms, 1),
            "detail": f"{label}: {type(exc).__name__}: {exc}",
        }


def _component_reason(key: str, val: dict[str, Any]) -> str:
    """Build a human-readable reason for a failed health component."""
    status = str(val.get("status", "")).lower()
    if key == "signal_monitor":
        is_running = val.get("is_running")
        age = val.get("last_cycle_age_minutes")
        if not is_running:
            return "not running"
        if age is None:
            return "no cycle yet (startup)"
        if isinstance(age, (int, float)) and age > 30:
            return f"last cycle {age:.0f}min ago (stale)"
        return f"status={status}"
    if key == "market_updater":
        is_running = val.get("is_running")
        age = val.get("last_heartbeat_age_minutes")
        if not is_running:
            return f"not running (data age {age}min)" if age is not None else "not running"
        return f"status={status}"
    if key == "market_data":
        fresh = val.get("fresh_symbols", 0)
        stale = val.get("stale_symbols", 0)
        return f"fresh={fresh} stale={stale}"
    if key == "telegram":
        enabled = val.get("enabled")
        run_env = val.get("run_telegram_env")
        if not run_env:
            return "disabled by env"
        if not enabled:
            return "config missing or kill switch"
        return f"status={status}"
    if key == "trade_system":
        table = val.get("order_intents_table_exists")
        if table is False:
            return "order_intents table missing"
        return f"status={status}"
    return f"status={status}"


def check_system_health(
    base_url: str | None = None,
    *,
    timeout_s: float = SMOKE_CHECK_TIMEOUT_S,
) -> dict[str, Any]:
    """Call ``/api/health/system`` and verify global_status is not FAIL.

    Returns ``{"ok": bool, "label": str, "global_status": str,
    "failed_components": list[str], "component_reasons": dict[str, str], "detail": str}``.
    Excludes global_status from failed_components (it is the aggregate).
    """
    base = (base_url or _health_base_url()).rstrip("/")
    url = f"{base}/api/health/system"
    t0 = time.monotonic()
    try:
        resp = httpx.get(url, timeout=timeout_s, follow_redirects=True)
        latency_ms = (time.monotonic() - t0) * 1000
        if resp.status_code >= 500:
            return {
                "ok": False,
                "label": "system_health",
                "global_status": "HTTP_ERROR",
                "failed_components": [],
                "component_reasons": {},
                "detail": f"system_health: HTTP {resp.status_code} ({latency_ms:.0f}ms)",
            }
        body = resp.json() if resp.status_code < 400 else {}
        global_status = str(body.get("global_status", "UNKNOWN")).upper()
        failed: list[str] = []
        reasons: dict[str, str] = {}
        skip_keys = {"global_status", "timestamp", "db_status"}
        for key, val in body.items():
            if key in skip_keys:
                continue
            if isinstance(val, dict):
                comp_status = str(val.get("status", "")).lower()
                if comp_status in ("down", "fail", "error"):
                    failed.append(key)
                    reasons[key] = _component_reason(key, val)
            elif isinstance(val, str) and val.lower() in ("down", "fail"):
                failed.append(key)
                reasons[key] = val
        ok = global_status != "FAIL" and resp.status_code < 400
        detail = f"system_health: {global_status} ({latency_ms:.0f}ms)"
        if failed:
            parts = [f"{k}: {reasons.get(k, 'fail')}" for k in failed]
            detail += f"\n  " + "\n  ".join(parts)
        return {
            "ok": ok,
            "label": "system_health",
            "global_status": global_status,
            "failed_components": failed,
            "component_reasons": reasons,
            "detail": detail,
        }
    except httpx.TimeoutException:
        return {
            "ok": False,
            "label": "system_health",
            "global_status": "TIMEOUT",
            "failed_components": [],
            "component_reasons": {},
            "detail": f"system_health: timeout after {timeout_s}s",
        }
    except Exception as exc:
        return {
            "ok": False,
            "label": "system_health",
            "global_status": "ERROR",
            "failed_components": [],
            "component_reasons": {},
            "detail": f"system_health: {type(exc).__name__}: {exc}",
        }


# ---------------------------------------------------------------------------
# Core: run smoke-check suite
# ---------------------------------------------------------------------------

SMOKE_PASSED = "passed"
SMOKE_FAILED = "failed"


def _notion_deploy_progress(task_id: str | None, percent: int) -> None:
    """Update Notion Deploy Progress (0-100) for task_id if provided. No-op on failure."""
    if not (task_id or "").strip():
        return
    try:
        from app.services.notion_tasks import update_notion_deploy_progress
        update_notion_deploy_progress(task_id.strip(), percent)
    except Exception:
        pass


def run_smoke_check(
    *,
    base_url: str | None = None,
    extra_endpoints: list[dict[str, str]] | None = None,
    retries: int = SMOKE_CHECK_RETRIES,
    retry_delay_s: float = SMOKE_CHECK_RETRY_DELAY_S,
    include_system_health: bool = True,
    timeout_s: float = SMOKE_CHECK_TIMEOUT_S,
    initial_delay_s: float | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Run the post-deploy smoke-check suite.

    Parameters
    ----------
    base_url:
        Base URL for the deployed backend (e.g. ``http://127.0.0.1:8002``).
        Resolved from env if not provided.
    extra_endpoints:
        Additional ``[{"url": "...", "label": "..."}]`` to check.
    retries:
        Number of retries for the liveness check before giving up.
    retry_delay_s:
        Delay between retries.
    include_system_health:
        Whether to also call ``/api/health/system`` for deep checks.
    timeout_s:
        Per-request timeout.
    initial_delay_s:
        Seconds to wait before first liveness attempt (for post-deploy: backend needs ~90s to become healthy).
        Defaults to SMOKE_CHECK_INITIAL_DELAY_S if None.
    task_id:
        Optional Notion task ID; when set, Deploy Progress (0-100) is updated at each milestone for a progress bar in Notion.

    Returns
    -------
    dict with keys:
        outcome (str): "passed" or "failed"
        ok (bool): True if all checks passed.
        checks (list[dict]): Individual check results.
        summary (str): Human-readable one-liner.
        duration_ms (float): Total wall-clock time.
    """
    base = (base_url or _health_base_url()).rstrip("/")
    checks: list[dict[str, Any]] = []
    t_start = time.monotonic()

    _notion_deploy_progress(task_id, 30)

    delay = initial_delay_s if initial_delay_s is not None else SMOKE_CHECK_INITIAL_DELAY_S
    if delay > 0:
        logger.info("smoke_check: waiting %.0fs for backend to become healthy (post-deploy)", delay)
        time.sleep(delay)
    _notion_deploy_progress(task_id, 35)

    # --- 1. Liveness: /ping_fast (lightweight, same as Docker healthcheck) ---
    liveness_url = f"{base}/ping_fast"
    liveness_ok = False
    liveness_result: dict[str, Any] = {}
    for attempt in range(1, retries + 1):
        liveness_result = check_endpoint(liveness_url, label="liveness", timeout_s=timeout_s)
        if liveness_result["ok"]:
            liveness_ok = True
            break
        if attempt < retries:
            logger.info(
                "smoke_check: liveness attempt %d/%d failed, retrying in %.1fs — %s",
                attempt, retries, retry_delay_s, liveness_result["detail"],
            )
            time.sleep(retry_delay_s)
    liveness_result["attempts"] = attempt
    checks.append(liveness_result)
    if liveness_ok:
        _notion_deploy_progress(task_id, 55)

    if not liveness_ok:
        _notion_deploy_progress(task_id, 100)
        duration_ms = (time.monotonic() - t_start) * 1000
        summary = f"Smoke check FAILED: liveness check failed after {retries} attempts — {liveness_result['detail']}"
        logger.warning("smoke_check: %s", summary)
        return {
            "outcome": SMOKE_FAILED,
            "ok": False,
            "checks": checks,
            "summary": summary,
            "duration_ms": round(duration_ms, 1),
        }

    # --- 2. System health (optional deep check, with retries for startup timing) ---
    if include_system_health:
        sys_retries = int(os.environ.get("SMOKE_CHECK_SYSTEM_HEALTH_RETRIES", str(SMOKE_CHECK_SYSTEM_HEALTH_RETRIES)))
        sys_retry_delay = float(os.environ.get("SMOKE_CHECK_SYSTEM_HEALTH_RETRY_DELAY_S", str(SMOKE_CHECK_SYSTEM_HEALTH_RETRY_DELAY_S)))
        sys_result: dict[str, Any] = {}
        for sys_attempt in range(1, sys_retries + 1):
            sys_result = check_system_health(base, timeout_s=timeout_s)
            if sys_result["ok"]:
                break
            if sys_attempt < sys_retries:
                logger.info(
                    "smoke_check: system_health attempt %d/%d failed (may be startup timing), retrying in %.0fs — %s",
                    sys_attempt, sys_retries, sys_retry_delay, sys_result.get("detail", "")[:120],
                )
                time.sleep(sys_retry_delay)
        checks.append(sys_result)
        if not sys_result["ok"]:
            _notion_deploy_progress(task_id, 100)
            duration_ms = (time.monotonic() - t_start) * 1000
            summary = f"Smoke check FAILED: {sys_result['detail']}"
            logger.warning("smoke_check: %s", summary)
            return {
                "outcome": SMOKE_FAILED,
                "ok": False,
                "checks": checks,
                "summary": summary,
                "duration_ms": round(duration_ms, 1),
            }
        _notion_deploy_progress(task_id, 85)

    # --- 3. Extra endpoints ---
    for ep in extra_endpoints or []:
        ep_url = ep.get("url", "")
        ep_label = ep.get("label", ep_url)
        if not ep_url:
            continue
        ep_result = check_endpoint(ep_url, label=ep_label, timeout_s=timeout_s)
        checks.append(ep_result)
        if not ep_result["ok"]:
            _notion_deploy_progress(task_id, 100)
            duration_ms = (time.monotonic() - t_start) * 1000
            summary = f"Smoke check FAILED: {ep_result['detail']}"
            logger.warning("smoke_check: %s", summary)
            return {
                "outcome": SMOKE_FAILED,
                "ok": False,
                "checks": checks,
                "summary": summary,
                "duration_ms": round(duration_ms, 1),
            }

    # --- All passed ---
    _notion_deploy_progress(task_id, 100)
    duration_ms = (time.monotonic() - t_start) * 1000
    n = len(checks)
    summary = f"Smoke check PASSED: {n} check{'s' if n != 1 else ''} OK ({duration_ms:.0f}ms)"
    logger.info("smoke_check: %s", summary)
    return {
        "outcome": SMOKE_PASSED,
        "ok": True,
        "checks": checks,
        "summary": summary,
        "duration_ms": round(duration_ms, 1),
    }


# ---------------------------------------------------------------------------
# Record result and advance lifecycle
# ---------------------------------------------------------------------------


def record_smoke_check_result(
    task_id: str,
    smoke_result: dict[str, Any],
    *,
    advance_on_pass: bool = True,
    current_status: str = "",
) -> dict[str, Any]:
    """Persist a smoke-check result to Notion and conditionally advance the task.

    Parameters
    ----------
    task_id:
        Notion page ID.
    smoke_result:
        Output of ``run_smoke_check()``.
    advance_on_pass:
        If True and smoke check passed, move the task from ``deploying``
        to ``done``.
    current_status:
        Hint for the task's current status. Used to guard transitions.

    Returns
    -------
    dict with keys:
        ok (bool), outcome (str), advanced (bool), advanced_to (str),
        blocked (bool), summary (str)
    """
    task_id = (task_id or "").strip()
    outcome = smoke_result.get("outcome", SMOKE_FAILED)
    summary = smoke_result.get("summary", "")
    timestamp = _utc_now_iso()

    if not task_id:
        logger.warning("record_smoke_check_result: empty task_id")
        return {
            "ok": False, "outcome": outcome, "advanced": False,
            "advanced_to": "", "blocked": False, "summary": summary,
            "error": "empty task_id",
        }

    # --- 1. Write final_result metadata ---
    meta_ok = False
    try:
        from app.services.notion_tasks import update_notion_task_metadata
        meta_label = f"smoke-check: {outcome}"
        update_notion_task_metadata(
            task_id,
            {"final_result": f"{meta_label} — {summary[:180]}"},
            append_comment=f"[{timestamp}] Post-deploy smoke check: {outcome} — {summary[:300]}",
        )
        meta_ok = True
    except Exception as exc:
        logger.warning("record_smoke_check_result: metadata write failed task_id=%s: %s", task_id, exc)

    # --- 2. Advance or block ---
    advanced = False
    advanced_to = ""
    blocked = False

    if outcome == SMOKE_PASSED and advance_on_pass:
        try:
            from app.services.notion_tasks import TASK_STATUS_DONE, update_notion_task_status
            ok = update_notion_task_status(
                task_id,
                TASK_STATUS_DONE,
                append_comment=f"[{timestamp}] Smoke check passed — task marked done.",
            )
            if ok:
                advanced = True
                advanced_to = TASK_STATUS_DONE
                logger.info("record_smoke_check_result: advanced task_id=%s to done", task_id)
            else:
                logger.warning("record_smoke_check_result: status advance to done failed task_id=%s", task_id)
        except Exception as exc:
            logger.warning("record_smoke_check_result: advance failed task_id=%s: %s", task_id, exc)

    elif outcome == SMOKE_FAILED:
        try:
            from app.services.notion_tasks import TASK_STATUS_BLOCKED, update_notion_task_status
            ok = update_notion_task_status(
                task_id,
                TASK_STATUS_BLOCKED,
                append_comment=f"[{timestamp}] Smoke check FAILED — task blocked. Details: {summary[:300]}",
            )
            if ok:
                blocked = True
                logger.info("record_smoke_check_result: blocked task_id=%s (smoke check failed)", task_id)
            else:
                logger.warning("record_smoke_check_result: block status update failed task_id=%s", task_id)
        except Exception as exc:
            logger.warning("record_smoke_check_result: block failed task_id=%s: %s", task_id, exc)

    # --- 3. Activity log ---
    try:
        from app.services.agent_activity_log import log_agent_event
        log_agent_event(
            "smoke_check_recorded",
            task_id=task_id,
            details={
                "outcome": outcome,
                "summary": summary[:300],
                "advanced": advanced,
                "advanced_to": advanced_to,
                "blocked": blocked,
                "checks": [c.get("detail", "") for c in smoke_result.get("checks", [])],
            },
        )
    except Exception:
        pass

    return {
        "ok": meta_ok or advanced or blocked,
        "outcome": outcome,
        "advanced": advanced,
        "advanced_to": advanced_to,
        "blocked": blocked,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# Convenience: run + record in one call
# ---------------------------------------------------------------------------


def run_and_record_smoke_check(
    task_id: str,
    *,
    base_url: str | None = None,
    extra_endpoints: list[dict[str, str]] | None = None,
    advance_on_pass: bool = True,
    current_status: str = "",
    include_system_health: bool = True,
    retries: int = SMOKE_CHECK_RETRIES,
    retry_delay_s: float = SMOKE_CHECK_RETRY_DELAY_S,
) -> dict[str, Any]:
    """Run the full smoke-check suite and record the result.

    Combines ``run_smoke_check()`` and ``record_smoke_check_result()``
    for callers that want a single entry point.

    Returns the merged result dict from both functions.
    """
    smoke = run_smoke_check(
        base_url=base_url,
        extra_endpoints=extra_endpoints,
        retries=retries,
        retry_delay_s=retry_delay_s,
        include_system_health=include_system_health,
        task_id=task_id or None,
    )
    recorded = record_smoke_check_result(
        task_id,
        smoke,
        advance_on_pass=advance_on_pass,
        current_status=current_status,
    )
    return {**smoke, **recorded}


# ---------------------------------------------------------------------------
# Format for Telegram
# ---------------------------------------------------------------------------


def format_smoke_result_for_telegram(result: dict[str, Any]) -> str:
    """Build a short HTML summary suitable for a Telegram message."""
    outcome = result.get("outcome", "unknown")
    icon = "\u2705" if outcome == SMOKE_PASSED else "\u274c"
    lines = [f"{icon} <b>Smoke check: {outcome}</b>"]
    for check in result.get("checks", []):
        c_icon = "\u2705" if check.get("ok") else "\u274c"
        lines.append(f"  {c_icon} {check.get('detail', check.get('label', ''))}")
    dur = result.get("duration_ms")
    if dur is not None:
        lines.append(f"\nDuration: {dur:.0f}ms")
    return "\n".join(lines)
