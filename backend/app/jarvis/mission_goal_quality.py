"""Natural clarification, goal satisfaction, and corrective action helpers for Jarvis missions."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.jarvis.action_policy import (
    DEFAULT_EXECUTION_MODE,
    compute_priority_score,
    get_action_policy,
)
from app.jarvis.analytics_mission_deliverables import (
    AnalyticsMissionSpec,
    deliverables_to_dict,
    infer_analytics_deliverables,
)
from app.jarvis.analytics_prompt_gates import readonly_analytics_prompt_sufficient


def _sanitize_telegram_plain(text: str) -> str:
    """Reduce Telegram HTML parse errors from angle brackets in model text."""
    return (text or "").replace("<", "(").replace(">", ")").strip()


def _fold_for_spanish_check(s: str) -> str:
    """Lowercase ASCII fold (strip accents) for simple Spanish vs English heuristics."""
    decomposed = unicodedata.normalize("NFD", s or "")
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return stripped.lower()


# Operator-facing clarification when the planner needs more context (always Spanish).
_SPANISH_CLARIFICATION_FALLBACK = (
    "Puedo hacerlo. Antes de seguir: ¿qué alcance quieres (periodo, cuenta o cómo quieres ver resumidos los resultados)?"
)

# If Bedrock returns English, we discard and use _SPANISH_CLARIFICATION_FALLBACK (product UX).
_ENGLISH_CLARIFICATION_LEAD = re.compile(
    r"^\s*(what|which|how|should|could|would|do|does|did|is|are|was|were|can|may|please|tell|give)\b",
    re.I,
)
_SPANISH_CLARIFICATION_MARKERS = re.compile(
    r"\b(que|quien|quienes|como|cual|cuales|donde|cuando|cuanto|cuantos|cuantas|porque|"
    r"puedes|quieres|debes|indica|especifica|alcance|cuenta|periodo|resumen|hago|debo|"
    r"necesitas|prefieres|incluir|usar|dias)\b",
    re.I,
)


def clarification_question_looks_spanish(q: str) -> bool:
    """
    Lightweight check so operator-facing clarification stays in Spanish.

    If uncertain, returns False (caller should use the Spanish fallback).
    """
    raw = (q or "").strip()
    if not raw:
        return False
    if "¿" in raw:
        return True
    t = _fold_for_spanish_check(raw)
    if _ENGLISH_CLARIFICATION_LEAD.match(t):
        return False
    if _SPANISH_CLARIFICATION_MARKERS.search(t):
        return True
    return False


def pick_google_ads_diagnostic_result(execution: dict[str, Any]) -> dict[str, Any] | None:
    """Prefer an executed row whose result includes analytics rows."""
    candidates: list[dict[str, Any]] = []
    for row in execution.get("executed") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("action_type") or "").strip().lower() != "diagnose_google_ads_setup":
            continue
        r = row.get("result")
        if isinstance(r, dict):
            candidates.append(r)
    if not candidates:
        return None
    for res in candidates:
        rows = res.get("analytics_top_campaigns")
        if isinstance(rows, list) and rows:
            return res
    return candidates[0]


def pick_ga4_diagnostic_result(execution: dict[str, Any]) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for row in execution.get("executed") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("action_type") or "").strip().lower() != "diagnose_ga4_setup":
            continue
        r = row.get("result")
        if isinstance(r, dict):
            candidates.append(r)
    if not candidates:
        return None
    for res in candidates:
        if res.get("ga4_analytics_fetch_ok") and (
            (isinstance(res.get("analytics_top_pages"), list) and res["analytics_top_pages"])
            or (isinstance(res.get("analytics_top_events"), list) and res["analytics_top_events"])
        ):
            return res
    for res in candidates:
        pages = res.get("analytics_top_pages")
        events = res.get("analytics_top_events")
        if (isinstance(pages, list) and pages) or (isinstance(events, list) and events):
            return res
    return candidates[0]


def pick_gsc_diagnostic_result(execution: dict[str, Any]) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for row in execution.get("executed") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("action_type") or "").strip().lower() != "diagnose_gsc_setup":
            continue
        r = row.get("result")
        if isinstance(r, dict):
            candidates.append(r)
    if not candidates:
        return None
    for res in candidates:
        queries = res.get("analytics_top_queries")
        pages = res.get("analytics_top_pages")
        if (isinstance(queries, list) and queries) or (isinstance(pages, list) and pages):
            return res
    return candidates[0]


def _goal_base(
    *,
    satisfied: bool,
    missing_items: list[str],
    reason: str,
    auto_retry_recommended: bool,
    spec: AnalyticsMissionSpec | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "satisfied": satisfied,
        "missing_items": missing_items,
        "reason": reason,
        "auto_retry_recommended": auto_retry_recommended,
    }
    if spec is not None:
        out["evaluator_domain"] = spec.domain
        out["deliverables"] = deliverables_to_dict(spec)
    return out


def _evaluate_google_ads_readonly_analytics(
    execution: dict[str, Any], *, spec: AnalyticsMissionSpec
) -> dict[str, Any]:
    res = pick_google_ads_diagnostic_result(execution)
    missing: list[str] = []
    if res is None:
        missing.append("google_ads_diagnostic_execution")
        return _goal_base(
            satisfied=False,
            missing_items=missing,
            reason="read_only_google_ads_rubric",
            auto_retry_recommended=True,
            spec=spec,
        )
    if not res.get("auth_ok"):
        missing.append("google_ads_authentication")
    if not res.get("campaign_fetch_ok"):
        missing.append("google_ads_campaign_data")
    rows = res.get("analytics_top_campaigns")
    if not isinstance(rows, list) or len(rows) == 0:
        missing.append("google_ads_performance_metrics")
    summary = str(res.get("analytics_summary") or "").strip()
    if not summary:
        missing.append("google_ads_summary")
    issues = res.get("analytics_issues")
    opps = res.get("analytics_opportunities")
    has_issue = isinstance(issues, list) and any(str(x).strip() for x in issues)
    has_opp = isinstance(opps, list) and any(str(x).strip() for x in opps)
    if not (has_issue or has_opp):
        missing.append("google_ads_insights")
    if missing:
        shallow = "google_ads_performance_metrics" in missing and bool(res.get("campaign_fetch_ok"))
        return _goal_base(
            satisfied=False,
            missing_items=missing,
            reason="read_only_google_ads_rubric",
            auto_retry_recommended=bool(shallow),
            spec=spec,
        )
    return _goal_base(
        satisfied=True,
        missing_items=[],
        reason="read_only_google_ads_rubric",
        auto_retry_recommended=False,
        spec=spec,
    )


def _evaluate_ga4_readonly_analytics(execution: dict[str, Any], *, spec: AnalyticsMissionSpec) -> dict[str, Any]:
    res = pick_ga4_diagnostic_result(execution)
    if res is None:
        return _goal_base(
            satisfied=False,
            missing_items=["ga4_diagnostic_execution"],
            reason="read_only_ga4_rubric",
            auto_retry_recommended=True,
            spec=spec,
        )
    missing_env = res.get("missing_env_vars") or []
    if isinstance(missing_env, list) and len(missing_env) > 0:
        return _goal_base(
            satisfied=False,
            missing_items=["ga4_configuration"],
            reason="read_only_ga4_rubric",
            auto_retry_recommended=False,
            spec=spec,
        )

    pages = res.get("analytics_top_pages")
    events = res.get("analytics_top_events")
    if not isinstance(pages, list):
        pages = []
    if not isinstance(events, list):
        events = []
    has_ranked = len(pages) > 0 or len(events) > 0
    query_err_raw = str(res.get("analytics_query_error") or "").strip()
    query_err = query_err_raw.lower()
    fetch_flag = res.get("ga4_analytics_fetch_ok")
    if fetch_flag is None:
        if has_ranked:
            fetch_ok = True
        elif query_err_raw:
            fetch_ok = False
        else:
            return _goal_base(
                satisfied=False,
                missing_items=["ga4_readonly_analytics_unavailable"],
                reason="read_only_ga4_rubric",
                auto_retry_recommended=False,
                spec=spec,
            )
    else:
        fetch_ok = bool(fetch_flag)

    if not fetch_ok:
        if any(x in query_err for x in ("permission", "forbidden", "unauthenticated", "401", "403")):
            return _goal_base(
                satisfied=False,
                missing_items=["ga4_authentication"],
                reason="read_only_ga4_rubric",
                auto_retry_recommended=False,
                spec=spec,
            )
        return _goal_base(
            satisfied=False,
            missing_items=["ga4_api_error"],
            reason="read_only_ga4_rubric",
            auto_retry_recommended=False,
            spec=spec,
        )

    if not has_ranked:
        shallow = bool(res.get("env_configured")) and fetch_ok
        return _goal_base(
            satisfied=False,
            missing_items=["ga4_performance_metrics"],
            reason="read_only_ga4_rubric",
            auto_retry_recommended=bool(shallow),
            spec=spec,
        )

    missing: list[str] = []
    summary = str(res.get("analytics_summary") or "").strip()
    if not summary:
        missing.append("ga4_summary")
    issues = res.get("analytics_issues")
    opps = res.get("analytics_opportunities")
    has_issue = isinstance(issues, list) and any(str(x).strip() for x in issues)
    has_opp = isinstance(opps, list) and any(str(x).strip() for x in opps)
    if not (has_issue or has_opp):
        missing.append("ga4_insights")
    if missing:
        return _goal_base(
            satisfied=False,
            missing_items=missing,
            reason="read_only_ga4_rubric",
            auto_retry_recommended=False,
            spec=spec,
        )
    return _goal_base(
        satisfied=True,
        missing_items=[],
        reason="read_only_ga4_rubric",
        auto_retry_recommended=False,
        spec=spec,
    )


def _evaluate_gsc_readonly_analytics(execution: dict[str, Any], *, spec: AnalyticsMissionSpec) -> dict[str, Any]:
    res = pick_gsc_diagnostic_result(execution)
    if res is None:
        return _goal_base(
            satisfied=False,
            missing_items=["gsc_diagnostic_execution"],
            reason="read_only_gsc_rubric",
            auto_retry_recommended=True,
            spec=spec,
        )
    missing_env = res.get("missing_env_vars") or []
    if isinstance(missing_env, list) and len(missing_env) > 0:
        return _goal_base(
            satisfied=False,
            missing_items=["gsc_configuration"],
            reason="read_only_gsc_rubric",
            auto_retry_recommended=False,
            spec=spec,
        )
    queries = res.get("analytics_top_queries")
    pages = res.get("analytics_top_pages")
    has_ranked = (isinstance(queries, list) and len(queries) > 0) or (isinstance(pages, list) and len(pages) > 0)
    if not has_ranked:
        return _goal_base(
            satisfied=False,
            missing_items=["gsc_readonly_analytics_unavailable"],
            reason="read_only_gsc_rubric",
            auto_retry_recommended=False,
            spec=spec,
        )
    missing: list[str] = []
    summary = str(res.get("analytics_summary") or "").strip()
    if not summary:
        missing.append("gsc_summary")
    issues = res.get("analytics_issues")
    opps = res.get("analytics_opportunities")
    has_issue = isinstance(issues, list) and any(str(x).strip() for x in issues)
    has_opp = isinstance(opps, list) and any(str(x).strip() for x in opps)
    if not (has_issue or has_opp):
        missing.append("gsc_insights")
    if missing:
        return _goal_base(
            satisfied=False,
            missing_items=missing,
            reason="read_only_gsc_rubric",
            auto_retry_recommended=False,
            spec=spec,
        )
    return _goal_base(
        satisfied=True,
        missing_items=[],
        reason="read_only_gsc_rubric",
        auto_retry_recommended=False,
        spec=spec,
    )


def should_attempt_goal_retry(*, mission_prompt: str, goal_eval: dict[str, Any], retry_used: bool) -> bool:
    """At most one automatic retry when the rubric recommends it (e.g. shallow Google Ads output)."""
    if retry_used:
        return False
    if goal_eval.get("satisfied"):
        return False
    if not goal_eval.get("auto_retry_recommended"):
        return False
    return readonly_analytics_prompt_sufficient(mission_prompt)


def evaluate_goal_satisfaction(*, mission_prompt: str, execution: dict[str, Any]) -> dict[str, Any]:
    """
    Compare requested scope vs delivered execution payload (strict rubrics only where defined).

    When no rubric applies, returns satisfied=True so existing missions keep current behavior.
    """
    prompt = (mission_prompt or "").strip()
    spec = infer_analytics_deliverables(prompt)
    if spec is None:
        return {"satisfied": True, "missing_items": [], "reason": "no_strict_rubric", "auto_retry_recommended": False}
    if spec.domain == "google_ads":
        return _evaluate_google_ads_readonly_analytics(execution, spec=spec)
    if spec.domain == "ga4":
        return _evaluate_ga4_readonly_analytics(execution, spec=spec)
    if spec.domain == "gsc":
        return _evaluate_gsc_readonly_analytics(execution, spec=spec)
    return {"satisfied": True, "missing_items": [], "reason": "no_strict_rubric", "auto_retry_recommended": False}


def build_corrective_readonly_analytics_action(domain: str) -> dict[str, Any]:
    """Single high-priority read-only diagnostic action for a safe retry (domain-specific)."""
    dom = (domain or "").strip().lower()
    if dom == "ga4":
        action_type = "diagnose_ga4_setup"
        title = "GA4 read-only setup diagnostics (corrective retry)"
    elif dom == "gsc":
        action_type = "diagnose_gsc_setup"
        title = "Google Search Console read-only setup diagnostics (corrective retry)"
    else:
        action_type = "diagnose_google_ads_setup"
        title = "Google Ads read-only diagnostics and metrics (corrective retry)"
    policy = get_action_policy(action_type)
    execution_mode = str(policy.get("execution_mode") or DEFAULT_EXECUTION_MODE)
    confidence = 0.95
    params: dict[str, Any] = {}
    if action_type in {"diagnose_ga4_setup", "diagnose_gsc_setup"}:
        params = {"container_name": "backend-aws"}
    return {
        "title": title,
        "rationale": "Automatic retry: prior output did not satisfy the stated read-only analytics objective.",
        "action_type": action_type,
        "params": params,
        "impact": "high",
        "confidence": confidence,
        "execution_mode": execution_mode,
        "requires_approval": execution_mode == "requires_approval",
        "priority_score": compute_priority_score(
            action_type=action_type,
            impact="high",
            confidence=confidence,
        ),
    }


def build_corrective_google_ads_diagnose_action() -> dict[str, Any]:
    """Backward-compatible wrapper for Google Ads-only corrective retry."""
    return build_corrective_readonly_analytics_action("google_ads")


def format_natural_clarification_request(*, mission_prompt: str, plan: dict[str, Any]) -> str:
    """One friendly clarification question; falls back to a soft default if Bedrock is unavailable."""
    fallback = _sanitize_telegram_plain(_SPANISH_CLARIFICATION_FALLBACK)
    try:
        from app.jarvis.bedrock_client import ask_bedrock, extract_planner_json_object

        ask = (
            "You are Jarvis, a careful autonomous operator.\n"
            "The mission needs a quick clarification before running tools.\n"
            "For analytics missions, only ask if timeframe, metrics/scope, ranking/limit, or read-only intent is unclear.\n"
            "Return JSON only: {\"question\": \"...\"}\n"
            "Rules: exactly one short question ending with ?; conversational tone; no markdown; no XML/HTML tags.\n"
            "Write the question in Spanish (natural, operational).\n"
            f"User mission:\n{mission_prompt[:900]}\n"
            f"Planner objective:\n{str(plan.get('objective') or '')[:400]}\n"
        )
        raw = ask_bedrock(ask)
        parsed = extract_planner_json_object(raw or "")
        if isinstance(parsed, dict):
            q = _sanitize_telegram_plain(str(parsed.get("question") or ""))
            if q and "?" in q and len(q) < 420 and clarification_question_looks_spanish(q):
                return q
    except Exception:
        pass
    return fallback


def format_goal_shortfall_user_message(goal: dict[str, Any]) -> str:
    """Natural-language explanation when the objective is not yet met after an automatic retry."""
    missing = goal.get("missing_items") or []
    if not isinstance(missing, list):
        missing = []
    human = {
        "google_ads_diagnostic_execution": "diagnóstico de solo lectura de Google Ads completado con éxito",
        "google_ads_authentication": "autenticación con la API de Google Ads confirmada",
        "google_ads_campaign_data": "datos a nivel de campaña en Google Ads",
        "google_ads_performance_metrics": "métricas de gasto y rendimiento (p. ej. top campañas, últimos 30 días)",
        "google_ads_summary": "un resumen cuantitativo breve",
        "google_ads_insights": "al menos un hallazgo concreto (problema u oportunidad)",
        "google_ads_top_issues": "al menos un hallazgo concreto de problema",
        "google_ads_top_opportunities": "al menos un hallazgo concreto de oportunidad",
        "ga4_diagnostic_execution": "diagnóstico de solo lectura de GA4 completado con éxito",
        "ga4_configuration": "configuración de GA4 en el entorno (property ID y credenciales)",
        "ga4_readonly_analytics_unavailable": "filas de analítica GA4 en solo lectura (puede que este build no exponga informes en vivo)",
        "ga4_performance_metrics": "páginas o eventos principales de GA4 no vacíos (p. ej. últimos 30 días)",
        "ga4_api_error": "respuesta correcta de la API de datos de GA4 (revisa credenciales, property ID y API habilitada)",
        "ga4_authentication": "acceso a la API de datos de GA4 (la cuenta de servicio necesita permisos de lectura en la propiedad)",
        "ga4_summary": "un resumen cuantitativo breve de GA4",
        "ga4_insights": "al menos un hallazgo concreto en GA4 (problema u oportunidad)",
        "gsc_diagnostic_execution": "diagnóstico de solo lectura de Search Console completado con éxito",
        "gsc_configuration": "configuración de Search Console en el entorno (URL del sitio y credenciales)",
        "gsc_readonly_analytics_unavailable": "filas de analítica de Search Console en solo lectura (puede que este build no exponga informes en vivo)",
        "gsc_summary": "un resumen cuantitativo breve de Search Console",
        "gsc_insights": "al menos un hallazgo concreto en Search Console (problema u oportunidad)",
    }
    parts = [human.get(m, m.replace("_", " ")) for m in missing if isinstance(m, str)]
    detail = ", ".join(parts[:5]) if parts else "lo que pedías en la misión"
    base = (
        "Ejecuté un pase seguro en solo lectura, pero el resultado aún no cubre del todo lo que pediste "
        f"(falta: {detail}). "
        "Responde con el detalle que falta o confirma si quieres que amplíe el análisis."
    )
    return _sanitize_telegram_plain(re.sub(r"\s+", " ", base)[:900])
