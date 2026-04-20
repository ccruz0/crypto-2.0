"""Autonomous mission orchestrator (Telegram in, Notion as source of truth)."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from app.jarvis.analytics_mission_deliverables import infer_analytics_deliverables
from app.jarvis.analytics_prompt_gates import readonly_analytics_prompt_sufficient
from app.jarvis.autonomous_agents import (
    ExecutionAgent,
    OutcomeEvaluatorAgent,
    PlannerAgent,
    ResearchAgent,
    ReviewAgent,
    StrategyAgent,
)
from app.jarvis.google_ads_budget_proposals import (
    build_google_ads_reduce_campaign_budget_actions,
    format_google_ads_budget_reduce_approval_summary,
)
from app.jarvis.google_ads_mutations import (
    run_google_ads_pause_campaign,
    run_google_ads_reduce_campaign_budget,
    run_google_ads_resume_campaign,
)
from app.jarvis.google_ads_resume_proposals import (
    build_google_ads_resume_campaign_actions,
    format_google_ads_resume_approval_summary,
    google_ads_resume_mission_intent,
)
from app.jarvis.google_ads_pause_proposals import (
    extract_google_ads_readonly_diagnostic_result,
    format_google_ads_pause_approval_summary,
)
from app.jarvis.ops_agent import OPS_ACTION_TYPES, OpsAgent
from app.jarvis.autonomous_schemas import (
    MISSION_STATUS_DONE,
    MISSION_STATUS_EXECUTING,
    MISSION_STATUS_FAILED,
    MISSION_STATUS_PLANNING,
    MISSION_STATUS_RESEARCHING,
    MISSION_STATUS_REVIEWING,
    MISSION_STATUS_WAITING_FOR_APPROVAL,
    MISSION_STATUS_WAITING_FOR_INPUT,
)
from app.jarvis.mission_goal_quality import (
    build_corrective_readonly_analytics_action,
    evaluate_goal_satisfaction,
    format_goal_shortfall_user_message,
    format_natural_clarification_request,
    should_attempt_goal_retry,
)
from app.jarvis.notion_mission_readability import (
    summarize_execution_for_readability,
    summarize_plan_for_readability,
    human_mission_status,
)
from app.jarvis.notion_mission_service import NotionMissionService
from app.jarvis.perico_mission import (
    build_perico_deliverables_snapshot,
    build_perico_mission_prompt,
    is_perico_marked_prompt,
    perico_should_block_for_operator_input,
    perico_try_auto_pytest_retry,
)
from app.jarvis.telegram_service import TelegramMissionService

logger = logging.getLogger(__name__)


def _format_combined_approval_summary(actions: list[dict[str, Any]]) -> str:
    """Human-readable approval text; Google Ads pause uses metrics + trigger rule."""
    parts: list[str] = []
    for x in actions[:4]:
        if not isinstance(x, dict):
            continue
        at = str(x.get("action_type") or "").strip().lower()
        if at == "google_ads_pause_campaign":
            parts.append(format_google_ads_pause_approval_summary(x))
        elif at == "google_ads_reduce_campaign_budget":
            parts.append(format_google_ads_budget_reduce_approval_summary(x))
        elif at == "google_ads_resume_campaign":
            parts.append(format_google_ads_resume_approval_summary(x))
        else:
            t = str(x.get("title") or "").strip()
            if t:
                parts.append(t)
    return "\n\n".join(parts) if parts else "critical action requested"


def _dump(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=True)
    except Exception:
        return str(value)


def is_autonomous_jarvis_enabled() -> bool:
    return (os.getenv("JARVIS_AUTONOMOUS_ENABLED") or "").strip().lower() in ("1", "true", "yes", "on")


class JarvisAutonomousOrchestrator:
    def __init__(
        self,
        *,
        notion: NotionMissionService | None = None,
        planner: PlannerAgent | None = None,
        researcher: ResearchAgent | None = None,
        strategist: StrategyAgent | None = None,
        ops: OpsAgent | None = None,
        executor: ExecutionAgent | None = None,
        outcome_evaluator: OutcomeEvaluatorAgent | None = None,
        reviewer: ReviewAgent | None = None,
        telegram: TelegramMissionService | None = None,
    ) -> None:
        self.notion = notion or NotionMissionService()
        self.planner = planner or PlannerAgent()
        self.researcher = researcher or ResearchAgent()
        self.strategist = strategist or StrategyAgent()
        self.ops = ops or OpsAgent()
        self.executor = executor or ExecutionAgent()
        self.outcome_evaluator = outcome_evaluator or OutcomeEvaluatorAgent()
        self.reviewer = reviewer or ReviewAgent()
        self.telegram = telegram or TelegramMissionService()

    def run_new_mission(
        self,
        *,
        prompt: str,
        actor: str,
        chat_id: str,
        specialist_agent: str | None = None,
    ) -> dict[str, Any]:
        if not self.notion.configured():
            return {
                "ok": False,
                "dialog_message": (
                    "Jarvis autónomo necesita Notion configurado "
                    "(NOTION_API_KEY y base de tareas / NOTION_TASK_DB)."
                ),
            }
        user_prompt = (prompt or "").strip()
        spec = (specialist_agent or "").strip().lower() or None
        effective_prompt = (
            build_perico_mission_prompt(user_text=user_prompt) if spec == "perico" else user_prompt
        )
        mission = self.notion.create_mission(
            prompt=effective_prompt,
            actor=actor,
            specialist_agent=spec,
            operator_short_prompt=user_prompt if spec == "perico" else None,
        )
        mission_id = str(mission["mission_id"])
        return self._run_pipeline(
            mission_id=mission_id,
            prompt=effective_prompt,
            actor=actor,
            chat_id=chat_id,
            external_input="",
            specialist_agent=spec,
        )

    def continue_after_approval(
        self,
        *,
        mission_id: str,
        approved: bool,
        actor: str,
        chat_id: str,
        reason: str = "",
        pending_actions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        mission = self.notion.get_mission(mission_id)
        if mission is None:
            return {"ok": False, "dialog_message": f"No encontré la misión: {mission_id}"}
        self.notion.append_event(
            mission_id,
            event="approval_response",
            detail=f"approved={int(approved)} actor={actor} reason={reason[:300]}",
        )
        if not approved:
            self.notion.append_readability_timeline(
                mission_id, f"Aprobación rechazada por {actor}; misión detenida."
            )
            self.notion.transition_state(
                mission_id,
                to_state=MISSION_STATUS_FAILED,
                note=f"approval rejected by {actor}",
            )
            return {
                "ok": True,
                "mission_id": mission_id,
                "status": MISSION_STATUS_FAILED,
                "dialog_message": (
                    f"Misión rechazada y marcada como fallida. "
                    f"(Ref. interna: {mission_id})"
                ),
            }
        actions_src = pending_actions
        if actions_src is None:
            actions_src = self.notion.get_latest_pending_approval_actions(mission_id)
        pause_actions = [
            a
            for a in (actions_src or [])
            if isinstance(a, dict)
            and str(a.get("action_type") or "").strip().lower() == "google_ads_pause_campaign"
        ]
        if pause_actions:
            self.notion.append_readability_timeline(
                mission_id, "Aprobación concedida; ejecutando pausa de campaña (Google Ads)."
            )
            self.notion.transition_state(
                mission_id,
                to_state=MISSION_STATUS_EXECUTING,
                note=f"approval granted by {actor}; google_ads_pause_campaign",
            )
            row = pause_actions[0]
            params = dict(row.get("params") or {})
            result = run_google_ads_pause_campaign(params)
            self.notion.append_agent_output(mission_id, agent_name="execution_approved_mutation", content=_dump(result))
            self.notion.append_readability_timeline(
                mission_id,
                (
                    f"Pausa de campaña ejecutada (ok={bool(result.get('ok'))}). "
                    f"{str(result.get('error_message') or '')[:200]}"
                ).strip(),
            )
            self.notion.append_event(
                mission_id,
                event="google_ads_pause_campaign",
                detail=f"ok={bool(result.get('ok'))} campaign_id={params.get('campaign_id')}",
            )
            cname = str(params.get("campaign_name") or "la campaña").strip()
            if result.get("ok"):
                self.telegram.send_message(
                    chat_id,
                    f"Campaña {cname} pausada correctamente. (Ref. interna: {mission_id})",
                )
                execution_payload = {
                    "executed": [
                        {
                            "title": str(row.get("title") or "Pausar campaña"),
                            "action_type": "google_ads_pause_campaign",
                            "status": "executed",
                            "result": result,
                        }
                    ],
                    "needs_approval": False,
                }
                self.notion.transition_state(mission_id, to_state=MISSION_STATUS_REVIEWING, note="post-approval review")
                review = self.reviewer.run(plan={}, execution=execution_payload)
                self.notion.append_agent_output(mission_id, agent_name="review", content=_dump(review))
                self.notion.transition_state(mission_id, to_state=MISSION_STATUS_DONE, note="pause completed")
                return {
                    "ok": True,
                    "mission_id": mission_id,
                    "status": MISSION_STATUS_DONE,
                    "dialog_message": (
                        f"Campaña {cname} pausada correctamente. (Ref. interna: {mission_id})"
                    ),
                    "result": {"execution": execution_payload, "review": review},
                }
            err = str(result.get("error_message") or "error desconocido")
            self.telegram.send_message(
                chat_id,
                f"No se pudo pausar la campaña: {err[:500]} (Ref. interna: {mission_id})",
            )
            self.notion.transition_state(mission_id, to_state=MISSION_STATUS_FAILED, note="google_ads_pause_failed")
            return {
                "ok": False,
                "mission_id": mission_id,
                "status": MISSION_STATUS_FAILED,
                "dialog_message": f"No se pudo pausar la campaña: {err[:700]} (Ref. interna: {mission_id})",
                "result": {"execution": {"executed": [{"action_type": "google_ads_pause_campaign", "result": result}]}},
            }

        budget_actions = [
            a
            for a in (actions_src or [])
            if isinstance(a, dict)
            and str(a.get("action_type") or "").strip().lower() == "google_ads_reduce_campaign_budget"
        ]
        if budget_actions:
            self.notion.append_readability_timeline(
                mission_id, "Aprobación concedida; ajustando presupuesto diario (Google Ads)."
            )
            self.notion.transition_state(
                mission_id,
                to_state=MISSION_STATUS_EXECUTING,
                note=f"approval granted by {actor}; google_ads_reduce_campaign_budget",
            )
            brow = budget_actions[0]
            bparams = dict(brow.get("params") or {})
            bresult = run_google_ads_reduce_campaign_budget(bparams)
            self.notion.append_agent_output(
                mission_id, agent_name="execution_approved_mutation", content=_dump(bresult)
            )
            self.notion.append_readability_timeline(
                mission_id,
                (
                    f"Ajuste de presupuesto ejecutado (ok={bool(bresult.get('ok'))}). "
                    f"{str(bresult.get('error_message') or '')[:200]}"
                ).strip(),
            )
            self.notion.append_event(
                mission_id,
                event="google_ads_reduce_campaign_budget",
                detail=f"ok={bool(bresult.get('ok'))} campaign_id={bparams.get('campaign_id')}",
            )
            bname = str(bparams.get("campaign_name") or "la campaña").strip()
            pct_disp = bparams.get("reduction_percent", 20)
            cur_amt = str(bparams.get("current_budget_amount") or "")
            new_amt = str(bparams.get("proposed_budget_amount") or "")
            if bresult.get("ok"):
                self.telegram.send_message(
                    chat_id,
                    (
                        f"Presupuesto de «{bname}» reducido un {pct_disp}% respecto al tope diario anterior "
                        f"(antes ~{cur_amt}, objetivo propuesto ~{new_amt}; mismo id de cuenta). "
                        f"(Ref. interna: {mission_id})"
                    ),
                )
                execution_payload = {
                    "executed": [
                        {
                            "title": str(brow.get("title") or "Reducir presupuesto"),
                            "action_type": "google_ads_reduce_campaign_budget",
                            "status": "executed",
                            "result": bresult,
                        }
                    ],
                    "needs_approval": False,
                }
                self.notion.transition_state(mission_id, to_state=MISSION_STATUS_REVIEWING, note="post-approval review")
                review = self.reviewer.run(plan={}, execution=execution_payload)
                self.notion.append_agent_output(mission_id, agent_name="review", content=_dump(review))
                self.notion.transition_state(mission_id, to_state=MISSION_STATUS_DONE, note="budget_reduce completed")
                return {
                    "ok": True,
                    "mission_id": mission_id,
                    "status": MISSION_STATUS_DONE,
                    "dialog_message": (
                        f"Presupuesto de «{bname}» reducido un {pct_disp}% correctamente. "
                        f"(Ref. interna: {mission_id})"
                    ),
                    "result": {"execution": execution_payload, "review": review},
                }
            berr = str(bresult.get("error_message") or "error desconocido")
            self.telegram.send_message(
                chat_id,
                f"No se pudo ajustar el presupuesto: {berr[:500]} (Ref. interna: {mission_id})",
            )
            self.notion.transition_state(
                mission_id, to_state=MISSION_STATUS_FAILED, note="google_ads_budget_reduce_failed"
            )
            return {
                "ok": False,
                "mission_id": mission_id,
                "status": MISSION_STATUS_FAILED,
                "dialog_message": f"No se pudo ajustar el presupuesto: {berr[:700]} (Ref. interna: {mission_id})",
                "result": {
                    "execution": {
                        "executed": [{"action_type": "google_ads_reduce_campaign_budget", "result": bresult}]
                    }
                },
            }

        resume_actions = [
            a
            for a in (actions_src or [])
            if isinstance(a, dict)
            and str(a.get("action_type") or "").strip().lower() == "google_ads_resume_campaign"
        ]
        if resume_actions:
            self.notion.append_readability_timeline(
                mission_id, "Aprobación concedida; reactivando campaña (Google Ads)."
            )
            self.notion.transition_state(
                mission_id,
                to_state=MISSION_STATUS_EXECUTING,
                note=f"approval granted by {actor}; google_ads_resume_campaign",
            )
            rrow = resume_actions[0]
            rparams = dict(rrow.get("params") or {})
            rresult = run_google_ads_resume_campaign(rparams)
            self.notion.append_agent_output(
                mission_id, agent_name="execution_approved_mutation", content=_dump(rresult)
            )
            self.notion.append_readability_timeline(
                mission_id,
                (
                    f"Reactivación de campaña ejecutada (ok={bool(rresult.get('ok'))}). "
                    f"{str(rresult.get('error_message') or '')[:200]}"
                ).strip(),
            )
            self.notion.append_event(
                mission_id,
                event="google_ads_resume_campaign",
                detail=f"ok={bool(rresult.get('ok'))} campaign_id={rparams.get('campaign_id')} no_op={bool(rresult.get('no_op'))}",
            )
            rname = str(rparams.get("campaign_name") or "la campaña").strip()
            if rresult.get("ok"):
                if rresult.get("no_op"):
                    self.telegram.send_message(
                        chat_id,
                        (
                            f"La campaña «{rname}» ya estaba ENABLED; no hubo cambios en Google Ads. "
                            f"(Ref. interna: {mission_id})"
                        ),
                    )
                else:
                    self.telegram.send_message(
                        chat_id,
                        (
                            f"Campaña «{rname}» reactivada (ENABLED). Puede generar coste de inmediato. "
                            f"(Ref. interna: {mission_id})"
                        ),
                    )
                execution_payload = {
                    "executed": [
                        {
                            "title": str(rrow.get("title") or "Reactivar campaña"),
                            "action_type": "google_ads_resume_campaign",
                            "status": "executed",
                            "result": rresult,
                        }
                    ],
                    "needs_approval": False,
                }
                self.notion.transition_state(mission_id, to_state=MISSION_STATUS_REVIEWING, note="post-approval review")
                review = self.reviewer.run(plan={}, execution=execution_payload)
                self.notion.append_agent_output(mission_id, agent_name="review", content=_dump(review))
                self.notion.transition_state(mission_id, to_state=MISSION_STATUS_DONE, note="resume_completed")
                dm = (
                    f"La campaña «{rname}» ya estaba ENABLED; sin cambios. (Ref. interna: {mission_id})"
                    if rresult.get("no_op")
                    else f"Campaña «{rname}» reactivada correctamente. (Ref. interna: {mission_id})"
                )
                return {
                    "ok": True,
                    "mission_id": mission_id,
                    "status": MISSION_STATUS_DONE,
                    "dialog_message": dm,
                    "result": {"execution": execution_payload, "review": review},
                }
            rerr = str(rresult.get("error_message") or "error desconocido")
            self.telegram.send_message(
                chat_id,
                f"No se pudo reactivar la campaña: {rerr[:500]} (Ref. interna: {mission_id})",
            )
            self.notion.transition_state(
                mission_id, to_state=MISSION_STATUS_FAILED, note="google_ads_resume_failed"
            )
            return {
                "ok": False,
                "mission_id": mission_id,
                "status": MISSION_STATUS_FAILED,
                "dialog_message": f"No se pudo reactivar la campaña: {rerr[:700]} (Ref. interna: {mission_id})",
                "result": {
                    "execution": {
                        "executed": [{"action_type": "google_ads_resume_campaign", "result": rresult}]
                    }
                },
            }

        self.notion.append_readability_timeline(mission_id, "Aprobación concedida; cerrando el flujo autorizado.")
        self.notion.transition_state(
            mission_id,
            to_state=MISSION_STATUS_EXECUTING,
            note=f"approval granted by {actor}",
        )
        self.notion.transition_state(mission_id, to_state=MISSION_STATUS_REVIEWING, note="post-approval review")
        review = self.reviewer.run(plan={}, execution={"executed": ["approved-critical-step"], "needs_approval": False})
        self.notion.append_agent_output(mission_id, agent_name="review", content=_dump(review))
        self.notion.transition_state(mission_id, to_state=MISSION_STATUS_DONE, note="approved flow completed")
        return {
            "ok": True,
            "mission_id": mission_id,
            "status": MISSION_STATUS_DONE,
            "dialog_message": (
                f"Misión aprobada y completada. (Ref. interna: {mission_id})"
            ),
        }

    def continue_after_input(
        self,
        *,
        mission_id: str,
        input_text: str,
        actor: str,
        chat_id: str,
    ) -> dict[str, Any]:
        mission = self.notion.get_mission(mission_id)
        if mission is None:
            return {"ok": False, "dialog_message": f"No encontré la misión: {mission_id}"}
        self.notion.append_event(
            mission_id,
            event="input_received",
            detail=f"actor={actor} input={input_text[:600]}",
        )
        self.notion.append_readability_timeline(
            mission_id, "Nueva respuesta del operador; se reanuda la misión."
        )
        self.notion.transition_state(mission_id, to_state=MISSION_STATUS_PLANNING, note="resuming with new input")
        prompt = f"{mission.get('details', '')}\n\nUser input:\n{input_text}"
        return self._run_pipeline(
            mission_id=mission_id,
            prompt=prompt,
            actor=actor,
            chat_id=chat_id,
            external_input=input_text,
            specialist_agent=("perico" if is_perico_marked_prompt(prompt) else None),
        )

    def _merge_google_ads_mutation_proposals(
        self,
        *,
        mission_id: str,
        prompt: str,
        execution: dict[str, Any],
    ) -> dict[str, Any]:
        """
        After read-only Google Ads diagnostics, optionally queue approval-gated mutations (never mutate here):

        1) pause_campaign — strict readonly Google Ads analytics mission + heuristics
        2) reduce_campaign_budget — same mission gate + softer heuristics (only if no pause)
        3) resume_campaign — explicit operator intent only + PAUSED row in diagnostic (only if no pause/budget)
        """
        if is_perico_marked_prompt(prompt):
            return execution
        diag = extract_google_ads_readonly_diagnostic_result(execution)
        if not diag:
            return execution

        spec = (
            infer_analytics_deliverables(prompt)
            if readonly_analytics_prompt_sufficient(prompt)
            else None
        )
        ads_mission = bool(spec and getattr(spec, "domain", "") == "google_ads")

        existing_types = {
            str(x.get("action_type") or "").strip().lower()
            for x in (execution.get("waiting_for_approval") or [])
            if isinstance(x, dict)
        }
        if {
            "google_ads_pause_campaign",
            "google_ads_reduce_campaign_budget",
            "google_ads_resume_campaign",
        }.intersection(existing_types):
            return execution

        pause_actions: list[dict[str, Any]] = []
        if ads_mission:
            pause_actions = StrategyAgent.propose_google_ads_pause_from_readonly_diagnostic(diag) or []
        if pause_actions:
            exec2 = self.executor.run(
                strategy={"actions": pause_actions, "source": "deterministic_pause_proposal"},
                mission_prompt=prompt,
            )
            wa = [x for x in (execution.get("waiting_for_approval") or []) if isinstance(x, dict)]
            wa.extend([x for x in (exec2.get("waiting_for_approval") or []) if isinstance(x, dict)])
            execution = dict(execution)
            execution["waiting_for_approval"] = wa
            execution["needs_approval"] = bool(wa) or bool(execution.get("needs_approval"))
            summaries = [str(x.get("title") or "") for x in wa[:6] if str(x.get("title") or "").strip()]
            execution["approval_summary"] = "; ".join(summaries) if summaries else str(
                execution.get("approval_summary") or ""
            )
            self.notion.append_readability_timeline(
                mission_id,
                "Propuesta determinista: pausar una campaña según métricas (requiere tu aprobación).",
            )
            return execution

        budget_actions: list[dict[str, Any]] = []
        if ads_mission:
            budget_actions = build_google_ads_reduce_campaign_budget_actions(diag) or []
        if budget_actions:
            exec2 = self.executor.run(
                strategy={"actions": budget_actions, "source": "deterministic_budget_reduce_proposal"},
                mission_prompt=prompt,
            )
            wa = [x for x in (execution.get("waiting_for_approval") or []) if isinstance(x, dict)]
            wa.extend([x for x in (exec2.get("waiting_for_approval") or []) if isinstance(x, dict)])
            execution = dict(execution)
            execution["waiting_for_approval"] = wa
            execution["needs_approval"] = bool(wa) or bool(execution.get("needs_approval"))
            summaries = [str(x.get("title") or "") for x in wa[:6] if str(x.get("title") or "").strip()]
            execution["approval_summary"] = "; ".join(summaries) if summaries else str(
                execution.get("approval_summary") or ""
            )
            self.notion.append_readability_timeline(
                mission_id,
                "Propuesta determinista: reducir presupuesto diario de una campaña (requiere tu aprobación).",
            )
            return execution

        if google_ads_resume_mission_intent(prompt):
            resume_actions = build_google_ads_resume_campaign_actions(diag, prompt)
            if resume_actions:
                exec2 = self.executor.run(
                    strategy={"actions": resume_actions, "source": "deterministic_resume_intent"},
                    mission_prompt=prompt,
                )
                wa = [x for x in (execution.get("waiting_for_approval") or []) if isinstance(x, dict)]
                wa.extend([x for x in (exec2.get("waiting_for_approval") or []) if isinstance(x, dict)])
                execution = dict(execution)
                execution["waiting_for_approval"] = wa
                execution["needs_approval"] = bool(wa) or bool(execution.get("needs_approval"))
                summaries = [str(x.get("title") or "") for x in wa[:6] if str(x.get("title") or "").strip()]
                execution["approval_summary"] = "; ".join(summaries) if summaries else str(
                    execution.get("approval_summary") or ""
                )
                self.notion.append_readability_timeline(
                    mission_id,
                    "Propuesta por intención explícita: reactivar campaña en pausa (requiere tu aprobación).",
                )
        return execution

    def _run_pipeline(
        self,
        *,
        mission_id: str,
        prompt: str,
        actor: str,
        chat_id: str,
        external_input: str,
        specialist_agent: str | None = None,
    ) -> dict[str, Any]:
        self.notion.transition_state(mission_id, to_state=MISSION_STATUS_PLANNING, note="planner started")
        self.notion.append_readability_timeline(mission_id, "Planificador iniciado.")
        active_perico = (specialist_agent or "").strip().lower() == "perico" or is_perico_marked_prompt(prompt)
        if active_perico:
            self.notion.append_readability_timeline(
                mission_id,
                "Perico (software): bucle inspectar → hipótesis → parche mínimo → validar; sin deploy automático a producción.",
            )
        plan = self.planner.run(prompt)
        self.notion.append_technical_detail_marker(mission_id, "Salida en bruto del planificador y agentes")
        self.notion.append_agent_output(mission_id, agent_name="planner", content=_dump(plan))

        if plan.get("requires_input") and not external_input:
            clarify = format_natural_clarification_request(mission_prompt=prompt, plan=plan)
            self.notion.transition_state(
                mission_id,
                to_state=MISSION_STATUS_WAITING_FOR_INPUT,
                note="planner requested extra input",
            )
            self.notion.append_readability_timeline(
                mission_id, "Esperando tu respuesta para poder seguir."
            )
            self.notion.append_readability_executive_summary(
                mission_id,
                objective=prompt[:1200],
                status=human_mission_status(MISSION_STATUS_WAITING_FOR_INPUT),
                what_jarvis_did="El planificador necesita un poco más de contexto para avanzar con seguridad.",
                key_result=str(plan.get("objective") or summarize_plan_for_readability(plan))[:500],
                next_step="Responder en Telegram (botones o mensaje normal).",
            )
            clarify_sent = bool(self.telegram.send_input_request(chat_id, mission_id, clarify))
            return {
                "ok": True,
                "mission_id": mission_id,
                "status": MISSION_STATUS_WAITING_FOR_INPUT,
                "dialog_message": (
                    ""
                    if clarify_sent
                    else (
                        f"{clarify}\n\n"
                        "Pulsa «Responder» o escribe aquí. "
                        f"(Ref. interna: {mission_id})"
                    )
                ),
                "telegram_compact_reply_suppressed": clarify_sent,
            }

        research: dict[str, Any] | None = None
        if plan.get("requires_research"):
            self.notion.transition_state(mission_id, to_state=MISSION_STATUS_RESEARCHING, note="research started")
            self.notion.append_readability_timeline(mission_id, "Fase de investigación iniciada.")
            research = self.researcher.run(prompt=prompt, plan=plan)
            self.notion.append_agent_output(mission_id, agent_name="research", content=_dump(research))

        outcome_memory = self.notion.get_recent_outcomes(mission_id, limit=30)
        strategy = self.strategist.run(
            prompt=prompt,
            plan=plan,
            research=research,
            outcome_memory=outcome_memory,
        )
        self.notion.append_agent_output(mission_id, agent_name="strategy", content=_dump(strategy))
        self.notion.append_readability_timeline(mission_id, "Estrategia lista; revisión ops y ejecución.")
        ops_output = self.ops.run(
            prompt=prompt,
            plan=plan,
            research=research,
            strategy=strategy,
        )
        self.notion.append_agent_output(mission_id, agent_name="ops", content=_dump(ops_output))
        self.telegram.send_ops_report(chat_id, ops_output)
        baseline_by_title: dict[str, dict[str, Any]] = {}
        for action in (strategy.get("actions") or []):
            if not isinstance(action, dict):
                continue
            self.notion.append_action_baseline(mission_id, action=action)
            title = str(action.get("title") or "").strip()
            baseline_by_title[title] = {"score": 100.0, "captured_at": "strategy_phase"}

        self.notion.transition_state(mission_id, to_state=MISSION_STATUS_EXECUTING, note="execution started")
        self.notion.append_readability_timeline(mission_id, "Ejecución iniciada.")
        strategy_actions = [a for a in (strategy.get("actions") or []) if isinstance(a, dict)]
        non_ops_actions = [
            a
            for a in strategy_actions
            if str(a.get("action_type") or "").strip().lower() not in OPS_ACTION_TYPES
        ]
        retry_phase = 0
        execution: dict[str, Any] = {}
        goal_eval: dict[str, Any] = {"satisfied": True, "missing_items": [], "reason": "init"}
        while True:
            execution = self.executor.run(
                strategy={"actions": non_ops_actions, "source": strategy.get("source")},
                mission_prompt=prompt,
            )
            exec_tag = "execution" if retry_phase == 0 else "execution_retry"
            self.notion.append_agent_output(mission_id, agent_name=exec_tag, content=_dump(execution))
            goal_eval = evaluate_goal_satisfaction(mission_prompt=prompt, execution=execution)
            self.notion.append_agent_output(mission_id, agent_name="goal_check", content=_dump(goal_eval))
            if goal_eval.get("satisfied"):
                break
            if should_attempt_goal_retry(
                mission_prompt=prompt,
                goal_eval=goal_eval,
                retry_used=retry_phase >= 1,
            ):
                domain = str(goal_eval.get("evaluator_domain") or "google_ads").strip().lower() or "google_ads"
                self.notion.append_readability_timeline(
                    mission_id,
                    f"Reintento con pasada correctiva en solo lectura ({domain}).",
                )
                self.notion.append_event(
                    mission_id,
                    event="goal_autoretry",
                    detail=f"retrying_with_corrective_{domain}_readonly",
                )
                retry_phase += 1
                non_ops_actions = [build_corrective_readonly_analytics_action(domain)]
                continue
            break

        if active_perico:
            extra_py = perico_try_auto_pytest_retry(execution)
            if extra_py:
                execution.setdefault("executed", []).extend(extra_py)
            snap = build_perico_deliverables_snapshot(
                mission_prompt=prompt,
                plan=plan,
                execution=execution,
                goal_satisfied=bool(goal_eval.get("satisfied")),
                retry_attempted=bool(extra_py),
            )
            self.notion.append_agent_output(mission_id, agent_name="perico_deliverables", content=_dump(snap))
            if goal_eval.get("satisfied"):
                block_msg = perico_should_block_for_operator_input(execution)
                if block_msg:
                    self.notion.transition_state(
                        mission_id,
                        to_state=MISSION_STATUS_WAITING_FOR_INPUT,
                        note="perico_validation_incomplete",
                    )
                    self.notion.append_readability_timeline(
                        mission_id,
                        "Perico: validación incompleta o tests en rojo; se pide intervención del operador.",
                    )
                    self.notion.append_readability_executive_summary(
                        mission_id,
                        objective=prompt[:1200],
                        status=human_mission_status(MISSION_STATUS_WAITING_FOR_INPUT),
                        what_jarvis_did="Perico aplicó o intentó cambios pero no se cumple el criterio de cierre software.",
                        blocked=block_msg[:500],
                        next_step="Indica cómo seguir o ajusta el alcance (botón «Responder» o mensaje normal).",
                    )
                    gate_sent = bool(self.telegram.send_input_request(chat_id, mission_id, block_msg))
                    return {
                        "ok": True,
                        "mission_id": mission_id,
                        "status": MISSION_STATUS_WAITING_FOR_INPUT,
                        "dialog_message": (
                            ""
                            if gate_sent
                            else (
                                f"{block_msg}\n\n"
                                f"Pulsa «Responder» o escribe aquí. (Ref. interna: {mission_id})"
                            )
                        ),
                        "telegram_compact_reply_suppressed": gate_sent,
                    }

        if goal_eval.get("satisfied"):
            wa_before = len(execution.get("waiting_for_approval") or [])
            execution = self._merge_google_ads_mutation_proposals(
                mission_id=mission_id,
                prompt=prompt,
                execution=execution,
            )
            wa_after = len(execution.get("waiting_for_approval") or [])
            if wa_after > wa_before:
                self.notion.append_agent_output(mission_id, agent_name="execution", content=_dump(execution))

        if not goal_eval.get("satisfied"):
            self.notion.transition_state(
                mission_id,
                to_state=MISSION_STATUS_WAITING_FOR_INPUT,
                note="goal_not_satisfied_after_retry",
            )
            shortfall = format_goal_shortfall_user_message(goal_eval)
            self.notion.append_readability_timeline(
                mission_id, "El objetivo aún no se cumple; puede faltar detalle."
            )
            self.notion.append_readability_executive_summary(
                mission_id,
                objective=prompt[:1200],
                status=human_mission_status(MISSION_STATUS_WAITING_FOR_INPUT),
                what_jarvis_did="Se ejecutó la misión, pero el objetivo declarado sigue sin cubrirse del todo.",
                blocked=shortfall[:500],
                next_step="Responder con el detalle que falta (botón «Responder» o mensaje normal).",
            )
            shortfall_sent = bool(self.telegram.send_input_request(chat_id, mission_id, shortfall))
            return {
                "ok": True,
                "mission_id": mission_id,
                "status": MISSION_STATUS_WAITING_FOR_INPUT,
                "dialog_message": (
                    ""
                    if shortfall_sent
                    else (
                        f"{shortfall}\n\n"
                        "Pulsa «Responder» o escribe aquí. "
                        f"(Ref. interna: {mission_id})"
                    )
                ),
                "telegram_compact_reply_suppressed": shortfall_sent,
            }

        # Post-execution outcome evaluation (can run on same cycle or next cycle in future revisions).
        updated_metrics = {"score": 100.0, "captured_at": "post_execution"}
        outcome_eval = self.outcome_evaluator.evaluate(
            executed_actions=[x for x in (execution.get("executed") or []) if isinstance(x, dict)],
            baseline_by_title=baseline_by_title,
            updated_metrics=updated_metrics,
        )
        self.notion.append_agent_output(mission_id, agent_name="outcome_evaluator", content=_dump(outcome_eval))
        self.notion.append_outcome_evaluation(
            mission_id,
            evaluations=list(outcome_eval.get("evaluations") or []),
            summary=dict(outcome_eval.get("summary") or {}),
        )

        if execution.get("waiting_for_input"):
            first_input_action = (execution.get("waiting_for_input") or [{}])[0]
            prompt_text = str(
                first_input_action.get("params", {}).get("question")
                or first_input_action.get("title")
                or "Añade el contexto que falta para esta misión."
            )
            self.notion.transition_state(
                mission_id,
                to_state=MISSION_STATUS_WAITING_FOR_INPUT,
                note=prompt_text[:300],
            )
            self.notion.append_readability_timeline(
                mission_id, f"Esperando respuesta: {prompt_text[:200]}"
            )
            self.notion.append_readability_executive_summary(
                mission_id,
                objective=prompt[:1200],
                status=human_mission_status(MISSION_STATUS_WAITING_FOR_INPUT),
                what_jarvis_did="La ejecución se detuvo: una acción necesita más contexto.",
                blocked=prompt_text[:500],
                next_step="Responder por Telegram («Responder» o mensaje en este chat).",
            )
            input_sent = bool(self.telegram.send_input_request(chat_id, mission_id, prompt_text))
            return {
                "ok": True,
                "mission_id": mission_id,
                "status": MISSION_STATUS_WAITING_FOR_INPUT,
                "dialog_message": (
                    ""
                    if input_sent
                    else (
                        f"{prompt_text}\n\n"
                        f"Pulsa «Responder» o contesta aquí. (Ref. interna: {mission_id})"
                    )
                ),
                "telegram_compact_reply_suppressed": input_sent,
            }

        combined_waiting_approval = [
            x
            for x in (ops_output.get("waiting_for_approval") or [])
            if isinstance(x, dict)
        ] + [x for x in (execution.get("waiting_for_approval") or []) if isinstance(x, dict)]
        if combined_waiting_approval:
            self.notion.append_pending_approval_payload(mission_id, actions=combined_waiting_approval)
            summary = _format_combined_approval_summary(combined_waiting_approval)
            note = (summary.split("\n", 1)[0] if summary else "")[:300]
            self.notion.transition_state(
                mission_id,
                to_state=MISSION_STATUS_WAITING_FOR_APPROVAL,
                note=note or summary[:300],
            )
            self.notion.append_readability_timeline(
                mission_id,
                "Pendiente de tu aprobación en Telegram (mensaje con botones en este chat).",
            )
            self.notion.append_readability_executive_summary(
                mission_id,
                objective=prompt[:1200],
                status=human_mission_status(MISSION_STATUS_WAITING_FOR_APPROVAL),
                what_jarvis_did=summarize_execution_for_readability(execution),
                blocked="Sin tu aprobación no puedo seguir con este paso.",
                next_step="Aprobar o rechazar con los botones del mensaje anterior o con /mission.",
            )
            approval_sent = bool(self.telegram.send_approval_request(chat_id, mission_id, summary))
            return {
                "ok": True,
                "mission_id": mission_id,
                "status": MISSION_STATUS_WAITING_FOR_APPROVAL,
                # Single Telegram UX: structured approval already sent above; avoid duplicate plain-text follow-up.
                "dialog_message": (
                    ""
                    if approval_sent
                    else (
                        "Hace falta tu visto bueno antes de seguir.\n\n"
                        f"{summary[:2200]}\n\n"
                        f"Ref.: {mission_id}\n"
                        "Si los botones no llegaron, usa /mission approve o /mission reject con este id."
                    )
                ),
                "telegram_compact_reply_suppressed": approval_sent,
            }

        self.notion.transition_state(mission_id, to_state=MISSION_STATUS_REVIEWING, note="review started")
        review = self.reviewer.run(plan=plan, execution=execution)
        self.notion.append_agent_output(mission_id, agent_name="review", content=_dump(review))
        if review.get("passed"):
            self.notion.transition_state(mission_id, to_state=MISSION_STATUS_DONE, note="review passed")
            dm = self._build_done_dialog_message(
                mission_id=mission_id,
                prompt=prompt,
                plan=plan,
                research=research,
                strategy=strategy,
                ops_output=ops_output,
                execution=execution,
                review=review,
            )
            self.notion.append_readability_timeline(mission_id, "Revisión superada; misión completada.")
            self.notion.append_readability_executive_summary(
                mission_id,
                objective=prompt[:1200],
                status=human_mission_status(MISSION_STATUS_DONE),
                what_jarvis_did=summarize_execution_for_readability(execution),
                key_result=str(review.get("summary") or "Completada correctamente.")[:500],
                next_step="El detalle completo está en Notion; abajo quedan los logs técnicos.",
            )
            return {
                "ok": True,
                "mission_id": mission_id,
                "status": MISSION_STATUS_DONE,
                "dialog_message": dm,
                "result": {
                    "plan": plan,
                    "research": research,
                    "strategy": strategy,
                    "ops": ops_output,
                    "execution": execution,
                    "outcome_evaluation": outcome_eval,
                    "review": review,
                },
            }
        self.notion.transition_state(mission_id, to_state=MISSION_STATUS_FAILED, note="review failed")
        return {
            "ok": False,
            "mission_id": mission_id,
            "status": MISSION_STATUS_FAILED,
            "dialog_message": (
                f"La misión no superó la revisión. (Ref. interna: {mission_id})"
            ),
            "result": {
                "plan": plan,
                "research": research,
                "strategy": strategy,
                "ops": ops_output,
                "execution": execution,
                "outcome_evaluation": outcome_eval,
                "review": review,
            },
        }

    def _build_done_dialog_message(
        self,
        *,
        mission_id: str,
        prompt: str,
        plan: dict[str, Any],
        research: dict[str, Any] | None,
        strategy: dict[str, Any],
        ops_output: dict[str, Any],
        execution: dict[str, Any],
        review: dict[str, Any],
    ) -> str:
        lines: list[str] = [f"Misión lista. Ref. interna: {mission_id}"]
        plan_source = str(plan.get("source") or "unknown")
        research_source = str((research or {}).get("source") or "n/a")
        strategy_source = str(strategy.get("source") or "unknown")

        # Google Ads analytics first so Telegram truncation (if any) does not drop metrics/issues.
        if self._is_google_ads_mission(prompt=prompt, strategy=strategy):
            diagnostics = [x for x in (ops_output.get("diagnostics") or []) if isinstance(x, dict)]
            diag_lines = [str(x.get("message") or "").strip() for x in diagnostics if str(x.get("message") or "").strip()]
            exec_google = self._extract_google_ads_execution_result(execution)
            if exec_google is not None:
                lines.extend(self._format_google_ads_execution_lines(exec_google))
            elif diag_lines:
                lines.append("Diagnóstico Google Ads: " + " | ".join(diag_lines[:3]))
            elif not self._execution_has_api_result(execution):
                lines.append(
                    "No se guardó resultado de prueba de Google Ads: la ejecución cerró acciones "
                    "sin payload de API ni error explícito."
                )

        if self._is_ga4_mission(prompt=prompt, strategy=strategy):
            exec_ga4 = self._extract_ga4_execution_result(execution)
            if exec_ga4 is not None:
                lines.extend(self._format_ga4_execution_lines(exec_ga4))

        lines.append(
            f"Fuentes: planificador={plan_source}, investigación={research_source}, estrategia={strategy_source}."
        )

        if any(src == "fallback" for src in (plan_source, research_source, strategy_source)):
            lines.append(
                "Aviso: se usó planificación de respaldo; los diagnósticos del modelo pueden ir incompletos."
            )

        executed = [x for x in (execution.get("executed") or []) if isinstance(x, dict)]
        exec_titles = [str(x.get("title") or "").strip() for x in executed if str(x.get("title") or "").strip()]
        if exec_titles:
            lines.append(
                "Acciones ejecutadas: " + "; ".join(exec_titles[:3]) + ("…" if len(exec_titles) > 3 else "")
            )

        review_summary = str(review.get("summary") or "").strip()
        if review_summary:
            lines.append(f"Revisión: {review_summary}")
        # Align with Telegram send_command_response / _telegram_clip headroom for long read-only reports.
        return "\n".join(lines)[:3900]

    def _is_google_ads_mission(self, *, prompt: str, strategy: dict[str, Any]) -> bool:
        parts = [str(prompt or "")]
        for action in (strategy.get("actions") or []):
            if not isinstance(action, dict):
                continue
            parts.append(str(action.get("title") or ""))
            parts.append(str(action.get("rationale") or ""))
            parts.append(str(action.get("action_type") or ""))
        haystack = "\n".join(parts).lower()
        return "google ads" in haystack or "google_ads" in haystack

    def _is_ga4_mission(self, *, prompt: str, strategy: dict[str, Any]) -> bool:
        parts = [str(prompt or "")]
        for action in (strategy.get("actions") or []):
            if not isinstance(action, dict):
                continue
            parts.append(str(action.get("title") or ""))
            parts.append(str(action.get("rationale") or ""))
            parts.append(str(action.get("action_type") or ""))
        haystack = "\n".join(parts).lower()
        return "ga4" in haystack or "google analytics" in haystack

    def _execution_has_api_result(self, execution: dict[str, Any]) -> bool:
        for row in (execution.get("executed") or []):
            if not isinstance(row, dict):
                continue
            keys = {str(k).lower() for k in row.keys()}
            if keys.intersection(
                {
                    "result",
                    "error",
                    "api_error",
                    "response",
                    "campaigns",
                    "metrics",
                    "analytics_top_campaigns",
                    "analytics_top_pages",
                    "analytics_top_events",
                }
            ):
                return True
            params = row.get("params")
            if isinstance(params, dict):
                pkeys = {str(k).lower() for k in params.keys()}
                if pkeys.intersection({"result", "error", "api_error", "response", "campaigns", "metrics"}):
                    return True
        return False

    def _extract_google_ads_execution_result(self, execution: dict[str, Any]) -> dict[str, Any] | None:
        candidates: list[dict[str, Any]] = []
        for row in (execution.get("executed") or []):
            if not isinstance(row, dict):
                continue
            action_type = str(row.get("action_type") or "").strip().lower()
            title = str(row.get("title") or "").strip().lower()
            if action_type not in {
                "diagnose_google_ads_setup",
                "test_google_ads_connection",
                "google_ads_diagnostic",
            } and "google ads" not in title:
                continue
            result = row.get("result")
            if isinstance(result, dict):
                candidates.append(result)
        if not candidates:
            return None
        for res in candidates:
            rows = res.get("analytics_top_campaigns")
            if isinstance(rows, list) and rows:
                return res
        return candidates[0]

    def _format_google_ads_execution_lines(self, result: dict[str, Any]) -> list[str]:
        lines: list[str] = []
        auth_ok = bool(result.get("auth_ok"))
        fetch_ok = bool(result.get("campaign_fetch_ok"))
        if auth_ok:
            lines.append("Autenticación con Google Ads: correcta.")
        else:
            lines.append("Autenticación con Google Ads: falló.")
        if fetch_ok:
            count = result.get("campaign_count")
            if isinstance(count, int):
                lines.append(f"Campañas obtenidas: {count}.")
            else:
                lines.append("Listado de campañas obtenido correctamente.")
            analytics_rows = result.get("analytics_top_campaigns")
            if isinstance(analytics_rows, list) and analytics_rows:
                period = str(result.get("analytics_period") or "last_30_days")
                lines.append(f"Métricas solo lectura ({period}, top por gasto):")
                for idx, row in enumerate(analytics_rows[:10], start=1):
                    if not isinstance(row, dict):
                        continue
                    nm = str(row.get("name") or "").strip().replace("\n", " ")[:72]
                    if not nm:
                        continue
                    lines.append(
                        f"{idx}) {nm} — coste {row.get('cost')} impr. {row.get('impressions')} "
                        f"clics {row.get('clicks')} CTR {row.get('ctr')} conv. {row.get('conversions')}"
                    )
            else:
                sample = result.get("campaigns")
                if isinstance(sample, list) and sample:
                    names: list[str] = []
                    for raw in sample[:5]:
                        piece = str(raw or "").strip().replace("\n", " ")
                        if piece:
                            names.append(piece)
                    if names:
                        joined = "; ".join(names)
                        if len(joined) > 420:
                            joined = joined[:417].rstrip() + "…"
                        lines.append("Muestra de campañas: " + joined)
            summary = str(result.get("analytics_summary") or "").strip()
            if summary:
                lines.append("Resumen: " + summary[:320])
            issues = result.get("analytics_issues")
            if isinstance(issues, list) and issues:
                joined_i = " | ".join(str(x) for x in issues[:4] if str(x).strip())
                if joined_i:
                    lines.append("Problemas destacados: " + joined_i[:420])
            opps = result.get("analytics_opportunities")
            if isinstance(opps, list) and opps:
                joined_o = " | ".join(str(x) for x in opps[:4] if str(x).strip())
                if joined_o:
                    lines.append("Oportunidades destacadas: " + joined_o[:420])
            aerr = str(result.get("analytics_query_error") or "").strip()
            if aerr:
                lines.append("Nota sobre la consulta de métricas: " + aerr[:280])
        else:
            lines.append("No se pudo obtener el listado de campañas.")
        err = str(result.get("error_message") or "").strip()
        if err:
            lines.append("Error de API: " + err[:350])
        return lines

    def _extract_ga4_execution_result(self, execution: dict[str, Any]) -> dict[str, Any] | None:
        candidates: list[dict[str, Any]] = []
        for row in (execution.get("executed") or []):
            if not isinstance(row, dict):
                continue
            action_type = str(row.get("action_type") or "").strip().lower()
            if action_type != "diagnose_ga4_setup":
                continue
            result = row.get("result")
            if isinstance(result, dict):
                candidates.append(result)
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

    def _format_ga4_engagement_display(self, value: Any) -> str:
        try:
            f = float(value)
        except (TypeError, ValueError):
            return str(value or "")
        if f <= 1.0:
            return f"{f * 100:.1f}%"
        return f"{f:.1f}%"

    def _format_ga4_execution_lines(self, result: dict[str, Any]) -> list[str]:
        lines: list[str] = []
        if result.get("env_configured"):
            lines.append("Configuración GA4 en el entorno: OK.")
        else:
            lines.append("Configuración GA4: incompleta (faltan variables de entorno).")
        if not result.get("ga4_analytics_fetch_ok"):
            qerr = str(result.get("analytics_query_error") or "").strip()
            if qerr:
                lines.append("Nota API de datos GA4: " + qerr[:320])
            return lines
        period = str(result.get("analytics_period") or "last_30_days")
        pages = [x for x in (result.get("analytics_top_pages") or []) if isinstance(x, dict)]
        events = [x for x in (result.get("analytics_top_events") or []) if isinstance(x, dict)]
        if pages:
            lines.append(f"Métricas solo lectura ({period}, páginas top por sesiones):")
            for idx, row in enumerate(pages[:10], start=1):
                path = str(row.get("path") or "").strip().replace("\n", " ")[:88]
                title = str(row.get("title") or "").strip().replace("\n", " ")[:56]
                label = f"{path}" + (f" — {title}" if title else "")
                if not label.strip():
                    continue
                er = self._format_ga4_engagement_display(row.get("engagement_rate"))
                lines.append(
                    f"{idx}) {label} — sesiones {row.get('sessions')} usuarios {row.get('users')} "
                    f"eventos {row.get('event_count')} engagement {er} conv. {row.get('conversions')}"
                )
        if events:
            lines.append(f"Métricas solo lectura ({period}, eventos top por volumen):")
            for idx, row in enumerate(events[:10], start=1):
                nm = str(row.get("name") or "").strip().replace("\n", " ")[:80]
                if not nm:
                    continue
                lines.append(
                    f"{idx}) {nm} — recuento {row.get('event_count')} usuarios {row.get('users')} conv. {row.get('conversions')}"
                )
        summary = str(result.get("analytics_summary") or "").strip()
        if summary:
            lines.append("Resumen GA4: " + summary[:320])
        issues = result.get("analytics_issues")
        if isinstance(issues, list) and issues:
            joined_i = " | ".join(str(x) for x in issues[:4] if str(x).strip())
            if joined_i:
                lines.append("Problemas destacados (GA4): " + joined_i[:420])
        opps = result.get("analytics_opportunities")
        if isinstance(opps, list) and opps:
            joined_o = " | ".join(str(x) for x in opps[:4] if str(x).strip())
            if joined_o:
                lines.append("Oportunidades destacadas (GA4): " + joined_o[:420])
        return lines


def run_autonomous_jarvis_from_telegram(*, text: str, actor: str, chat_id: str) -> dict[str, Any]:
    orch = JarvisAutonomousOrchestrator()
    return orch.run_new_mission(prompt=text, actor=actor, chat_id=chat_id)


def run_perico_from_telegram(*, text: str, actor: str, chat_id: str) -> dict[str, Any]:
    """Explicit software-specialist entrypoint (same mission system as Jarvis)."""
    orch = JarvisAutonomousOrchestrator()
    return orch.run_new_mission(prompt=text, actor=actor, chat_id=chat_id, specialist_agent="perico")


def handle_mission_command(*, raw_args: str, actor: str, chat_id: str) -> dict[str, Any]:
    cmdline = (raw_args or "").strip()
    if not cmdline:
        return {
            "ok": False,
            "dialog_message": (
                "Uso:\n"
                "/mission status <id>\n"
                "/mission approve <id>\n"
                "/mission reject <id> <motivo>\n"
                "/mission input <id> <texto>"
            ),
        }

    parts = cmdline.split(None, 2)
    action = (parts[0] or "").strip().lower()
    mission_id = (parts[1] or "").strip() if len(parts) >= 2 else ""
    tail = (parts[2] or "").strip() if len(parts) >= 3 else ""
    orch = JarvisAutonomousOrchestrator()

    if action == "status":
        mission = orch.notion.get_mission(mission_id)
        if not mission:
            return {"ok": False, "dialog_message": f"No encontré la misión: {mission_id}"}
        return {
            "ok": True,
            "mission_id": mission_id,
            "status": mission.get("status"),
            "dialog_message": (
                f"Misión {mission_id}\n"
                f"Estado: {mission.get('status')}\n"
                f"Título: {mission.get('task')}"
            ),
        }
    if action == "approve":
        return orch.continue_after_approval(
            mission_id=mission_id,
            approved=True,
            actor=actor,
            chat_id=chat_id,
            reason=tail,
        )
    if action == "reject":
        return orch.continue_after_approval(
            mission_id=mission_id,
            approved=False,
            actor=actor,
            chat_id=chat_id,
            reason=tail,
        )
    if action == "input":
        return orch.continue_after_input(
            mission_id=mission_id,
            input_text=tail,
            actor=actor,
            chat_id=chat_id,
        )
    return {"ok": False, "dialog_message": f"Subcomando de misión desconocido: {action}"}

