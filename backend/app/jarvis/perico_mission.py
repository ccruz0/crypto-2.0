"""Perico: Jarvis software specialist missions (explicit /perico), same platform as Jarvis."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.jarvis.perico_tools import perico_repo_root

# Machine-readable prefix; must not be stripped before analytics / Google Ads merge guards.
PERICO_AGENT_MARKER = "[AGENT:PERICO_SOFTWARE]"

# Phase 1 default: this monorepo (tests, Telegram/Jarvis integration live here).
PERICO_DEFAULT_TARGET_PROJECT = "crypto-2.0"


def _format_validation_command(pytest_rows: list[dict[str, Any]]) -> str:
    """Human-readable command line from the last perico_run_pytest result (or params fallback)."""
    if not pytest_rows:
        return ""
    row = pytest_rows[-1]
    res = row.get("result") if isinstance(row.get("result"), dict) else {}
    cmd = res.get("cmd")
    if isinstance(cmd, list) and cmd:
        return " ".join(str(x) for x in cmd)[:2000]
    params = dict(row.get("params") or {}) if isinstance(row.get("params"), dict) else {}
    parts = ["python3", "-m", "pytest", "-q", "--tb=no"]
    rel = str(params.get("relative_path") or "").strip()
    if rel:
        parts.append(rel)
    extra = str(params.get("extra_args") or "").strip()
    if extra:
        parts.extend(extra.split())
    return " ".join(parts)[:2000]


def _collect_suspected_files(executed: list[dict[str, Any]]) -> list[str]:
    """
    Minimal safe hints: grep hit paths, explicit read targets, patch targets.

    Paths are repo-relative strings when possible; capped and deduped.
    """
    root = perico_repo_root()
    seen: set[str] = set()
    out: list[str] = []

    def add(raw: str) -> None:
        p = (raw or "").strip().replace("\\", "/")
        if not p or ".." in p.split("/"):
            return
        if p.startswith("/"):
            try:
                p = str(Path(p).resolve().relative_to(root))
            except Exception:
                p = Path(p).name
        if p not in seen:
            seen.add(p)
            out.append(p)

    for row in executed:
        at = str(row.get("action_type") or "").strip().lower()
        res = row.get("result") if isinstance(row.get("result"), dict) else {}
        params = dict(row.get("params") or {}) if isinstance(row.get("params"), dict) else {}
        if at != "perico_repo_read" or not res.get("ok"):
            continue
        op = str(res.get("operation") or "").strip().lower()
        if op == "grep":
            for m in (res.get("matches") or [])[:35]:
                if isinstance(m, dict):
                    add(str(m.get("path") or ""))
        elif op == "read":
            rp = str(params.get("relative_path") or "").strip()
            if rp:
                add(rp)
            else:
                full = str(res.get("path") or "").strip()
                if full:
                    try:
                        add(str(Path(full).resolve().relative_to(root)))
                    except Exception:
                        add(Path(full).name)
        elif op == "list":
            rp = str(params.get("relative_path") or "").strip()
            if rp and rp not in (".", ""):
                add(rp.rstrip("/") + "/")

    for row in executed:
        at = str(row.get("action_type") or "").strip().lower()
        if at != "perico_apply_patch":
            continue
        res = row.get("result") if isinstance(row.get("result"), dict) else {}
        params = dict(row.get("params") or {}) if isinstance(row.get("params"), dict) else {}
        rp = str(res.get("relative_path") or params.get("relative_path") or "").strip()
        if rp:
            add(rp)

    return out[:25]


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
        "Registered Perico tools (use these exact action_type strings with auto_execute):\n"
        "- perico_repo_read — params: operation=list|read|grep, relative_path (repo-relative), "
        "pattern (grep only), max_results.\n"
        "- perico_apply_patch — params: relative_path, old_text, new_text; host must set PERICO_WRITE_ENABLED=1.\n"
        "- perico_run_pytest — params: relative_path (optional tests path under backend/), extra_args, timeout_seconds.\n\n"
        "Operator software task:\n"
        f"{raw}"
    )


def build_perico_deliverables_snapshot(
    *,
    mission_prompt: str,
    plan: dict[str, Any] | None,
    execution: dict[str, Any] | None,
    goal_satisfied: bool | None,
    retry_attempted: bool = False,
) -> dict[str, Any]:
    """
    Structured view for Notion / logs (phase 1; derived from execution rows).
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
        str(x.get("action_type") or "").strip().lower() == "perico_apply_patch"
        and isinstance(x.get("result"), dict)
        and bool((x.get("result") or {}).get("ok"))
        for x in executed
    ) or any(
        w in _row_text(x)
        for x in executed
        for w in ("patch", "write_file", "apply_patch", "edit_file", "git apply")
    )

    deploy_sensitive = any(
        w in _row_text(x)
        for x in executed
        for w in ("deploy", "production", "ssm_send", "kubectl", "terraform apply")
    )

    files_touched: list[str] = []
    diff_parts: list[str] = []
    errors_detected: list[str] = []
    pytest_rows: list[dict[str, Any]] = []
    for row in executed:
        at = str(row.get("action_type") or "").strip().lower()
        res = row.get("result") if isinstance(row.get("result"), dict) else {}
        if at == "perico_repo_read" and res.get("ok") and res.get("operation") == "read" and res.get("path"):
            files_touched.append(str(res.get("path")))
        if at == "perico_apply_patch" and res.get("ok"):
            rp = str(res.get("relative_path") or "").strip()
            if rp:
                files_touched.append(rp)
            dp = str(res.get("diff_preview") or "").strip()
            if dp:
                diff_parts.append(dp[:2000])
        if at == "perico_run_pytest":
            pytest_rows.append(row)
            if not res.get("ok") or res.get("tests_ok") is False:
                err = (res.get("stderr_tail") or res.get("stdout_tail") or res.get("error") or "").strip()
                if err:
                    errors_detected.append(err[:2500])

    tests_passed: bool | None = None
    validation_run = "unknown"
    if pytest_rows:
        last = pytest_rows[-1].get("result")
        if isinstance(last, dict) and last.get("pytest"):
            tests_passed = bool(last.get("tests_ok"))
            validation_run = "perico_run_pytest"
        else:
            validation_run = "perico_run_pytest_incomplete"

    suspected = _collect_suspected_files(executed)
    validation_command = _format_validation_command(pytest_rows)

    return {
        "target_project": target or PERICO_DEFAULT_TARGET_PROJECT,
        "task_type": task_type,
        "suspected_files": suspected,
        "files_touched": sorted(set(files_touched))[:40],
        "diff_summary": "\n---\n".join(diff_parts)[:8000] if diff_parts else "",
        "tests_passed": tests_passed,
        "errors_detected": errors_detected[:6],
        "retry_attempted": bool(retry_attempted),
        "patch_applied": patch_applied,
        "validation_run": validation_run,
        "validation_command": validation_command,
        "objective_satisfied": (bool(goal_satisfied) if goal_satisfied is not None else None),
        "deploy_sensitive": deploy_sensitive,
    }


def perico_try_auto_pytest_retry(execution: dict[str, Any]) -> list[dict[str, Any]]:
    """
    If a patch succeeded and a single pytest run failed, invoke pytest once more with the same params.

    Returns new pseudo-execution rows to append (empty if no retry).
    """
    from app.jarvis.executor import invoke_registered_tool, is_invoke_error_payload

    rows = [x for x in (execution.get("executed") or []) if isinstance(x, dict)]
    patch_ok = any(
        str(x.get("action_type") or "").strip().lower() == "perico_apply_patch"
        and isinstance(x.get("result"), dict)
        and bool((x.get("result") or {}).get("ok"))
        for x in rows
    )
    pytest_rows = [x for x in rows if str(x.get("action_type") or "").strip().lower() == "perico_run_pytest"]
    if not patch_ok or len(pytest_rows) != 1:
        return []
    r0 = pytest_rows[0]
    res0 = r0.get("result") if isinstance(r0.get("result"), dict) else {}
    if not res0.get("pytest") or res0.get("tests_ok"):
        return []
    params = dict(r0.get("params") or {})
    raw = invoke_registered_tool("perico_run_pytest", params, jarvis_run_id=None)
    if is_invoke_error_payload(raw) or not isinstance(raw, dict):
        synth = {
            "title": "Automatic pytest retry (Perico)",
            "action_type": "perico_run_pytest",
            "params": params,
            "execution_mode": "auto_execute",
            "priority_score": 50,
            "status": "failed",
            "result": raw if isinstance(raw, dict) else {"error": "non_dict_result"},
        }
        return [synth]
    synth = {
        "title": "Automatic pytest retry (Perico)",
        "action_type": "perico_run_pytest",
        "params": params,
        "execution_mode": "auto_execute",
        "priority_score": 50,
        "status": "executed" if raw.get("ok") and raw.get("tests_ok") else "failed",
        "result": raw,
    }
    return [synth]


def perico_should_block_for_operator_input(execution: dict[str, Any]) -> str | None:
    """
    Software completion gate: patch requires validation; repeated pytest failure needs operator.

    Returns a Spanish operator message or None to continue the pipeline.
    """
    rows = [x for x in (execution.get("executed") or []) if isinstance(x, dict)]
    patch_ok = any(
        str(x.get("action_type") or "").strip().lower() == "perico_apply_patch"
        and isinstance(x.get("result"), dict)
        and bool((x.get("result") or {}).get("ok"))
        for x in rows
    )
    pytest_rows = [x for x in rows if str(x.get("action_type") or "").strip().lower() == "perico_run_pytest"]
    if patch_ok and not pytest_rows:
        return (
            "Perico aplicó un parche pero no hay resultado de `perico_run_pytest`. "
            "Ejecuta tests (misma misión con una acción perico_run_pytest) o indica por qué no aplican."
        )
    if not pytest_rows:
        return None
    last = pytest_rows[-1].get("result")
    if not isinstance(last, dict) or not last.get("pytest"):
        return None
    if last.get("tests_ok"):
        return None
    if len(pytest_rows) >= 2:
        tail = str(last.get("stderr_tail") or last.get("combined_tail") or "")[:1200]
        return (
            "Tras un reintento automático, pytest sigue en rojo. "
            f"Revisa el error o ajusta el alcance.\n\nÚltima salida (truncada):\n{tail or '(sin detalle)'}"
        )
    return None
