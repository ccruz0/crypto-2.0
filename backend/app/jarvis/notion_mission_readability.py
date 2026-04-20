"""Human-readable Notion mission layers (executive summary + timeline).

Technical traceability ([AGENT_OUTPUT:*], JSON, etc.) stays in NotionMissionService;
this module only formats higher-signal paragraphs for operators.
"""

from __future__ import annotations

import re
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


def extract_operator_request_line(mission_prompt: str) -> str:
    """Text after ``Operator software task:`` for Perico-wrapped prompts; else trimmed prompt."""
    mp = (mission_prompt or "").strip()
    if "Operator software task:" in mp:
        return mp.split("Operator software task:", 1)[-1].strip()
    return mp


_TASK_TYPE_LABEL_ES: dict[str, str] = {
    "bugfix": "corrección de bug",
    "integration_fix": "integración",
    "diagnostics": "diagnóstico",
    "validation": "validación",
    "refactor": "refactor",
    "general_software": "software general",
}


def notion_executive_display_fields(
    mission_prompt: str,
    *,
    specialist_agent: str | None = None,
) -> dict[str, str]:
    """
    Fields for Notion [EXEC_SUMMARY]: never expose internal Perico system prompt / markers.

    Returns keys: objective, agent, project, task_type (empty strings when not applicable).
    """
    from app.jarvis.perico_mission import (
        PERICO_DEFAULT_TARGET_PROJECT,
        infer_perico_target_project,
        is_perico_marked_prompt,
        is_perico_software_mission_prompt,
        parse_perico_task_type_from_prompt,
    )

    mp = mission_prompt or ""
    spec = (specialist_agent or "").strip().lower()
    is_perico = (
        spec == "perico"
        or is_perico_marked_prompt(mp)
        or is_perico_software_mission_prompt(mp)
    )
    if is_perico:
        op_line = extract_operator_request_line(mp)
        first = op_line.splitlines()[0].strip() if op_line else ""
        objective = (first or op_line or "").strip()[:900] or "(sin texto del operador)"
        tt_raw = parse_perico_task_type_from_prompt(mp)
        tt_label = _TASK_TYPE_LABEL_ES.get(tt_raw.strip().lower(), tt_raw or "")
        hint_m = re.search(r"\[PERICO_TARGET_PROJECT_HINT:\s*([^\]]+)\]", mp)
        project = (hint_m.group(1).strip() if hint_m else "") or (
            infer_perico_target_project(op_line) or PERICO_DEFAULT_TARGET_PROJECT
        )
        return {
            "objective": objective,
            "agent": "Perico",
            "project": project,
            "task_type": tt_label,
        }
    obj = mp.strip()[:900]
    return {
        "objective": obj,
        "agent": "",
        "project": "",
        "task_type": "",
    }


def format_executive_summary_block(
    *,
    objective: str = "",
    status: str = "",
    what_jarvis_did: str = "",
    key_result: str = "",
    blocked: str = "",
    next_step: str = "",
    agent: str = "",
    project: str = "",
    task_type: str = "",
) -> str:
    """Single comment body for [EXEC_SUMMARY] (no trailing newline spam)."""
    lines: list[str] = ["[EXEC_SUMMARY]"]
    o = (objective or "").strip()
    if o:
        lines.append(f"Objetivo: {o[:900]}")
    ag = (agent or "").strip()
    if ag:
        lines.append(f"Agente: {ag[:120]}")
    pr = (project or "").strip()
    if pr:
        lines.append(f"Proyecto: {pr[:120]}")
    tt = (task_type or "").strip()
    if tt:
        lines.append(f"Tipo de tarea: {tt[:120]}")
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


def summarize_perico_pending_approval_for_notion(
    execution: dict[str, Any] | None,
    pending_actions: list[dict[str, Any]],
) -> tuple[str, str]:
    """
    Clearer copy for Perico missions when Estado is waiting_for_approval.

    Returns (what_jarvis_did, next_step).
    """
    exec_line = summarize_execution_for_readability(execution)
    titles = [
        str(a.get("title") or "").strip()
        for a in pending_actions
        if isinstance(a, dict)
    ]
    titles = [t for t in titles if t][:5]
    pend = " · ".join(titles) if titles else "paso que requiere tu confirmación"
    what = (
        "Perico preparó el trabajo automático permitido; falta tu aprobación explícita "
        f"antes de ejecutar: {pend[:420]}."
    )
    if len(what) < 800 and exec_line:
        what = f"{what} Resumen de acciones: {exec_line[:380]}"
    next_step = (
        "En Telegram, usa los botones del mensaje de aprobación (Aprobar / Rechazar) "
        "o los comandos de misión indicados. Sin aprobación no se continúa ese paso."
    )
    return what[:950], next_step[:500]
