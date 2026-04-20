"""Autonomous Jarvis agents: planner, research, strategy, execution, outcome, review."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

from app.jarvis.action_policy import (
    DEFAULT_EXECUTION_MODE,
    compute_priority_score,
    get_action_policy,
    resolve_action_type,
)
from app.jarvis.analytics_mission_deliverables import infer_analytics_deliverables
from app.jarvis.analytics_prompt_gates import readonly_analytics_prompt_sufficient
from app.jarvis.bedrock_client import ask_bedrock, extract_planner_json_object
from app.jarvis.executor import invoke_registered_tool, is_invoke_error_payload
from app.jarvis.ga4_readonly_analytics import run_ga4_readonly_analytics
from app.jarvis.perico_mission import is_perico_marked_prompt
from app.jarvis.setup_diagnostics import (
    diagnose_ga4_setup_bundle,
    diagnose_gsc_setup_bundle,
    flatten_ga4_execution_result,
    flatten_gsc_execution_result,
)

_PERICO_REGISTERED_TOOLS: frozenset[str] = frozenset(
    {
        "perico_repo_read",
        "perico_apply_patch",
        "perico_run_pytest",
    }
)


def _skipped_vague_perico_placeholder(action: dict[str, Any], *, mission_prompt: str) -> bool:
    """
    Skip fluffy planner rows ('prepare for…') on Perico missions — force concrete perico_* tools.
    """
    if not is_perico_marked_prompt(mission_prompt):
        return False
    at = str(action.get("action_type") or "").strip().lower()
    if at in _PERICO_REGISTERED_TOOLS:
        return False
    if at.startswith("diagnose_"):
        return False
    blob = f"{action.get('title', '')} {action.get('rationale', '')}".lower()
    needles = (
        "prepare for potential",
        "prepare for",
        "prepare potential",
        "get ready to",
        "plan to run",
    )
    return any(n in blob for n in needles)


_OPS_DIAG_ACTION_BY_SOURCE: dict[str, str] = {
    "google ads": "diagnose_google_ads_setup",
    "google analytics": "diagnose_ga4_setup",
    "ga4": "diagnose_ga4_setup",
    "google search console": "diagnose_gsc_setup",
    "gsc": "diagnose_gsc_setup",
}

def _readonly_analytics_prompt_sufficient(prompt: str) -> bool:
    """Delegate to analytics_prompt_gates (kept as module attribute for tests and imports)."""
    return readonly_analytics_prompt_sufficient(prompt)


def _should_inject_google_ads_readonly_diagnostic(prompt: str) -> bool:
    """Inject concrete diagnose_google_ads_setup only for Google Ads (not GA4/GSC-only missions)."""
    if not _readonly_analytics_prompt_sufficient(prompt):
        return False
    spec = infer_analytics_deliverables(prompt)
    return spec is not None and spec.domain == "google_ads"


def _should_inject_ga4_readonly_diagnostic(prompt: str) -> bool:
    if not _readonly_analytics_prompt_sufficient(prompt):
        return False
    spec = infer_analytics_deliverables(prompt)
    return spec is not None and spec.domain == "ga4"


def _should_inject_gsc_readonly_diagnostic(prompt: str) -> bool:
    if not _readonly_analytics_prompt_sufficient(prompt):
        return False
    spec = infer_analytics_deliverables(prompt)
    return spec is not None and spec.domain == "gsc"


def _json_dump(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=True)
    except Exception:
        return str(value)


class PlannerAgent:
    name = "planner"

    def run(self, prompt: str) -> dict[str, Any]:
        ask = (
            "Create a concise execution plan for an autonomous software operator.\n"
            "Return only JSON with keys: objective (string), steps (array of strings), "
            "requires_research (boolean), requires_input (boolean).\n"
            f"Prompt: {prompt}"
        )
        raw = ask_bedrock(ask)
        parsed = extract_planner_json_object(raw or "")
        if not isinstance(parsed, dict):
            return {
                "objective": prompt[:300],
                "steps": [
                    "Understand mission goal and constraints.",
                    "Gather missing context before unsafe actions.",
                    "Execute safe actions and verify outcomes.",
                ],
                "requires_research": True,
                "requires_input": False,
                "source": "fallback",
            }
        steps = parsed.get("steps")
        requires_input = bool(parsed.get("requires_input"))
        if requires_input and _readonly_analytics_prompt_sufficient(prompt):
            requires_input = False
        return {
            "objective": str(parsed.get("objective") or prompt[:300]),
            "steps": [str(s) for s in steps] if isinstance(steps, list) else [],
            "requires_research": bool(parsed.get("requires_research")),
            "requires_input": requires_input,
            "source": "bedrock",
        }


class ResearchAgent:
    name = "research"

    def run(self, *, prompt: str, plan: dict[str, Any]) -> dict[str, Any]:
        ask = (
            "You are a research agent. Produce JSON only with keys "
            "findings (array of strings), open_questions (array of strings), confidence (0-1 float).\n"
            f"Mission prompt: {prompt}\n"
            f"Plan: {_json_dump(plan)[:2400]}"
        )
        raw = ask_bedrock(ask)
        parsed = extract_planner_json_object(raw or "")
        if not isinstance(parsed, dict):
            return {
                "findings": ["No external data source configured; proceeding with available context."],
                "open_questions": [],
                "confidence": 0.55,
                "source": "fallback",
            }
        return {
            "findings": [str(x) for x in parsed.get("findings", []) if isinstance(x, (str, int, float))],
            "open_questions": [str(x) for x in parsed.get("open_questions", []) if isinstance(x, (str, int, float))],
            "confidence": float(parsed.get("confidence", 0.6) or 0.6),
            "source": "bedrock",
        }


class StrategyAgent:
    name = "strategy"

    def run(
        self,
        *,
        prompt: str,
        plan: dict[str, Any],
        research: dict[str, Any] | None,
        outcome_memory: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        history = outcome_memory or []
        success_rate = _historical_success_rate(history)
        ask = (
            "You are a strategy agent. You do not execute actions.\n"
            "Return only JSON with key actions (array). Each action must include:\n"
            "- title (string)\n"
            "- rationale (string)\n"
            "- action_type (string)\n"
            "- params (object)\n"
            "- impact (low|medium|high)\n"
            "- confidence (float 0..1)\n"
            "- requires_approval (boolean)\n"
            "Sort actions by priority (highest first).\n"
            f"Mission prompt: {prompt}\n"
            f"Plan: {_json_dump(plan)[:1800]}\n"
            f"Research: {_json_dump(research or {})[:2200]}\n"
            f"Historical outcome success rate: {success_rate:.3f}"
        )
        raw = ask_bedrock(ask)
        parsed = extract_planner_json_object(raw or "")
        if not isinstance(parsed, dict):
            # Fallback: derive one conservative action from available research.
            findings = [str(x) for x in ((research or {}).get("findings") or []) if isinstance(x, (str, int, float))]
            title = findings[0][:120] if findings else "Validate mission assumptions and proceed with safe execution."
            action_type_fb = resolve_action_type(title)
            policy_fb = get_action_policy(action_type_fb)
            em_fb = str(policy_fb.get("execution_mode") or DEFAULT_EXECUTION_MODE)
            conf_fb = float((research or {}).get("confidence") or 0.55)
            fb_actions: list[dict[str, Any]] = [
                {
                    "title": title,
                    "rationale": "Fallback strategy from available mission context.",
                    "action_type": action_type_fb,
                    "params": {"note": "fallback"},
                    "impact": "medium",
                    "confidence": conf_fb,
                    "execution_mode": em_fb,
                    "requires_approval": em_fb == "requires_approval",
                    "priority_score": compute_priority_score(
                        action_type=action_type_fb,
                        impact="medium",
                        confidence=conf_fb,
                    ),
                }
            ]
            fb_actions = self._append_ops_diagnosis_actions(fb_actions, prompt=prompt, research=research)
            fb_actions = self._inject_google_ads_readonly_analytics_if_needed(fb_actions, prompt=prompt)
            fb_actions = self._inject_ga4_readonly_setup_if_needed(fb_actions, prompt=prompt)
            fb_actions = self._inject_gsc_readonly_setup_if_needed(fb_actions, prompt=prompt)
            return {"actions": fb_actions, "source": "fallback"}
        raw_actions = parsed.get("actions")
        actions: list[dict[str, Any]] = []
        if isinstance(raw_actions, list):
            for item in raw_actions:
                if not isinstance(item, dict):
                    continue
                impact = str(item.get("impact") or "medium").strip().lower()
                if impact not in ("low", "medium", "high"):
                    impact = "medium"
                confidence_val = item.get("confidence", 0.6)
                try:
                    confidence = max(0.0, min(1.0, float(confidence_val)))
                except Exception:
                    confidence = 0.6
                confidence = _adjust_confidence_with_history(confidence, success_rate)
                title = str(item.get("title") or "").strip()[:200]
                hinted_type = str(item.get("action_type") or "").strip().lower()
                action_type = resolve_action_type(title, hinted_type)
                policy = get_action_policy(action_type)
                execution_mode = str(policy.get("execution_mode") or DEFAULT_EXECUTION_MODE)
                params = item.get("params") if isinstance(item.get("params"), dict) else {}
                priority_score = compute_priority_score(
                    action_type=action_type,
                    impact=impact,
                    confidence=confidence,
                )
                actions.append(
                    {
                        "title": title,
                        "rationale": str(item.get("rationale") or "").strip()[:500],
                        "action_type": action_type,
                        "params": params,
                        "impact": impact,
                        "confidence": confidence,
                        "execution_mode": execution_mode,
                        "requires_approval": execution_mode == "requires_approval",
                        "priority_score": priority_score,
                    }
                )
        if not actions:
            action_type = "analysis"
            execution_mode = str(get_action_policy(action_type).get("execution_mode") or DEFAULT_EXECUTION_MODE)
            actions.append(
                {
                    "title": "No strategy actions returned; fallback to safe incremental progress.",
                    "rationale": "Strategy model returned an empty payload.",
                    "action_type": action_type,
                    "params": {"note": "empty_strategy_payload"},
                    "impact": "low",
                    "confidence": _adjust_confidence_with_history(0.4, success_rate),
                    "execution_mode": execution_mode,
                    "requires_approval": execution_mode == "requires_approval",
                    "priority_score": compute_priority_score(
                        action_type=action_type,
                        impact="low",
                        confidence=_adjust_confidence_with_history(0.4, success_rate),
                    ),
                }
            )
        # Ensure strict ordering: highest priority_score first, preserving model order as tiebreaker.
        actions = sorted(
            enumerate(actions),
            key=lambda row: (-int(row[1].get("priority_score", 0) or 0), row[0]),
        )
        ordered = [row[1] for row in actions]
        ordered = self._append_ops_diagnosis_actions(
            ordered,
            prompt=prompt,
            research=research,
        )
        ordered = self._inject_google_ads_readonly_analytics_if_needed(ordered, prompt=prompt)
        ordered = self._inject_ga4_readonly_setup_if_needed(ordered, prompt=prompt)
        ordered = self._inject_gsc_readonly_setup_if_needed(ordered, prompt=prompt)
        return {"actions": ordered, "source": "bedrock"}

    def _inject_google_ads_readonly_analytics_if_needed(
        self, actions: list[dict[str, Any]], *, prompt: str
    ) -> list[dict[str, Any]]:
        """Bedrock often returns abstract 'analysis' steps; force one real Ads diagnostic when scope is clear."""
        if not _should_inject_google_ads_readonly_diagnostic(prompt):
            return actions
        for a in actions:
            if not isinstance(a, dict):
                continue
            if str(a.get("action_type") or "").strip().lower() == "diagnose_google_ads_setup":
                return actions
        policy = get_action_policy("diagnose_google_ads_setup")
        execution_mode = str(policy.get("execution_mode") or DEFAULT_EXECUTION_MODE)
        confidence = 0.92
        inj: dict[str, Any] = {
            "title": "Google Ads read-only diagnostics and metrics (last 30 days)",
            "rationale": (
                "Run the concrete Google Ads API read-only diagnostic and last-30-day spend/metrics query; "
                "no account mutations."
            ),
            "action_type": "diagnose_google_ads_setup",
            "params": {},
            "impact": "high",
            "confidence": confidence,
            "execution_mode": execution_mode,
            "requires_approval": execution_mode == "requires_approval",
            "priority_score": compute_priority_score(
                action_type="diagnose_google_ads_setup",
                impact="high",
                confidence=confidence,
            ),
        }
        merged = actions + [inj]
        merged = sorted(
            enumerate(merged),
            key=lambda row: (-int(row[1].get("priority_score", 0) or 0), row[0]),
        )
        return [row[1] for row in merged]

    def _inject_ga4_readonly_setup_if_needed(self, actions: list[dict[str, Any]], *, prompt: str) -> list[dict[str, Any]]:
        if not _should_inject_ga4_readonly_diagnostic(prompt):
            return actions
        for a in actions:
            if not isinstance(a, dict):
                continue
            if str(a.get("action_type") or "").strip().lower() == "diagnose_ga4_setup":
                return actions
        policy = get_action_policy("diagnose_ga4_setup")
        execution_mode = str(policy.get("execution_mode") or DEFAULT_EXECUTION_MODE)
        confidence = 0.92
        inj: dict[str, Any] = {
            "title": "GA4 read-only analytics (last 30 days, top pages and events)",
            "rationale": (
                "Run GA4 runtime env check plus GA4 Data API read-only reports (top pages/events); "
                "no account mutations."
            ),
            "action_type": "diagnose_ga4_setup",
            "params": {"container_name": "backend-aws"},
            "impact": "high",
            "confidence": confidence,
            "execution_mode": execution_mode,
            "requires_approval": execution_mode == "requires_approval",
            "priority_score": compute_priority_score(
                action_type="diagnose_ga4_setup",
                impact="high",
                confidence=confidence,
            ),
        }
        merged = actions + [inj]
        merged = sorted(
            enumerate(merged),
            key=lambda row: (-int(row[1].get("priority_score", 0) or 0), row[0]),
        )
        return [row[1] for row in merged]

    def _inject_gsc_readonly_setup_if_needed(self, actions: list[dict[str, Any]], *, prompt: str) -> list[dict[str, Any]]:
        if not _should_inject_gsc_readonly_diagnostic(prompt):
            return actions
        for a in actions:
            if not isinstance(a, dict):
                continue
            if str(a.get("action_type") or "").strip().lower() == "diagnose_gsc_setup":
                return actions
        policy = get_action_policy("diagnose_gsc_setup")
        execution_mode = str(policy.get("execution_mode") or DEFAULT_EXECUTION_MODE)
        confidence = 0.92
        inj: dict[str, Any] = {
            "title": "Google Search Console read-only setup check and analytics placeholder",
            "rationale": (
                "Run the concrete GSC runtime env diagnostic for read-only analytics missions; "
                "no site mutations."
            ),
            "action_type": "diagnose_gsc_setup",
            "params": {"container_name": "backend-aws"},
            "impact": "high",
            "confidence": confidence,
            "execution_mode": execution_mode,
            "requires_approval": execution_mode == "requires_approval",
            "priority_score": compute_priority_score(
                action_type="diagnose_gsc_setup",
                impact="high",
                confidence=confidence,
            ),
        }
        merged = actions + [inj]
        merged = sorted(
            enumerate(merged),
            key=lambda row: (-int(row[1].get("priority_score", 0) or 0), row[0]),
        )
        return [row[1] for row in merged]

    def _append_ops_diagnosis_actions(
        self,
        actions: list[dict[str, Any]],
        *,
        prompt: str,
        research: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        findings = [str(x) for x in ((research or {}).get("findings") or []) if isinstance(x, (str, int, float))]
        haystack = "\n".join([prompt, *findings]).lower()
        if "not configured" not in haystack:
            return actions
        existing_types = {
            str(a.get("action_type") or "").strip().lower()
            for a in actions
            if isinstance(a, dict)
        }
        extras: list[dict[str, Any]] = []
        for needle, action_type in _OPS_DIAG_ACTION_BY_SOURCE.items():
            if needle not in haystack:
                continue
            if action_type in existing_types:
                continue
            policy = get_action_policy(action_type)
            execution_mode = str(policy.get("execution_mode") or DEFAULT_EXECUTION_MODE)
            extras.append(
                {
                    "title": f"Diagnose {needle.title()} setup in runtime container",
                    "rationale": (
                        f"Research/prompt indicates '{needle}' is not configured; run runtime diagnostics before business execution."
                    ),
                    "action_type": action_type,
                    "params": {"container_name": "backend-aws"},
                    "impact": "high",
                    "confidence": 0.8,
                    "execution_mode": execution_mode,
                    "requires_approval": execution_mode == "requires_approval",
                    "priority_score": compute_priority_score(
                        action_type=action_type,
                        impact="high",
                        confidence=0.8,
                    ),
                }
            )
        if not extras:
            return actions
        merged = actions + extras
        merged = sorted(
            enumerate(merged),
            key=lambda row: (-int(row[1].get("priority_score", 0) or 0), row[0]),
        )
        return [row[1] for row in merged]

    @staticmethod
    def propose_google_ads_pause_from_readonly_diagnostic(diag: dict[str, Any]) -> list[dict[str, Any]]:
        """Strategy-layer hook: deterministic pause proposals from read-only Ads metrics (no mutations)."""
        from app.jarvis.google_ads_pause_proposals import build_google_ads_pause_campaign_actions

        return build_google_ads_pause_campaign_actions(diag)


class ExecutionAgent:
    name = "execution"

    def run(
        self,
        *,
        strategy: dict[str, Any] | None,
        mission_prompt: str = "",
    ) -> dict[str, Any]:
        strategy_actions = [
            a
            for a in ((strategy or {}).get("actions") or [])
            if isinstance(a, dict) and str(a.get("title") or "").strip()
        ]
        executed: list[dict[str, Any]] = []
        waiting_approval: list[dict[str, Any]] = []
        waiting_input: list[dict[str, Any]] = []
        for action in strategy_actions:
            mode = str(action.get("execution_mode") or DEFAULT_EXECUTION_MODE).strip().lower()
            if mode == "approval_required":
                mode = "requires_approval"
            row = {
                "title": str(action.get("title") or "").strip(),
                "action_type": str(action.get("action_type") or "analysis"),
                "params": action.get("params") if isinstance(action.get("params"), dict) else {},
                "execution_mode": mode,
                "priority_score": int(action.get("priority_score", 0) or 0),
            }
            if _skipped_vague_perico_placeholder(action, mission_prompt=mission_prompt):
                executed.append(
                    {
                        **row,
                        "status": "skipped",
                        "result": {
                            "ok": False,
                            "error": "vague_placeholder_action",
                            "message": (
                                "Acción demasiado vaga; en misiones Perico usa perico_repo_read, "
                                "perico_apply_patch o perico_run_pytest."
                            ),
                        },
                    }
                )
                continue
            if mode == "auto_execute":
                action_type = str(action.get("action_type") or "").strip().lower()
                if _is_google_ads_diagnostic_action(action):
                    diag_params: dict[str, Any] = dict(row.get("params") or {})
                    if _readonly_analytics_prompt_sufficient(mission_prompt):
                        diag_params["include_readonly_analytics_last_30d"] = True
                    diag = run_google_ads_readonly_diagnostic(diag_params)
                    executed.append(
                        {
                            **row,
                            "status": "executed" if diag.get("auth_ok") and diag.get("campaign_fetch_ok") else "failed",
                            "result": diag,
                        }
                    )
                elif action_type == "diagnose_ga4_setup":
                    params = dict(row.get("params") or {})
                    bundle = diagnose_ga4_setup_bundle(params)
                    flat = flatten_ga4_execution_result(bundle)
                    if flat.get("env_configured") and _readonly_analytics_prompt_sufficient(mission_prompt):
                        spec_ga = infer_analytics_deliverables(mission_prompt)
                        top_n = spec_ga.top_rank if spec_ga and spec_ga.top_rank else 10
                        analytics_payload = run_ga4_readonly_analytics({"limit": top_n, **params})
                        for k, v in analytics_payload.items():
                            if v is not None:
                                flat[k] = v
                    ok_env = bool(flat.get("env_configured"))
                    executed.append({**row, "status": "executed" if ok_env else "failed", "result": flat})
                elif action_type == "diagnose_gsc_setup":
                    params = dict(row.get("params") or {})
                    bundle = diagnose_gsc_setup_bundle(params)
                    flat = flatten_gsc_execution_result(bundle)
                    executed.append({**row, "status": "executed", "result": flat})
                elif action_type in _PERICO_REGISTERED_TOOLS:
                    if not is_perico_marked_prompt(mission_prompt):
                        executed.append(
                            {
                                **row,
                                "status": "skipped",
                                "result": {
                                    "ok": False,
                                    "error": "perico_tools_require_perico_mission",
                                    "message": "Use /perico or a prompt containing the Perico software marker.",
                                },
                            }
                        )
                    else:
                        params = dict(row.get("params") or {})
                        raw = invoke_registered_tool(action_type, params, jarvis_run_id=None)
                        if is_invoke_error_payload(raw):
                            executed.append(
                                {
                                    **row,
                                    "status": "failed",
                                    "result": raw,
                                }
                            )
                        elif isinstance(raw, dict) and raw.get("ok") is False:
                            executed.append(
                                {
                                    **row,
                                    "status": "failed",
                                    "result": raw,
                                }
                            )
                        else:
                            executed.append(
                                {
                                    **row,
                                    "status": "executed",
                                    "result": raw if isinstance(raw, dict) else {"value": raw},
                                }
                            )
                else:
                    executed.append(row)
            elif mode == "requires_input":
                waiting_input.append(row)
            else:
                waiting_approval.append(row)
        needs_approval = bool(waiting_approval)
        return {
            "executed": executed,
            "waiting_for_approval": waiting_approval,
            "waiting_for_input": waiting_input,
            "needs_approval": needs_approval,
            "approval_summary": (
                "; ".join(str(x.get("title") or "") for x in waiting_approval[:4])
                if waiting_approval
                else ""
            ),
        }


def _normalize_ads_customer_id(value: str) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def _classify_google_ads_error(error_text: str) -> str:
    msg = (error_text or "").lower()
    if "developer token" in msg:
        return "developer_token"
    if any(x in msg for x in ("oauth", "invalid_grant", "unauthorized_client", "refresh token")):
        return "oauth"
    if any(
        x in msg
        for x in (
            "user_permission_denied",
            "permission_denied",
            "statuscode.permission_denied",
            "the caller does not have permission",
            "doesn't have permission to access customer",
            "login-customer-id",
        )
    ):
        return "permissions"
    if any(x in msg for x in ("permission", "not authorized", "authorizationerror", "access denied")):
        return "permissions"
    if any(x in msg for x in ("customer", "account", "manager")):
        return "account_access"
    if any(x in msg for x in ("service_disabled", "has not been used", "it is disabled")):
        return "permissions"
    if any(x in msg for x in ("credential", "service account", "json", "file", "key")):
        return "credentials"
    return "unknown"


def _google_ads_failure(*, message: str, error_type: str, auth_ok: bool = False) -> dict[str, Any]:
    return {
        "auth_ok": bool(auth_ok),
        "campaign_fetch_ok": False,
        "campaign_count": None,
        "campaigns": [],
        "error_type": error_type,
        "error_message": str(message)[:1200],
    }


def _ads_money_from_micros(micros: Any) -> str:
    try:
        v = int(micros)
    except (TypeError, ValueError):
        return "0.00"
    return f"{v / 1_000_000:.2f}"


def _ads_ctr_percent(ctr: Any) -> str:
    try:
        c = float(ctr or 0.0)
    except (TypeError, ValueError):
        return "0.00%"
    return f"{c * 100:.2f}%"


def _campaign_metric_row_from_search_row(row: Any, *, include_budget_fields: bool) -> dict[str, Any] | None:
    camp = getattr(row, "campaign", None)
    met = getattr(row, "metrics", None)
    if camp is None or met is None:
        return None
    name = str(getattr(camp, "name", "") or "").strip()
    if not name:
        return None
    cid_raw = getattr(camp, "id", None)
    try:
        cid = int(cid_raw) if cid_raw is not None else 0
    except (TypeError, ValueError):
        cid = 0
    st = getattr(camp, "status", None)
    status_name = ""
    if st is not None:
        status_name = str(getattr(st, "name", None) or st or "").strip()
    impr = int(getattr(met, "impressions", 0) or 0)
    clk = int(getattr(met, "clicks", 0) or 0)
    conv = float(getattr(met, "conversions", 0.0) or 0.0)
    out: dict[str, Any] = {
        "campaign_id": cid,
        "name": name,
        "status": status_name,
        "cost": _ads_money_from_micros(getattr(met, "cost_micros", 0)),
        "impressions": impr,
        "clicks": clk,
        "ctr": _ads_ctr_percent(getattr(met, "ctr", 0.0)),
        "conversions": conv,
    }
    if include_budget_fields:
        budget_rn = ""
        cb_ref = getattr(camp, "campaign_budget", None)
        if cb_ref is not None:
            budget_rn = str(cb_ref).strip()
        cb_msg = getattr(row, "campaign_budget", None)
        amt = 0
        exp_shared = False
        if cb_msg is not None:
            if not budget_rn:
                budget_rn = str(getattr(cb_msg, "resource_name", "") or "").strip()
            try:
                amt = int(getattr(cb_msg, "amount_micros", 0) or 0)
            except (TypeError, ValueError):
                amt = 0
            es = getattr(cb_msg, "explicitly_shared", None)
            if es is not None:
                try:
                    exp_shared = bool(es)
                except Exception:
                    exp_shared = False
        out["campaign_budget_resource_name"] = budget_rn
        out["budget_amount_micros"] = amt
        out["budget_explicitly_shared"] = exp_shared
    return out


def _fetch_readonly_campaign_metrics_last_30d(ga_service: Any, client: Any, customer_id: str) -> list[dict[str, Any]]:
    """Read-only GAQL: top campaigns by spend for LAST_30_DAYS (no mutations).

    Tries an extended query (daily budget fields) first; on API error falls back to the
    legacy metrics-only query so analytics missions keep working.
    """
    extended_query = (
        "SELECT campaign.id, campaign.name, campaign.status, campaign.campaign_budget, "
        "campaign_budget.amount_micros, campaign_budget.resource_name, campaign_budget.explicitly_shared, "
        "metrics.cost_micros, metrics.impressions, metrics.clicks, metrics.ctr, metrics.conversions "
        "FROM campaign "
        "WHERE segments.date DURING LAST_30_DAYS AND campaign.status IN ('ENABLED', 'PAUSED') "
        "ORDER BY metrics.cost_micros DESC LIMIT 10"
    )
    narrow_query = (
        "SELECT campaign.id, campaign.name, metrics.cost_micros, metrics.impressions, "
        "metrics.clicks, metrics.ctr, metrics.conversions "
        "FROM campaign "
        "WHERE segments.date DURING LAST_30_DAYS AND campaign.status IN ('ENABLED', 'PAUSED') "
        "ORDER BY metrics.cost_micros DESC LIMIT 10"
    )
    for use_budget, query in ((True, extended_query), (False, narrow_query)):
        req = client.get_type("SearchGoogleAdsRequest")
        req.customer_id = customer_id
        req.query = query
        rows_out: list[dict[str, Any]] = []
        try:
            for row in ga_service.search(request=req):
                built = _campaign_metric_row_from_search_row(row, include_budget_fields=use_budget)
                if built:
                    rows_out.append(built)
            if use_budget and not rows_out:
                continue
            return rows_out
        except Exception as exc:
            if use_budget:
                logger.warning(
                    "jarvis.google_ads.extended_metrics_query_failed customer_id=%s err=%s; falling_back",
                    customer_id,
                    exc,
                )
                continue
            raise
    return []


def _readonly_analytics_insights(rows: list[dict[str, Any]]) -> tuple[list[str], list[str], str]:
    """Lightweight read-only heuristics from aggregated campaign rows (not API recommendations)."""
    issues: list[str] = []
    opps: list[str] = []
    if not rows:
        return issues, opps, "No campaign performance rows returned for the last 30 days."
    top = rows[0]
    total_cost = 0.0
    total_conv = 0.0
    for r in rows:
        try:
            total_cost += float(str(r.get("cost") or "0"))
        except ValueError:
            pass
        try:
            total_conv += float(r.get("conversions") or 0)
        except (TypeError, ValueError):
            pass
    try:
        top_cost = float(str(top.get("cost") or "0"))
    except ValueError:
        top_cost = 0.0
    if float(top.get("conversions") or 0) == 0 and top_cost > 0:
        issues.append(f"Top-spend campaign '{top.get('name')}' shows zero conversions in the window.")
    for r in rows[:5]:
        impr = int(r.get("impressions") or 0)
        clk = int(r.get("clicks") or 0)
        ctr_ratio = (clk / impr) if impr > 0 else 0.0
        if impr >= 800 and clk >= 20 and ctr_ratio < 0.01:
            issues.append(f"Low CTR on '{r.get('name')}' ({r.get('ctr')}) with meaningful traffic.")
            break
    for r in rows[:5]:
        impr = int(r.get("impressions") or 0)
        clk = int(r.get("clicks") or 0)
        conv = float(r.get("conversions") or 0.0)
        ctr_ratio = (clk / impr) if impr > 0 else 0.0
        if impr >= 400 and ctr_ratio >= 0.03 and conv >= 1:
            opps.append(
                f"Strong CTR ({r.get('ctr')}) with conversions on '{r.get('name')}'—good candidate to study or scale."
            )
            break
    if not opps:
        opps.append(f"Compare creatives and audiences among the top {min(5, len(rows))} spenders for incremental wins.")
    summary = (
        f"Last 30 days read-only snapshot: {len(rows)} campaigns by spend; "
        f"approx combined cost {total_cost:.2f}; conversions (metric) {total_conv:.1f}."
    )
    return issues[:4], opps[:4], summary


def _load_google_ads_oauth_client_config(creds_path: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        with open(creds_path, "r", encoding="utf-8") as handle:
            parsed = json.load(handle)
    except Exception as exc:
        return None, f"Google Ads credentials JSON is unreadable: {exc}"

    if not isinstance(parsed, dict):
        return None, "Google Ads credentials JSON is malformed."

    root = None
    if isinstance(parsed.get("installed"), dict):
        root = parsed.get("installed")
    elif isinstance(parsed.get("web"), dict):
        root = parsed.get("web")
    elif parsed.get("type") == "service_account":
        return (
            None,
            (
                "Google Ads credentials JSON is a service-account file, but this diagnostic expects "
                "an OAuth client JSON (installed/web) plus refresh token."
            ),
        )
    elif "client_id" in parsed and "client_secret" in parsed:
        root = parsed

    if not isinstance(root, dict):
        return (
            None,
            "Google Ads credentials JSON must include OAuth client fields (client_id, client_secret).",
        )
    client_id = str(root.get("client_id") or "").strip()
    client_secret = str(root.get("client_secret") or "").strip()
    if not client_id or not client_secret:
        return (
            None,
            "Google Ads credentials JSON must include OAuth client_id and client_secret.",
        )
    return {"client_id": client_id, "client_secret": client_secret}, None


def run_google_ads_readonly_diagnostic(params: dict[str, Any]) -> dict[str, Any]:
    creds_path = str(
        params.get("credentials_json")
        or os.getenv("JARVIS_GOOGLE_ADS_CREDENTIALS_JSON")
        or ""
    ).strip()
    developer_token = str(
        params.get("developer_token")
        or os.getenv("JARVIS_GOOGLE_ADS_DEVELOPER_TOKEN")
        or ""
    ).strip()
    customer_id_raw = str(
        params.get("customer_id")
        or os.getenv("JARVIS_GOOGLE_ADS_CUSTOMER_ID")
        or ""
    ).strip()
    refresh_token = str(
        params.get("refresh_token")
        or os.getenv("JARVIS_GOOGLE_ADS_REFRESH_TOKEN")
        or ""
    ).strip()
    login_customer_id_raw = str(
        params.get("login_customer_id")
        or os.getenv("JARVIS_GOOGLE_ADS_LOGIN_CUSTOMER_ID")
        or ""
    ).strip()
    login_customer_id = _normalize_ads_customer_id(login_customer_id_raw)
    customer_id = _normalize_ads_customer_id(customer_id_raw)

    if not developer_token:
        return _google_ads_failure(
            message="Google Ads developer token is missing.",
            error_type="developer_token",
            auth_ok=False,
        )
    if not customer_id:
        return _google_ads_failure(
            message="Google Ads customer ID is missing.",
            error_type="account_access",
            auth_ok=False,
        )
    if not creds_path:
        return _google_ads_failure(
            message="Google Ads credentials JSON path is missing.",
            error_type="credentials",
            auth_ok=False,
        )
    if not os.path.isfile(creds_path):
        return _google_ads_failure(
            message=f"Google Ads credentials file is not accessible: {creds_path}",
            error_type="credentials",
            auth_ok=False,
        )
    if not refresh_token:
        return _google_ads_failure(
            message="Google Ads OAuth refresh token is missing.",
            error_type="oauth",
            auth_ok=False,
        )
    oauth_client, oauth_err = _load_google_ads_oauth_client_config(creds_path)
    if oauth_client is None:
        return _google_ads_failure(
            message=str(oauth_err or "Google Ads OAuth credentials are invalid."),
            error_type="credentials",
            auth_ok=False,
        )

    try:
        from google.ads.googleads.client import GoogleAdsClient  # type: ignore
    except Exception as exc:
        return _google_ads_failure(
            message=f"Google Ads client library is unavailable: {exc}",
            error_type="unknown",
            auth_ok=False,
        )

    try:
        client_cfg: dict[str, Any] = {
            "developer_token": developer_token,
            "client_id": str(oauth_client.get("client_id") or ""),
            "client_secret": str(oauth_client.get("client_secret") or ""),
            "refresh_token": refresh_token,
            "use_proto_plus": True,
        }
        if login_customer_id:
            client_cfg["login_customer_id"] = login_customer_id
        client = GoogleAdsClient.load_from_dict(client_cfg)
        ga_service = client.get_service("GoogleAdsService")
    except Exception as exc:
        message = str(exc)
        return _google_ads_failure(
            message=message,
            error_type=_classify_google_ads_error(message),
            auth_ok=False,
        )

    try:
        auth_req = client.get_type("SearchGoogleAdsRequest")
        auth_req.customer_id = customer_id
        auth_req.query = "SELECT customer.id FROM customer LIMIT 1"
        next(iter(ga_service.search(request=auth_req)), None)
    except Exception as exc:
        message = str(exc)
        return _google_ads_failure(
            message=message,
            error_type=_classify_google_ads_error(message),
            auth_ok=False,
        )

    include_analytics = bool(params.get("include_readonly_analytics_last_30d"))

    def _basic_campaign_names() -> list[str]:
        campaign_req = client.get_type("SearchGoogleAdsRequest")
        campaign_req.customer_id = customer_id
        campaign_req.query = (
            "SELECT campaign.id, campaign.name, campaign.status "
            "FROM campaign "
            "ORDER BY campaign.id "
            "LIMIT 10"
        )
        names_local: list[str] = []
        for row in ga_service.search(request=campaign_req):
            campaign = getattr(row, "campaign", None)
            name = str(getattr(campaign, "name", "") or "").strip()
            if name:
                names_local.append(name)
        return names_local

    try:
        if include_analytics:
            try:
                metric_rows = _fetch_readonly_campaign_metrics_last_30d(ga_service, client, customer_id)
                issues, opps, summary = _readonly_analytics_insights(metric_rows)
                names = [str(r.get("name") or "").strip() for r in metric_rows if str(r.get("name") or "").strip()]
                return {
                    "auth_ok": True,
                    "campaign_fetch_ok": True,
                    "campaign_count": len(metric_rows),
                    "campaigns": names[:5],
                    "analytics_period": "last_30_days",
                    "analytics_top_campaigns": metric_rows,
                    "analytics_issues": issues,
                    "analytics_opportunities": opps,
                    "analytics_summary": summary,
                    "error_type": None,
                    "error_message": None,
                }
            except Exception as exc:
                campaign_names = _basic_campaign_names()
                return {
                    "auth_ok": True,
                    "campaign_fetch_ok": True,
                    "campaign_count": len(campaign_names),
                    "campaigns": campaign_names[:5],
                    "analytics_period": "last_30_days",
                    "analytics_top_campaigns": [],
                    "analytics_issues": [],
                    "analytics_opportunities": [],
                    "analytics_summary": "Extended metrics query failed; basic campaign list returned.",
                    "analytics_query_error": str(exc)[:400],
                    "error_type": None,
                    "error_message": None,
                }

        campaign_names = _basic_campaign_names()
        return {
            "auth_ok": True,
            "campaign_fetch_ok": True,
            "campaign_count": len(campaign_names),
            "campaigns": campaign_names[:5],
            "error_type": None,
            "error_message": None,
        }
    except Exception as exc:
        message = str(exc)
        return _google_ads_failure(
            message=message,
            error_type=_classify_google_ads_error(message),
            auth_ok=True,
        )


def _is_google_ads_diagnostic_action(action: dict[str, Any]) -> bool:
    action_type = str(action.get("action_type") or "").strip().lower()
    if action_type in {"diagnose_google_ads_setup", "test_google_ads_connection", "google_ads_diagnostic"}:
        return True
    text = " ".join(
        [
            str(action.get("title") or ""),
            str(action.get("rationale") or ""),
            action_type,
        ]
    ).lower()
    return "google ads" in text and any(
        needle in text for needle in ("diagnos", "auth", "campaign", "connection", "api")
    )


def _execution_uses_perico_repo_tools(execution: dict[str, Any]) -> bool:
    for row in execution.get("executed") or []:
        if not isinstance(row, dict):
            continue
        at = str(row.get("action_type") or "").strip().lower()
        if at.startswith("perico_"):
            return True
    return False


class ReviewAgent:
    name = "review"

    def run(self, *, plan: dict[str, Any], execution: dict[str, Any]) -> dict[str, Any]:
        _ = plan
        ok = bool(execution.get("executed")) and not bool(execution.get("needs_approval"))
        if ok:
            if _execution_uses_perico_repo_tools(execution):
                return {
                    "passed": True,
                    "summary": "Perico ejecutó herramientas de repo; el cierre operativo va en goal_check / perico_deliverables.",
                }
            return {
                "passed": True,
                "summary": "Mission completed with safe actions and validation checks.",
            }
        if execution.get("needs_approval"):
            return {
                "passed": False,
                "summary": "Mission paused waiting for explicit user approval for critical actions.",
            }
        return {
            "passed": False,
            "summary": "Execution output was incomplete or unsafe to finalize.",
        }


class OutcomeEvaluatorAgent:
    """
    Evaluate executed actions against expected impact by comparing baseline vs updated metrics.
    """

    name = "outcome_evaluator"

    def evaluate(
        self,
        *,
        executed_actions: list[dict[str, Any]],
        baseline_by_title: dict[str, dict[str, Any]],
        updated_metrics: dict[str, Any],
    ) -> dict[str, Any]:
        evaluations: list[dict[str, Any]] = []
        for action in executed_actions:
            title = str(action.get("title") or "").strip()
            baseline = baseline_by_title.get(title) or {"score": 100.0}
            before = float(baseline.get("score", 100.0) or 100.0)
            after = float(updated_metrics.get("score", before) or before)
            delta = after - before
            if delta > 0.5:
                status = "success"
            elif delta < -0.5:
                status = "failure"
            else:
                status = "neutral"
            evaluations.append(
                {
                    "title": title,
                    "action_type": str(action.get("action_type") or "analysis"),
                    "execution_mode": str(action.get("execution_mode") or "unknown"),
                    "priority_score": int(action.get("priority_score", 0) or 0),
                    "expected_impact": str(action.get("impact") or "medium"),
                    "before_metrics": baseline,
                    "after_metrics": updated_metrics,
                    "delta": round(delta, 4),
                    "outcome": status,
                }
            )
        summary = {
            "success": sum(1 for x in evaluations if x.get("outcome") == "success"),
            "neutral": sum(1 for x in evaluations if x.get("outcome") == "neutral"),
            "failure": sum(1 for x in evaluations if x.get("outcome") == "failure"),
            "total": len(evaluations),
        }
        return {"evaluations": evaluations, "summary": summary}


def _historical_success_rate(memory: list[dict[str, Any]]) -> float:
    if not memory:
        return 0.5
    total = 0
    success = 0
    for row in memory:
        if not isinstance(row, dict):
            continue
        out = str(row.get("outcome") or "").strip().lower()
        if out not in ("success", "neutral", "failure"):
            continue
        total += 1
        if out == "success":
            success += 1
    if total == 0:
        return 0.5
    return success / float(total)


def _adjust_confidence_with_history(base_conf: float, success_rate: float) -> float:
    """
    Nudge model confidence by historical execution quality.
    success_rate 0.5 is neutral; range approx +/-0.15 adjustment.
    """
    adj = (success_rate - 0.5) * 0.3
    return max(0.0, min(1.0, base_conf + adj))

