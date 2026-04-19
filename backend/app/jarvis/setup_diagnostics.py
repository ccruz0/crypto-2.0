"""Shared GA4/GSC runtime setup diagnostics (read-only container env inspection)."""

from __future__ import annotations

from typing import Any

from app.jarvis import ops_tools


def _diag(message: str, *, severity: str = "info", code: str = "") -> dict[str, Any]:
    return {
        "severity": severity,
        "message": message,
        "code": code or severity,
    }


def diagnose_ga4_setup_bundle(params: dict[str, Any]) -> dict[str, Any]:
    """Same payload shape as legacy OpsAgent._diagnose_ga4_setup."""
    container = str(params.get("container_name") or "backend-aws").strip()
    env_res = ops_tools.inspect_container_env(container, env_prefixes=["JARVIS_GA4_", "GA_"])
    env_map = env_res.get("env") if isinstance(env_res.get("env"), dict) else {}
    missing = [
        k for k in ("JARVIS_GA4_PROPERTY_ID", "JARVIS_GA4_CREDENTIALS_JSON") if not str(env_map.get(k) or "").strip()
    ]
    diagnostics: list[dict[str, Any]] = []
    waiting: list[dict[str, Any]] = []
    if missing:
        diagnostics.append(
            _diag(
                "Google Analytics is not configured: missing env vars in running container: " + ", ".join(missing),
                severity="error",
                code="ga4_missing_env",
            )
        )
        waiting.append(
            {
                "action_type": "update_runtime_env",
                "title": "Update runtime env for GA4 settings",
                "params": {"keys": missing},
                "execution_mode": "requires_approval",
                "priority_score": 91,
            }
        )
    else:
        diagnostics.append(_diag("GA4 runtime env appears configured.", severity="info", code="ga4_ok"))
    return {
        "diagnostics": diagnostics,
        "proposed_fixes": waiting,
        "waiting_for_approval": waiting,
        "waiting_for_input": [],
        "result": {"missing_env_vars": missing},
    }


def diagnose_gsc_setup_bundle(params: dict[str, Any]) -> dict[str, Any]:
    """Same payload shape as legacy OpsAgent._diagnose_gsc_setup."""
    container = str(params.get("container_name") or "backend-aws").strip()
    env_res = ops_tools.inspect_container_env(container, env_prefixes=["JARVIS_GSC_"])
    env_map = env_res.get("env") if isinstance(env_res.get("env"), dict) else {}
    missing = [
        k for k in ("JARVIS_GSC_SITE_URL", "JARVIS_GSC_CREDENTIALS_JSON") if not str(env_map.get(k) or "").strip()
    ]
    diagnostics: list[dict[str, Any]] = []
    waiting: list[dict[str, Any]] = []
    if missing:
        diagnostics.append(
            _diag(
                "Google Search Console is not configured: missing env vars in running container: "
                + ", ".join(missing),
                severity="error",
                code="gsc_missing_env",
            )
        )
        waiting.append(
            {
                "action_type": "update_runtime_env",
                "title": "Update runtime env for GSC settings",
                "params": {"keys": missing},
                "execution_mode": "requires_approval",
                "priority_score": 90,
            }
        )
    else:
        diagnostics.append(_diag("GSC runtime env appears configured.", severity="info", code="gsc_ok"))
    return {
        "diagnostics": diagnostics,
        "proposed_fixes": waiting,
        "waiting_for_approval": waiting,
        "waiting_for_input": [],
        "result": {"missing_env_vars": missing},
    }


def flatten_ga4_execution_result(bundle: dict[str, Any]) -> dict[str, Any]:
    """Normalize GA4 diagnostic row for goal satisfaction."""
    inner = bundle.get("result") if isinstance(bundle.get("result"), dict) else {}
    missing = list(inner.get("missing_env_vars") or [])
    out: dict[str, Any] = {
        "missing_env_vars": missing,
        "env_configured": len(missing) == 0,
    }
    for k in (
        "analytics_top_pages",
        "analytics_top_events",
        "analytics_summary",
        "analytics_issues",
        "analytics_opportunities",
        "analytics_query_error",
    ):
        if k in inner:
            out[k] = inner[k]
    return out


def flatten_gsc_execution_result(bundle: dict[str, Any]) -> dict[str, Any]:
    """Normalize GSC diagnostic row for goal satisfaction."""
    inner = bundle.get("result") if isinstance(bundle.get("result"), dict) else {}
    missing = list(inner.get("missing_env_vars") or [])
    out: dict[str, Any] = {
        "missing_env_vars": missing,
        "env_configured": len(missing) == 0,
    }
    for k in (
        "analytics_top_queries",
        "analytics_top_pages",
        "analytics_summary",
        "analytics_issues",
        "analytics_opportunities",
        "analytics_query_error",
    ):
        if k in inner:
            out[k] = inner[k]
    return out
