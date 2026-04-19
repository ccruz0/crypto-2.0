"""Human-readable Notion mission layers (executive summary + timeline).

Technical traceability ([AGENT_OUTPUT:*], JSON, etc.) stays in NotionMissionService;
this module only formats higher-signal paragraphs for operators.
"""

from __future__ import annotations

from typing import Any

from app.jarvis.autonomous_schemas import (
    MISSION_STATUS_DONE,
    MISSION_STATUS_EXECUTING,
    MISSION_STATUS_FAILED,
    MISSION_STATUS_PLANNING,
    MISSION_STATUS_RECEIVED,
    MISSION_STATUS_RESEARCHING,
    MISSION_STATUS_REVIEWING,
    MISSION_STATUS_WAITING_FOR_APPROVAL,
    MISSION_STATUS_WAITING_FOR_INPUT,
)

_STATUS_LABELS: dict[str, str] = {
    MISSION_STATUS_RECEIVED: "Recibida",
    MISSION_STATUS_PLANNING: "En planificación",
    MISSION_STATUS_RESEARCHING: "Investigando",
    MISSION_STATUS_EXECUTING: "En ejecución",
    MISSION_STATUS_WAITING_FOR_INPUT: "Falta tu respuesta",
    MISSION_STATUS_WAITING_FOR_APPROVAL: "Pendiente de tu aprobación",
    MISSION_STATUS_REVIEWING: "En revisión",
    MISSION_STATUS_DONE: "Completada",
    MISSION_STATUS_FAILED: "Detenida o bloqueada",
}


def human_mission_status(status: str | None) -> str:
    s = (status or "").strip().lower()
    return _STATUS_LABELS.get(s, s or "Desconocido")


def format_executive_summary_block(
    *,
    objective: str = "",
    status: str = "",
    what_jarvis_did: str = "",
    key_result: str = "",
    blocked: str = "",
    next_step: str = "",
) -> str:
    """Single comment body for [EXEC_SUMMARY] (no trailing newline spam)."""
    lines: list[str] = ["[EXEC_SUMMARY]"]
    o = (objective or "").strip()
    if o:
        lines.append(f"Objetivo: {o[:900]}")
    st = (status or "").strip()
    if st:
        lines.append(f"Estado: {st[:200]}")
    w = (what_jarvis_did or "").strip()
    if w:
        lines.append(f"Qué hizo Jarvis: {w[:900]}")
    kr = (key_result or "").strip()
    if kr:
        lines.append(f"Resultado clave: {kr[:900]}")
    bl = (blocked or "").strip()
    if bl:
        lines.append(f"Bloqueo o freno: {bl[:500]}")
    ns = (next_step or "").strip()
    if ns:
        lines.append(f"Siguiente paso recomendado: {ns[:500]}")
    return "\n".join(lines)[:1900]


def format_timeline_line(sentence: str) -> str:
    s = (sentence or "").strip()
    if not s:
        return ""
    return f"[TIMELINE] {s[:1700]}"


def summarize_plan_for_readability(plan: dict[str, Any] | None) -> str:
    if not isinstance(plan, dict):
        return ""
    obj = str(plan.get("objective") or "").strip()
    steps = plan.get("steps")
    if obj:
        return obj[:400]
    if isinstance(steps, list) and steps:
        first = str(steps[0] or "").strip()
        if first:
            return f"Pasos previstos (ej.): {first[:300]}"
    return "El planificador definió un esquema de trabajo."


def summarize_execution_for_readability(execution: dict[str, Any] | None) -> str:
    if not isinstance(execution, dict):
        return ""
    executed = [x for x in (execution.get("executed") or []) if isinstance(x, dict)]
    titles = [str(x.get("title") or "").strip() for x in executed[:8] if str(x.get("title") or "").strip()]
    if not titles:
        return "Se ejecutó la fase de ejecución; no hay acciones con nombre claro en el registro."
    joined = "; ".join(titles[:5])
    if len(titles) > 5:
        joined += " …"
    return f"Acciones ejecutadas: {joined}"[:900]
