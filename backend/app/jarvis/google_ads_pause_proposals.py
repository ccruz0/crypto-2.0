"""Deterministic Google Ads pause proposals from read-only diagnostic metrics (phase 1).

Mutations never run from here — only structured actions with execution_mode requires_approval.
"""

from __future__ import annotations

import os
import re
from typing import Any

from app.jarvis.action_policy import (
    DEFAULT_EXECUTION_MODE,
    compute_priority_score,
    get_action_policy,
)

# Tunable thresholds (env overrides for ops tuning).
_PAUSE_MIN_COST_ZERO_CONV = float(os.getenv("JARVIS_GOOGLE_ADS_PAUSE_MIN_COST", "5.0"))
_PAUSE_MAX_CTR_PCT = float(os.getenv("JARVIS_GOOGLE_ADS_PAUSE_MAX_CTR_PCT", "0.5"))
_PAUSE_MIN_IMPRESSIONS_CTR = int(os.getenv("JARVIS_GOOGLE_ADS_PAUSE_MIN_IMPRESSIONS", "500"))


def _parse_ctr_display_pct(ctr_str: str) -> float | None:
    """Parse '4.00%' -> 4.0 (display percent, not ratio)."""
    m = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*%?\s*$", (ctr_str or "").strip())
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _cost_float(cost: Any) -> float:
    try:
        return float(str(cost or "0").replace(",", "."))
    except ValueError:
        return 0.0


def _pick_single_pause_candidate(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """
    At most one campaign per mission (no bulk).
    Priority:
    1) ENABLED campaign with highest spend among zero-conversion rows (cost >= threshold).
    2) Else ENABLED campaign with lowest CTR (display %) among rows with enough impressions.
    """
    enabled = [
        r
        for r in rows
        if isinstance(r, dict)
        and str(r.get("status") or "").upper() == "ENABLED"
        and int(r.get("campaign_id") or 0) > 0
    ]
    if not enabled:
        return None

    zero_conv: list[dict[str, Any]] = []
    for r in enabled:
        conv = float(r.get("conversions") or 0.0)
        cost = _cost_float(r.get("cost"))
        if conv == 0.0 and cost >= _PAUSE_MIN_COST_ZERO_CONV:
            zero_conv.append(r)
    if zero_conv:
        zero_conv.sort(key=lambda x: _cost_float(x.get("cost")), reverse=True)
        r = zero_conv[0]
        trigger_rule = (
            f"Gasto ≥ {_PAUSE_MIN_COST_ZERO_CONV:g} (moneda de la cuenta) y conversiones = 0 "
            f"en la ventana agregada por campaña (últimos 30 días, GAQL read-only)."
        )
        expected_benefit = (
            "Evitar seguir gastando en clics que no convierten mientras revisas creatividades, "
            "audiencias y palabras clave."
        )
        return {
            "row": r,
            "rule_key": "high_cost_zero_conversions",
            "trigger_rule": trigger_rule,
            "expected_benefit": expected_benefit,
            "reason": (
                f"Alto gasto ({r.get('cost')}) sin conversiones en la ventana; "
                f"proponer pausa para revisar creatividades y segmentación."
            ),
        }

    low_ctr: list[tuple[float, dict[str, Any]]] = []
    for r in enabled:
        impr = int(r.get("impressions") or 0)
        if impr < _PAUSE_MIN_IMPRESSIONS_CTR:
            continue
        pct = _parse_ctr_display_pct(str(r.get("ctr") or ""))
        if pct is None:
            continue
        if pct < _PAUSE_MAX_CTR_PCT:
            low_ctr.append((pct, r))
    if not low_ctr:
        return None
    low_ctr.sort(key=lambda t: t[0])
    r = low_ctr[0][1]
    trigger_rule = (
        f"CTR en pantalla < {_PAUSE_MAX_CTR_PCT:g}% con impresiones ≥ {_PAUSE_MIN_IMPRESSIONS_CTR} "
        f"(últimos 30 días agregados por campaña; valor observado {r.get('ctr')})."
    )
    expected_benefit = (
        "Reducir impresiones con bajo rendimiento mientras afinas anuncios y segmentación; "
        "la pausa es reversible al reactivar la campaña."
    )
    return {
        "row": r,
        "rule_key": "low_ctr_threshold",
        "trigger_rule": trigger_rule,
        "expected_benefit": expected_benefit,
        "reason": (
            f"CTR muy bajo ({r.get('ctr')}) con tráfico suficiente (impr. {r.get('impressions')}); "
            f"proponer pausa para revisar anuncios y palabras clave."
        ),
    }


def build_google_ads_pause_campaign_actions(readonly_diagnostic: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Build at most one google_ads_pause_campaign action from a diagnose_google_ads_setup result dict.
    """
    if not isinstance(readonly_diagnostic, dict):
        return []
    rows = readonly_diagnostic.get("analytics_top_campaigns")
    if not isinstance(rows, list) or not rows:
        return []
    picked = _pick_single_pause_candidate([x for x in rows if isinstance(x, dict)])
    if picked is None:
        return []
    r = picked["row"]
    reason = str(picked.get("reason") or "").strip()
    trigger_rule = str(picked.get("trigger_rule") or "").strip()
    expected_benefit = str(picked.get("expected_benefit") or "").strip()
    rule_key = str(picked.get("rule_key") or "").strip()
    cid = int(r.get("campaign_id") or 0)
    name = str(r.get("name") or "").strip()
    if cid <= 0 or not name:
        return []

    policy = get_action_policy("google_ads_pause_campaign")
    execution_mode = str(policy.get("execution_mode") or DEFAULT_EXECUTION_MODE).strip().lower()
    if execution_mode == "approval_required":
        execution_mode = "requires_approval"
    confidence = 0.88
    action: dict[str, Any] = {
        "title": f"Pausar campaña Google Ads «{name}»",
        "rationale": reason,
        "action_type": "google_ads_pause_campaign",
        "params": {
            "campaign_id": str(cid),
            "campaign_name": name,
            "reason": reason,
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
            action_type="google_ads_pause_campaign",
            impact="high",
            confidence=confidence,
        ),
    }
    return [action]


def format_google_ads_pause_approval_summary(action: dict[str, Any]) -> str:
    """Operator-facing block for Telegram / Notion approval (Spanish, business-first)."""
    p = action.get("params") if isinstance(action.get("params"), dict) else {}
    name = str(p.get("campaign_name") or "—").strip()
    cid = str(p.get("campaign_id") or "—").strip()
    cost = str(p.get("cost") if p.get("cost") is not None else "—")
    conv = p.get("conversions")
    if isinstance(conv, (int, float)):
        conv_s = f"{float(conv):g}"
    else:
        conv_s = str(conv) if conv is not None else "—"
    ctr = str(p.get("ctr") or "—")
    impr = p.get("impressions")
    impr_s = str(int(impr)) if isinstance(impr, (int, float)) else str(impr or "—")
    clk = p.get("clicks")
    clk_s = str(int(clk)) if isinstance(clk, (int, float)) else str(clk or "—")
    rule = str(p.get("trigger_rule") or "—").strip()
    benefit = str(p.get("expected_benefit") or "—").strip()
    rsn = str(p.get("reason") or "").strip()
    lines = [
        "Pausa propuesta (Google Ads)",
        f"• Campaña: «{name}»  ·  id {cid}",
        f"• Métricas (~30 días): coste {cost}  ·  conv. {conv_s}  ·  CTR {ctr}  ·  impr. {impr_s}  ·  clics {clk_s}",
        f"• Regla: {rule}",
    ]
    if rsn:
        lines.append(f"• Motivo: {rsn}")
    if benefit:
        lines.append(f"• Beneficio esperado: {benefit}")
    return "\n".join(lines)


def extract_google_ads_readonly_diagnostic_result(execution: dict[str, Any]) -> dict[str, Any] | None:
    """Best diagnose_google_ads_setup result from an ExecutionAgent payload."""
    best: dict[str, Any] | None = None
    for row in execution.get("executed") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("action_type") or "").strip().lower() != "diagnose_google_ads_setup":
            continue
        res = row.get("result")
        if isinstance(res, dict) and res.get("auth_ok") and res.get("campaign_fetch_ok"):
            best = res
    return best


# Re-export for budget proposal module (same thresholds / parsers).
PAUSE_MIN_COST_ZERO_CONV = _PAUSE_MIN_COST_ZERO_CONV
PAUSE_MAX_CTR_PCT = _PAUSE_MAX_CTR_PCT
parse_ctr_display_pct = _parse_ctr_display_pct
cost_float = _cost_float
