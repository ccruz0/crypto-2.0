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

SMOKE_CHECK_TIMEOUT_S = 10
SMOKE_CHECK_RETRIES = 3
SMOKE_CHECK_RETRY_DELAY_S = 5


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


def check_system_health(
    base_url: str | None = None,
    *,
    timeout_s: float = SMOKE_CHECK_TIMEOUT_S,
) -> dict[str, Any]:
    """Call ``/api/health/system`` and verify global_status is not FAIL.

    Returns ``{"ok": bool, "label": str, "global_status": str,
    "failed_components": list[str], "detail": str}``.
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
                "detail": f"system_health: HTTP {resp.status_code} ({latency_ms:.0f}ms)",
            }
        body = resp.json() if resp.status_code < 400 else {}
        global_status = str(body.get("global_status", "UNKNOWN")).upper()
        failed = []
        for key, val in body.items():
            if isinstance(val, dict) and str(val.get("status", "")).lower() in ("down", "fail", "error"):
                failed.append(key)
            elif isinstance(val, str) and val.lower() in ("down", "fail"):
                failed.append(key)
        ok = global_status != "FAIL" and resp.status_code < 400
        detail = f"system_health: {global_status} ({latency_ms:.0f}ms)"
        if failed:
            detail += f" — degraded: {', '.join(failed)}"
        return {
            "ok": ok,
            "label": "system_health",
            "global_status": global_status,
            "failed_components": failed,
            "detail": detail,
        }
    except httpx.TimeoutException:
        return {
            "ok": False,
            "label": "system_health",
            "global_status": "TIMEOUT",
            "failed_components": [],
            "detail": f"system_health: timeout after {timeout_s}s",
        }
    except Exception as exc:
        return {
            "ok": False,
            "label": "system_health",
            "global_status": "ERROR",
            "failed_components": [],
            "detail": f"system_health: {type(exc).__name__}: {exc}",
        }


# ---------------------------------------------------------------------------
# Core: run smoke-check suite
# ---------------------------------------------------------------------------

SMOKE_PASSED = "passed"
SMOKE_FAILED = "failed"


def run_smoke_check(
    *,
    base_url: str | None = None,
    extra_endpoints: list[dict[str, str]] | None = None,
    retries: int = SMOKE_CHECK_RETRIES,
    retry_delay_s: float = SMOKE_CHECK_RETRY_DELAY_S,
    include_system_health: bool = True,
    timeout_s: float = SMOKE_CHECK_TIMEOUT_S,
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

    # --- 1. Liveness: /api/health (with retries) ---
    liveness_url = f"{base}/api/health"
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

    if not liveness_ok:
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

    # --- 2. System health (optional deep check) ---
    if include_system_health:
        sys_result = check_system_health(base, timeout_s=timeout_s)
        checks.append(sys_result)
        if not sys_result["ok"]:
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

    # --- 3. Extra endpoints ---
    for ep in extra_endpoints or []:
        ep_url = ep.get("url", "")
        ep_label = ep.get("label", ep_url)
        if not ep_url:
            continue
        ep_result = check_endpoint(ep_url, label=ep_label, timeout_s=timeout_s)
        checks.append(ep_result)
        if not ep_result["ok"]:
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
