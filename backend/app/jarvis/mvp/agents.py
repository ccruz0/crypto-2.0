"""Agent nodes for Jarvis LangGraph MVP."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.jarvis.bedrock_client import ask_bedrock, extract_planner_json_object
from app.jarvis.mvp.aws_auditor import compile_audit_findings, is_aws_audit_task, run_aws_audit
from app.jarvis.mvp.crypto_auditor import (
    compile_crypto_audit_findings,
    is_crypto_audit_task,
    run_crypto_audit,
)
from app.jarvis.mvp.risk import classify_task_risk
from app.jarvis.mvp.tools import READONLY_TOOLS, run_readonly_tool
from app.jarvis.mvp.wallet_reconciliation import is_wallet_reconcile_task

logger = logging.getLogger(__name__)

_MODEL_COST_USD = 0.003
_TOOL_COST_USD = 0.001


def supervisor_agent(state: dict[str, Any]) -> dict[str, Any]:
    """Classify risk and gate high-risk tasks."""
    task = str(state.get("task") or "")
    risk_level = classify_task_risk(task)
    logger.info("jarvis.mvp.supervisor task_id=%s risk=%s", state.get("task_id"), risk_level)

    updates: dict[str, Any] = {
        "risk_level": risk_level,
        "model_calls": int(state.get("model_calls") or 0),
    }

    if risk_level == "high":
        updates.update(
            {
                "status": "requires_approval",
                "final_answer": (
                    "This task is classified as high risk and cannot execute automatically. "
                    "Human approval is required before any action."
                ),
                "plan": [],
                "tool_results": [],
                "review": {
                    "approved": False,
                    "flags": ["high_risk_blocked"],
                    "summary": "Execution blocked by supervisor due to high risk classification.",
                },
            }
        )
    return updates


def _fallback_plan(task: str) -> list[dict[str, Any]]:
    text = task.lower()
    steps: list[dict[str, Any]] = [
        {"step": 1, "action": "classify", "description": "Classify task intent and risk"},
    ]
    step = 2
    if is_crypto_audit_task(task):
        for audit_tool in (
            "get_exchange_wallet",
            "get_dashboard_portfolio",
            "get_open_positions",
            "get_portfolio_cache",
            "get_trade_history_summary",
            "get_price_feed_status",
        ):
            steps.append(
                {
                    "step": step,
                    "action": audit_tool,
                    "description": f"Crypto auditor: {audit_tool}",
                    "tool": audit_tool,
                    "args": {},
                }
            )
            step += 1
    elif is_wallet_reconcile_task(task):
        steps.append(
            {
                "step": step,
                "action": "reconcile_crypto_wallet_vs_dashboard",
                "description": "Compare Crypto.com wallet balances vs dashboard portfolio valuation",
                "tool": "reconcile_crypto_wallet_vs_dashboard",
                "args": {},
            }
        )
        step += 1
    elif any(k in text for k in ("health", "dashboard", "status")):
        steps.append(
            {
                "step": step,
                "action": "check_dashboard_health",
                "description": "Check dashboard/system health",
                "tool": "check_dashboard_health",
                "args": {},
            }
        )
        step += 1
    if "runtime" in text or "environment" in text:
        steps.append(
            {
                "step": step,
                "action": "get_runtime_status",
                "description": "Fetch runtime environment status",
                "tool": "get_runtime_status",
                "args": {},
            }
        )
        step += 1
    if is_aws_audit_task(task):
        for audit_tool in (
            "get_ec2_inventory",
            "get_ebs_inventory",
            "get_snapshot_inventory",
            "get_eip_inventory",
            "get_security_group_inventory",
            "get_cost_summary",
            "get_resource_tag_audit",
        ):
            steps.append(
                {
                    "step": step,
                    "action": audit_tool,
                    "description": f"AWS auditor: {audit_tool}",
                    "tool": audit_tool,
                    "args": {},
                }
            )
            step += 1
    elif "cost" in text or "aws" in text:
        steps.append(
            {
                "step": step,
                "action": "get_aws_cost_snapshot_stub",
                "description": "Fetch AWS cost snapshot (stub)",
                "tool": "get_aws_cost_snapshot_stub",
                "args": {},
            }
        )
        step += 1
    if "log" in text:
        steps.append(
            {
                "step": step,
                "action": "get_recent_logs_stub",
                "description": "Summarize recent logs (stub)",
                "tool": "get_recent_logs_stub",
                "args": {"lines": 20},
            }
        )
        step += 1
    if step == 2:
        steps.append(
            {
                "step": 2,
                "action": "get_runtime_status",
                "description": "Default read-only runtime status check",
                "tool": "get_runtime_status",
                "args": {},
            }
        )
    steps.append(
        {
            "step": step,
            "action": "summarize",
            "description": "Summarize findings for the operator",
        }
    )
    return steps


def planner_agent(state: dict[str, Any]) -> dict[str, Any]:
    """Produce a JSON execution plan using Bedrock with heuristic fallback."""
    task = str(state.get("task") or "")
    model_calls = int(state.get("model_calls") or 0) + 1

    prompt = (
        "You are the Jarvis Planner agent. Return ONLY a JSON object with key 'plan' "
        "whose value is a list of steps. Each step must include: step (int), action (str), "
        "description (str). For read-only work you MAY include tool (one of "
        f"{sorted(READONLY_TOOLS)}) and args (object). Task: {task}"
    )
    plan: list[dict[str, Any]] = []
    raw = ask_bedrock(prompt)
    parsed = extract_planner_json_object(raw) if raw else None
    if isinstance(parsed, dict) and isinstance(parsed.get("plan"), list):
        plan = [p for p in parsed["plan"] if isinstance(p, dict)]
    if not plan:
        plan = _fallback_plan(task)
        logger.info("jarvis.mvp.planner fallback task_id=%s steps=%d", state.get("task_id"), len(plan))

    return {"plan": plan, "model_calls": model_calls}


def aws_auditor_agent(state: dict[str, Any]) -> dict[str, Any]:
    """Run read-only AWS infrastructure audit and compile findings."""
    task_id = state.get("task_id")
    logger.info("jarvis.mvp.aws_auditor task_id=%s", task_id)

    tool_results, audit_output = run_aws_audit()
    tool_calls = int(state.get("tool_calls") or 0) + len(tool_results)

    return {
        "tool_results": tool_results,
        "tool_calls": tool_calls,
        "audit_output": audit_output,
    }


def crypto_auditor_agent(state: dict[str, Any]) -> dict[str, Any]:
    """Run read-only crypto portfolio audit and compile findings."""
    task_id = state.get("task_id")
    logger.info("jarvis.mvp.crypto_auditor task_id=%s", task_id)

    tool_results, audit_output = run_crypto_audit()
    tool_calls = int(state.get("tool_calls") or 0) + len(tool_results)

    return {
        "tool_results": tool_results,
        "tool_calls": tool_calls,
        "crypto_audit_output": audit_output,
    }


def executor_agent(state: dict[str, Any]) -> dict[str, Any]:
    """Run only approved read-only tools from the plan."""
    plan = state.get("plan") or []
    tool_results: list[dict[str, Any]] = []
    tool_calls = int(state.get("tool_calls") or 0)

    for step in plan:
        if not isinstance(step, dict):
            continue
        tool = str(step.get("tool") or "").strip()
        if not tool:
            continue
        args = step.get("args") if isinstance(step.get("args"), dict) else {}
        result = run_readonly_tool(tool, args)
        tool_results.append(result)
        tool_calls += 1
        logger.info(
            "jarvis.mvp.executor task_id=%s tool=%s success=%s",
            state.get("task_id"),
            tool,
            result.get("success"),
        )

    return {"tool_results": tool_results, "tool_calls": tool_calls}


def reviewer_agent(state: dict[str, Any]) -> dict[str, Any]:
    """Review execution output and flag issues."""
    tool_results = state.get("tool_results") or []
    flags: list[str] = []
    errors: list[str] = []

    for item in tool_results:
        if not isinstance(item, dict):
            continue
        if item.get("success") is False:
            flags.append("tool_error")
            if item.get("error"):
                errors.append(str(item["error"]))
        if item.get("note") and "stub" in str(item.get("note", "")).lower():
            flags.append("stub_data")

    if not tool_results:
        flags.append("no_tool_results")

    risk_level = str(state.get("risk_level") or "low")
    if risk_level == "medium":
        flags.append("medium_risk_task")

    approved = "tool_error" not in flags and risk_level != "high"
    summary_parts = []
    if errors:
        summary_parts.append(f"{len(errors)} tool error(s) detected.")
    elif tool_results:
        summary_parts.append(f"{len(tool_results)} read-only tool(s) executed.")
    else:
        summary_parts.append("No tools were executed; plan may be informational only.")

    review = {
        "approved": approved,
        "flags": sorted(set(flags)),
        "errors": errors,
        "summary": " ".join(summary_parts),
    }

    final_answer = _build_final_answer(state, review)
    status = "completed" if approved else "failed"

    model_calls = int(state.get("model_calls") or 0)
    audit_answer = _build_aws_audit_answer(state, tool_results)
    crypto_answer = _build_crypto_audit_answer(state, tool_results)
    reconcile_answer = _build_wallet_reconcile_answer(tool_results)
    if audit_answer:
        final_answer = audit_answer
    elif crypto_answer:
        final_answer = crypto_answer
    elif reconcile_answer:
        final_answer = reconcile_answer
    else:
        model_calls += 1
        prompt = (
            "You are the Jarvis Reviewer. Given task, plan, and tool results, write a concise "
            f"operator-facing answer in plain text (max 6 sentences).\n"
            f"Task: {state.get('task')}\n"
            f"Review: {json.dumps(review)}\n"
            f"Tool results: {json.dumps(tool_results)[:4000]}"
        )
        llm_answer = (ask_bedrock(prompt) or "").strip()
        if llm_answer:
            final_answer = llm_answer

    return {
        "review": review,
        "final_answer": final_answer,
        "status": status,
        "model_calls": model_calls,
    }


def _build_aws_audit_answer(state: dict[str, Any], tool_results: list[dict[str, Any]]) -> str | None:
    """Build a deterministic final answer from AWS audit output."""
    if not is_aws_audit_task(str(state.get("task") or "")):
        return None
    audit = state.get("audit_output")
    if not isinstance(audit, dict):
        audit = compile_audit_findings(tool_results)
    summary = audit.get("summary") or {}
    savings = audit.get("estimated_monthly_savings", 0)
    cost_n = len(audit.get("cost_findings") or [])
    sec_n = len(audit.get("security_findings") or [])
    res_n = len(audit.get("resource_findings") or [])
    recs = audit.get("recommendations") or []
    lines = [
        "AWS infrastructure audit complete (read-only).",
        f"Findings: {cost_n} cost, {sec_n} security, {res_n} resource.",
        f"Estimated monthly savings opportunity: ${savings:,.2f}.",
        f"Tools succeeded: {summary.get('tools_succeeded', 0)}/{summary.get('tools_executed', 0)}.",
    ]
    if recs:
        lines.append(f"Top recommendation: {recs[0]}")
    lines.append("No AWS resources were modified.")
    return " ".join(lines)


def _build_crypto_audit_answer(state: dict[str, Any], tool_results: list[dict[str, Any]]) -> str | None:
    """Build a deterministic final answer from crypto audit output."""
    if not is_crypto_audit_task(str(state.get("task") or "")):
        return None
    audit = state.get("crypto_audit_output")
    if not isinstance(audit, dict):
        audit = compile_crypto_audit_findings(tool_results)
    summary = audit.get("summary") or {}
    diff_usd = audit.get("portfolio_difference_usd", 0)
    diff_pct = audit.get("portfolio_difference_pct", 0)
    total = summary.get("total_findings", 0)
    status = summary.get("reconciliation_status", "unknown")
    recs = audit.get("recommendations") or []
    lines = [
        "Crypto portfolio audit complete (read-only).",
        f"Reconciliation status: {status}.",
        f"Findings: {total} total.",
        f"Portfolio difference: ${diff_usd:,.2f} ({diff_pct}%).",
        f"Exchange: ${summary.get('exchange_total_usd', 0):,.2f} | "
        f"Dashboard: ${summary.get('dashboard_total_usd', 0):,.2f}.",
    ]
    if recs:
        lines.append(f"Top recommendation: {recs[0]}")
    lines.append("No trades or balance modifications were executed.")
    return " ".join(lines)


def _build_wallet_reconcile_answer(tool_results: list[dict[str, Any]]) -> str | None:
    """Build a deterministic final answer from wallet reconciliation tool output."""
    for item in tool_results:
        if not isinstance(item, dict):
            continue
        if item.get("tool") != "reconcile_crypto_wallet_vs_dashboard":
            continue
        status = str(item.get("status") or "failed")
        crypto_total = item.get("crypto_com_total_usd")
        dashboard_total = item.get("dashboard_total_usd")
        diff = item.get("difference_usd")
        diff_pct = item.get("difference_pct")
        causes = item.get("probable_root_causes") or []
        steps = item.get("recommended_next_steps") or []
        top_assets = [
            a for a in (item.get("asset_comparison") or []) if a.get("issue") != "ok"
        ][:3]
        asset_lines = ", ".join(
            f"{a.get('coin')} ({a.get('issue')}, Δ${a.get('difference_usd')})" for a in top_assets
        )
        lines = [
            f"Wallet reconciliation status: {status}.",
            f"Crypto.com total: ${crypto_total:,.2f} | Dashboard total: ${dashboard_total:,.2f} | "
            f"Difference: ${diff:,.2f} ({diff_pct}%).",
        ]
        if asset_lines:
            lines.append(f"Top asset issues: {asset_lines}.")
        if causes:
            lines.append(f"Probable root cause: {causes[0]}")
        if steps:
            lines.append(f"Recommended next step: {steps[0]}")
        lines.append("Read-only diagnostic only — no trades or balance writes were executed.")
        return " ".join(lines)
    return None


def _build_final_answer(state: dict[str, Any], review: dict[str, Any]) -> str:
    task = str(state.get("task") or "")
    tool_results = state.get("tool_results") or []
    if review.get("errors"):
        return (
            f"Task '{task}' completed with errors. "
            f"Review flags: {', '.join(review.get('flags') or [])}."
        )
    if not tool_results:
        return (
            f"Task '{task}' was planned but no read-only tools ran. "
            f"{review.get('summary', '')}"
        )
    ok = sum(1 for t in tool_results if isinstance(t, dict) and t.get("success") is not False)
    return (
        f"Task '{task}' completed using {ok} read-only tool(s). "
        f"{review.get('summary', '')}"
    )


def cost_guard_agent(state: dict[str, Any]) -> dict[str, Any]:
    """Estimate model and tool usage cost."""
    model_calls = int(state.get("model_calls") or 0)
    tool_calls = int(state.get("tool_calls") or 0)
    estimated = round(model_calls * _MODEL_COST_USD + tool_calls * _TOOL_COST_USD, 4)
    logger.info(
        "jarvis.mvp.cost_guard task_id=%s model_calls=%d tool_calls=%d cost_usd=%s",
        state.get("task_id"),
        model_calls,
        tool_calls,
        estimated,
    )
    return {"estimated_cost_usd": estimated}
