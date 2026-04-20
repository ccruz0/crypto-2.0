"""Perico: Jarvis software specialist missions (explicit /perico), same platform as Jarvis."""

from __future__ import annotations

import re
from typing import Any

# Machine-readable prefix; must not be stripped before analytics / Google Ads merge guards.
PERICO_AGENT_MARKER = "[AGENT:PERICO_SOFTWARE]"

# Phase 1 default: this monorepo (tests, Telegram/Jarvis integration live here).
PERICO_DEFAULT_TARGET_PROJECT = "crypto-2.0"


def is_perico_marked_prompt(prompt: str) -> bool:
    return PERICO_AGENT_MARKER in (prompt or "")


def infer_perico_target_project(user_text: str) -> str | None:
    """
    Best-effort project hint from operator text. None if no signal (caller may default).
    """
    t = (user_text or "").strip()
    if not t:
        return None
    low = t.lower()
    if re.search(r"\batp\b", low):
        return "ATP"
    if "rahyang" in low:
        return "Rahyang"
    if "peluquer" in low or "peluqueria" in low or "barbershop" in low:
        return "Peluquería Cruz"
    if "crypto-2.0" in low or "crypto 2" in low:
        return "crypto-2.0"
    if "backend" in low and ("repo" in low or "código" in low or "codigo" in low):
        return "crypto-2.0"
    return None


def classify_perico_task_type(user_text: str) -> str:
    low = (user_text or "").lower()
    # Diagnostics before bugfix: phrases like "por qué falla" are investigation-first.
    if any(x in low for x in ("investiga", "investigar", "por qué", "why", "diagn")):
        return "diagnostics"
    if any(x in low for x in ("bug", "falla", "error", "fix", "arregla", "broken", "traceback")):
        return "bugfix"
    if any(x in low for x in ("test", "pytest", "unit test", "fallan los tests")):
        return "validation"
    if any(x in low for x in ("refactor", "limpiar", "cleanup")):
        return "refactor"
    return "general_software"


def build_perico_mission_prompt(*, user_text: str) -> str:
    """
    Wrap operator text for the shared autonomous pipeline.

    Keeps Jarvis as orchestrator; steers planner/executor away from marketing-only framing.
    """
    raw = (user_text or "").strip()
    hint = infer_perico_target_project(raw) or PERICO_DEFAULT_TARGET_PROJECT
    task_type = classify_perico_task_type(raw)
    return (
        f"{PERICO_AGENT_MARKER}\n"
        f"[PERICO_TARGET_PROJECT_HINT: {hint}]\n"
        f"[PERICO_TASK_TYPE: {task_type}]\n\n"
        "You are Perico, the software specialist inside the Jarvis autonomous mission system.\n"
        "Scope: repositories, code, tests, logs, integration fixes, small refactors, and safe validation.\n"
        "Out of scope unless the user explicitly asks: marketing analytics, GA4/GSC/Google Ads reporting as the primary goal, "
        "or broad business audits without a concrete engineering task.\n"
        "Never plan or execute automatic production deploy; if deploy is needed, stop for human approval.\n"
        "If the target repository or service is ambiguous, ask one concise clarification before heavy tool use.\n\n"
        "Follow this software loop when choosing tools and structuring work:\n"
        "1) Identify the target project/repo from the hint and user text.\n"
        "2) Inspect the smallest relevant files, tests, or logs.\n"
        "3) State a short hypothesis.\n"
        "4) Propose or apply a minimal patch only when justified.\n"
        "5) Run or request validation (tests/checks) when possible.\n"
        "6) Decide whether the stated engineering objective is satisfied; if not, retry safely once.\n"
        "7) If a step would be production- or deploy-sensitive, mark it as requiring explicit human approval.\n\n"
        "Operator software task:\n"
        f"{raw}"
    )


def build_perico_deliverables_snapshot(
    *,
    mission_prompt: str,
    plan: dict[str, Any] | None,
    execution: dict[str, Any] | None,
    goal_satisfied: bool | None,
) -> dict[str, Any]:
    """
    Minimal structured view for Notion / logs (phase 1; heuristic).

    ``suspected_files`` is reserved for future tool output; kept empty when unknown.
    """
    mp = (mission_prompt or "").strip()
    user_line = ""
    if "Operator software task:" in mp:
        user_line = mp.split("Operator software task:", 1)[-1].strip()
    else:
        user_line = mp
    hint_match = re.search(
        r"\[PERICO_TARGET_PROJECT_HINT:\s*([^\]]+)\]",
        mp,
    )
    target = (hint_match.group(1).strip() if hint_match else None) or infer_perico_target_project(user_line)
    tt_match = re.search(r"\[PERICO_TASK_TYPE:\s*([^\]]+)\]", mp)
    task_type = tt_match.group(1).strip() if tt_match else classify_perico_task_type(user_line)

    exec0 = execution if isinstance(execution, dict) else {}
    executed = [x for x in (exec0.get("executed") or []) if isinstance(x, dict)]
    def _row_text(x: dict[str, Any]) -> str:
        return " ".join(
            str(x.get(k) or "")
            for k in ("action_type", "title", "rationale")
        ).lower()

    patch_applied = any(
        w in _row_text(x)
        for x in executed
        for w in ("patch", "write_file", "apply_patch", "edit_file", "git apply")
    )

    deploy_sensitive = any(
        w in _row_text(x)
        for x in executed
        for w in ("deploy", "production", "ssm_send", "kubectl", "terraform apply")
    )

    validation_run = "unknown"
    for row in executed:
        r = row.get("result")
        if isinstance(r, dict) and (r.get("pytest") or r.get("tests_ok") is not None):
            validation_run = "pytest_signal_in_result"
            break
        at = str(row.get("action_type") or "").strip().lower()
        if "test" in at or "pytest" in at:
            validation_run = f"action:{at}"
            break

    return {
        "target_project": target or PERICO_DEFAULT_TARGET_PROJECT,
        "task_type": task_type,
        "suspected_files": [],
        "patch_applied": patch_applied,
        "validation_run": validation_run,
        "objective_satisfied": (bool(goal_satisfied) if goal_satisfied is not None else None),
        "deploy_sensitive": deploy_sensitive,
    }
