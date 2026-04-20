"""Intent-driven Google Ads resume (PAUSED → ENABLED) proposals — phase 3, no auto-heuristics."""

from __future__ import annotations

import re
from typing import Any

from app.jarvis.action_policy import (
    DEFAULT_EXECUTION_MODE,
    compute_priority_score,
    get_action_policy,
)

# Explicit mission phrases only (no metric auto-triggers).
_RESUME_INTENT_PATTERNS = re.compile(
    r"(reactivar\s+campa[nñ]a|reanudar\s+campa[nñ]a|"
    r"resume\s+campaign|re-?enable\s+campaign|unpause\s+campaign)",
    re.IGNORECASE,
)

_CAMPAIGN_ID_HINT = re.compile(
    r"(?:campaign\s*id|id\s*(?:de\s*)?campa[nñ]a|campa[nñ]a\s*id)\s*[:=#]?\s*(\d{1,12})",
    re.IGNORECASE,
)
_NUMERIC_ID_HINT = re.compile(r"\bid\s*[:=#]?\s*(\d{1,12})\b", re.IGNORECASE)


def google_ads_resume_mission_intent(prompt: str) -> bool:
    """True when the operator clearly asked to resume/re-enable a campaign."""
    return bool(prompt and _RESUME_INTENT_PATTERNS.search(prompt))


def _parse_target_campaign_id(prompt: str) -> int | None:
    for pat in (_CAMPAIGN_ID_HINT, _NUMERIC_ID_HINT):
        m = pat.search(prompt or "")
        if m:
            try:
                cid = int(m.group(1))
                return cid if cid > 0 else None
            except (TypeError, ValueError):
                return None
    return None


def _paused_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if str(r.get("status") or "").upper() != "PAUSED":
            continue
        if int(r.get("campaign_id") or 0) <= 0:
            continue
        out.append(r)
    return out


def build_google_ads_resume_campaign_actions(
    readonly_diagnostic: dict[str, Any],
    mission_prompt: str,
) -> list[dict[str, Any]]:
    """
    At most one google_ads_resume_campaign action, only when mission_prompt shows resume intent.
    Picks a PAUSED campaign from analytics_top_campaigns (optional id hint in prompt).
    """
    if not google_ads_resume_mission_intent(mission_prompt or ""):
        return []
    if not isinstance(readonly_diagnostic, dict):
        return []
    rows = readonly_diagnostic.get("analytics_top_campaigns")
    if not isinstance(rows, list) or not rows:
        return []
    paused = _paused_rows([x for x in rows if isinstance(x, dict)])
    if not paused:
        return []

    hint_id = _parse_target_campaign_id(mission_prompt or "")
    chosen: dict[str, Any] | None = None
    if hint_id is not None:
        for r in paused:
            if int(r.get("campaign_id") or 0) == hint_id:
                chosen = r
                break
    if chosen is None:
        chosen = paused[0]

    cid = int(chosen.get("campaign_id") or 0)
    name = str(chosen.get("name") or "").strip()
    if cid <= 0 or not name:
        return []

    reason = (
        "El operador pidió explícitamente reactivar/reanudar una campaña en pausa; "
        "se propone volver a ENABLED tras aprobación."
    )
    expected_benefit = (
        "Volver a mostrar anuncios y captar tráfico cuando el contexto creativo o de negocio ya está listo; "
        "el tope de presupuesto existente sigue aplicando."
    )

    policy = get_action_policy("google_ads_resume_campaign")
    execution_mode = str(policy.get("execution_mode") or DEFAULT_EXECUTION_MODE).strip().lower()
    if execution_mode == "approval_required":
        execution_mode = "requires_approval"
    confidence = 0.85
    action: dict[str, Any] = {
        "title": f"Reactivar campaña Google Ads «{name}»",
        "rationale": reason,
        "action_type": "google_ads_resume_campaign",
        "params": {
            "campaign_id": str(cid),
            "campaign_name": name,
            "current_status": "PAUSED",
            "cost": str(chosen.get("cost") or ""),
            "conversions": float(chosen.get("conversions") or 0.0),
            "ctr": str(chosen.get("ctr") or ""),
            "impressions": int(chosen.get("impressions") or 0),
            "clicks": int(chosen.get("clicks") or 0),
            "reason": reason,
            "expected_benefit": expected_benefit,
        },
        "impact": "high",
        "confidence": confidence,
        "execution_mode": execution_mode,
        "requires_approval": execution_mode == "requires_approval",
        "priority_score": compute_priority_score(
            action_type="google_ads_resume_campaign",
            impact="high",
            confidence=confidence,
        ),
    }
    return [action]


def format_google_ads_resume_approval_summary(action: dict[str, Any]) -> str:
    """Operator-facing approval block (Spanish)."""
    p = action.get("params") if isinstance(action.get("params"), dict) else {}
    name = str(p.get("campaign_name") or "—").strip()
    cid = str(p.get("campaign_id") or "—").strip()
    st = str(p.get("current_status") or "PAUSED").strip()
    cost = str(p.get("cost") if p.get("cost") is not None else "—")
    conv = p.get("conversions")
    conv_s = f"{float(conv):g}" if isinstance(conv, (int, float)) else str(conv or "—")
    ctr = str(p.get("ctr") or "—")
    impr = p.get("impressions")
    impr_s = str(int(impr)) if isinstance(impr, (int, float)) else str(impr or "—")
    clk = p.get("clicks")
    clk_s = str(int(clk)) if isinstance(clk, (int, float)) else str(clk or "—")
    rsn = str(p.get("reason") or "").strip()
    benefit = str(p.get("expected_benefit") or "").strip()
    lines = [
        "Reactivar campaña (Google Ads)",
        f"• Campaña: «{name}»  ·  id {cid}",
        f"• Estado: {st}",
        f"• Métricas (~30 días): coste {cost}  ·  conv. {conv_s}  ·  CTR {ctr}  ·  impr. {impr_s}  ·  clics {clk_s}",
        "• Al aprobar: ENABLED (puede generar coste al instante).",
        f"• Motivo: {rsn}",
        f"• Beneficio esperado: {benefit}",
    ]
    return "\n".join(lines)
