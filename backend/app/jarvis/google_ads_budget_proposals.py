"""Deterministic Google Ads campaign budget reduction proposals (phase 2).

Runs only after read-only diagnostics; never mutates here. Pause proposals take precedence
when pause heuristics match any campaign (stronger signal).
"""

from __future__ import annotations

import os
from typing import Any

from app.jarvis.action_policy import (
    DEFAULT_EXECUTION_MODE,
    compute_priority_score,
    get_action_policy,
)
from app.jarvis.google_ads_pause_proposals import (
    PAUSE_MAX_CTR_PCT,
    PAUSE_MIN_COST_ZERO_CONV,
    build_google_ads_pause_campaign_actions,
    cost_float,
    parse_ctr_display_pct,
)

_BUDGET_MIN_COST = float(os.getenv("JARVIS_GOOGLE_ADS_BUDGET_REDUCE_MIN_COST", "2.0"))
_BUDGET_REDUCE_PCT = float(os.getenv("JARVIS_GOOGLE_ADS_BUDGET_REDUCE_PCT", "20"))
_BUDGET_WEAK_CTR_HIGH = 1.2  # display % — above pause threshold, still weak


def _money_from_micros(micros: int) -> str:
    try:
        return f"{int(micros) / 1_000_000:.2f}"
    except (TypeError, ValueError):
        return "0.00"


def _enabled_rows_with_budget(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if str(r.get("status") or "").upper() != "ENABLED":
            continue
        if int(r.get("campaign_id") or 0) <= 0:
            continue
        micros = int(r.get("budget_amount_micros") or 0)
        rn = str(r.get("campaign_budget_resource_name") or "").strip()
        if micros <= 0 or not rn:
            continue
        out.append(r)
    return out


def _matches_budget_below_pause_zero_conv(r: dict[str, Any]) -> tuple[bool, str, str, str]:
    conv = float(r.get("conversions") or 0.0)
    cost = cost_float(r.get("cost"))
    if conv == 0.0 and cost >= _BUDGET_MIN_COST and cost < PAUSE_MIN_COST_ZERO_CONV:
        rule = (
            f"Gasto ≥ {_BUDGET_MIN_COST:g} y < {PAUSE_MIN_COST_ZERO_CONV:g} (moneda de la cuenta) con "
            f"conversiones = 0 en ventana agregada 30 días; por debajo del umbral de pausa automática."
        )
        benefit = (
            "Recortar el tope diario para frenar el gasto mientras investigas sin llegar a pausar toda la campaña."
        )
        return True, "budget_below_pause_spend_zero_conv", rule, benefit
    return False, "", "", ""


def _matches_budget_weak_ctr(r: dict[str, Any]) -> tuple[bool, str, str, str]:
    impr = int(r.get("impressions") or 0)
    cost = cost_float(r.get("cost"))
    pct = parse_ctr_display_pct(str(r.get("ctr") or ""))
    if impr < 400 or cost < _BUDGET_MIN_COST or pct is None:
        return False, "", "", ""
    if PAUSE_MAX_CTR_PCT <= pct < _BUDGET_WEAK_CTR_HIGH:
        rule = (
            f"CTR entre {PAUSE_MAX_CTR_PCT:g}% y {_BUDGET_WEAK_CTR_HIGH:g}% (valor {r.get('ctr')}) con "
            f"≥400 impresiones y gasto ≥ {_BUDGET_MIN_COST:g}; no cumple umbral de pausa por CTR."
        )
        benefit = (
            "Bajar presupuesto para limitar exposición mientras mejoras creatividades y segmentación, "
            "manteniendo la campaña activa."
        )
        return True, "budget_weak_ctr_not_pause", rule, benefit
    return False, "", "", ""


def _matches_budget_poor_conv_efficiency(r: dict[str, Any]) -> tuple[bool, str, str, str]:
    clk = int(r.get("clicks") or 0)
    conv = float(r.get("conversions") or 0.0)
    cost = cost_float(r.get("cost"))
    if clk < 20 or cost < _BUDGET_MIN_COST:
        return False, "", "", ""
    rate = conv / clk if clk else 0.0
    if conv >= 0.5 and rate < 0.015:
        rule = (
            f"Eficiencia de conversión baja: {conv:g} conv. / {clk} clics "
            f"(ratio {rate * 100:.2f}% del volumen de clics) con gasto ≥ {_BUDGET_MIN_COST:g} en la ventana."
        )
        benefit = (
            "Reducir el ritmo de gasto para no seguir comprando clics con baja conversión hasta optimizar embudo y anuncios."
        )
        return True, "budget_poor_conv_efficiency", rule, benefit
    return False, "", "", ""


def _pick_single_budget_reduce_candidate(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """One campaign, highest spend first among rows matching a budget rule."""
    candidates = _enabled_rows_with_budget(rows)
    candidates.sort(key=lambda x: cost_float(x.get("cost")), reverse=True)
    matchers = (
        _matches_budget_below_pause_zero_conv,
        _matches_budget_weak_ctr,
        _matches_budget_poor_conv_efficiency,
    )
    for r in candidates:
        if bool(r.get("budget_explicitly_shared")):
            continue
        for fn in matchers:
            ok, key, rule, benefit = fn(r)
            if ok:
                return {"row": r, "rule_key": key, "trigger_rule": rule, "expected_benefit": benefit}
    return None


def build_google_ads_reduce_campaign_budget_actions(readonly_diagnostic: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Build at most one google_ads_reduce_campaign_budget action.
    Skipped entirely if pause heuristics match any campaign (pause is higher priority).
    """
    if not isinstance(readonly_diagnostic, dict):
        return []
    if build_google_ads_pause_campaign_actions(readonly_diagnostic):
        return []
    rows = readonly_diagnostic.get("analytics_top_campaigns")
    if not isinstance(rows, list) or not rows:
        return []
    picked = _pick_single_budget_reduce_candidate([x for x in rows if isinstance(x, dict)])
    if picked is None:
        return []
    r = picked["row"]
    rule_key = str(picked.get("rule_key") or "")
    trigger_rule = str(picked.get("trigger_rule") or "").strip()
    expected_benefit = str(picked.get("expected_benefit") or "").strip()
    cid = int(r.get("campaign_id") or 0)
    name = str(r.get("name") or "").strip()
    micros = int(r.get("budget_amount_micros") or 0)
    budget_rn = str(r.get("campaign_budget_resource_name") or "").strip()
    if cid <= 0 or not name or micros <= 0 or not budget_rn:
        return []

    pct = max(1.0, min(90.0, _BUDGET_REDUCE_PCT))
    new_micros = int(micros * (1.0 - pct / 100.0))
    if new_micros >= micros or new_micros < 1:
        return []

    policy = get_action_policy("google_ads_reduce_campaign_budget")
    execution_mode = str(policy.get("execution_mode") or DEFAULT_EXECUTION_MODE).strip().lower()
    if execution_mode == "approval_required":
        execution_mode = "requires_approval"
    confidence = 0.82
    reason = (
        f"Propuesta de recorte de presupuesto (~{pct:g}%) por rendimiento flojo; "
        f"campaña «{name}» sigue ENABLED."
    )
    action: dict[str, Any] = {
        "title": f"Reducir presupuesto (~{pct:g}%) · campaña «{name}»",
        "rationale": reason,
        "action_type": "google_ads_reduce_campaign_budget",
        "params": {
            "campaign_id": str(cid),
            "campaign_name": name,
            "campaign_budget_resource_name": budget_rn,
            "current_budget_micros": micros,
            "current_budget_amount": _money_from_micros(micros),
            "reduction_percent": pct,
            "proposed_budget_micros": new_micros,
            "proposed_budget_amount": _money_from_micros(new_micros),
            "cost": str(r.get("cost") or ""),
            "conversions": float(r.get("conversions") or 0.0),
            "ctr": str(r.get("ctr") or ""),
            "impressions": int(r.get("impressions") or 0),
            "clicks": int(r.get("clicks") or 0),
            "trigger_rule": trigger_rule,
            "expected_benefit": expected_benefit,
            "rule_key": rule_key,
        },
        "impact": "high",
        "confidence": confidence,
        "execution_mode": execution_mode,
        "requires_approval": execution_mode == "requires_approval",
        "priority_score": compute_priority_score(
            action_type="google_ads_reduce_campaign_budget",
            impact="high",
            confidence=confidence,
        ),
    }
    return [action]


def format_google_ads_budget_reduce_approval_summary(action: dict[str, Any]) -> str:
    """Operator-facing approval block (Spanish)."""
    p = action.get("params") if isinstance(action.get("params"), dict) else {}
    name = str(p.get("campaign_name") or "—").strip()
    cid = str(p.get("campaign_id") or "—").strip()
    cur = str(p.get("current_budget_amount") or "—")
    new_amt = str(p.get("proposed_budget_amount") or "—")
    pct = p.get("reduction_percent")
    pct_s = f"{float(pct):g}%" if isinstance(pct, (int, float)) else str(pct or "—")
    cost = str(p.get("cost") if p.get("cost") is not None else "—")
    conv = p.get("conversions")
    conv_s = f"{float(conv):g}" if isinstance(conv, (int, float)) else str(conv or "—")
    ctr = str(p.get("ctr") or "—")
    impr = p.get("impressions")
    impr_s = str(int(impr)) if isinstance(impr, (int, float)) else str(impr or "—")
    clk = p.get("clicks")
    clk_s = str(int(clk)) if isinstance(clk, (int, float)) else str(clk or "—")
    rule = str(p.get("trigger_rule") or "—").strip()
    benefit = str(p.get("expected_benefit") or "—").strip()
    lines = [
        "Reducción de presupuesto propuesta (Google Ads)",
        f"• Campaña: «{name}»  ·  id {cid}",
        f"• Métricas (~30 días): coste {cost}  ·  conv. {conv_s}  ·  CTR {ctr}  ·  impr. {impr_s}  ·  clics {clk_s}",
        f"• Presupuesto diario: {cur}  →  {new_amt} (−{pct_s})",
        f"• Regla: {rule}",
        f"• Beneficio esperado: {benefit}",
    ]
    return "\n".join(lines)
