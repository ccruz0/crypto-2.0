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


def _perico_executed_rows(execution: dict[str, Any] | None) -> list[dict[str, Any]]:
    ex = execution if isinstance(execution, dict) else {}
    return [x for x in (ex.get("executed") or []) if isinstance(x, dict)]


def perico_has_repo_inspection(executed: list[dict[str, Any]]) -> bool:
    """True when Perico actually inspected the repo (read, list, or grep with hits)."""
    for row in executed:
        if str(row.get("action_type") or "").strip().lower() != "perico_repo_read":
            continue
        res = row.get("result") if isinstance(row.get("result"), dict) else {}
        if not res.get("ok"):
            continue
        op = str(res.get("operation") or "").strip().lower()
        if op == "read":
            return True
        if op == "list":
            return True
        if op == "grep":
            matches = res.get("matches") or []
            if isinstance(matches, list) and any(isinstance(m, dict) and str(m.get("path") or "").strip() for m in matches):
                return True
    return False


def _perico_patch_attempted(executed: list[dict[str, Any]]) -> bool:
    return any(str(x.get("action_type") or "").strip().lower() == "perico_apply_patch" for x in executed)


def _perico_hypothesis_heuristic(*, plan: dict[str, Any] | None, executed: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    if isinstance(plan, dict):
        obj = str(plan.get("objective") or "").strip()
        if len(obj) > 12:
            parts.append(obj[:420])
    for row in executed:
        if str(row.get("action_type") or "").strip().lower() not in (
            "perico_repo_read",
            "perico_apply_patch",
            "perico_run_pytest",
        ):
            continue
        for key in ("rationale", "title"):
            chunk = str(row.get(key) or "").strip()
            if len(chunk) > 15:
                parts.append(chunk[:220])
        if len(parts) >= 3:
            break
    text = " | ".join(parts)[:900] if parts else ""
    return text or "(sin hipótesis textual explícita en acciones ejecutadas)"


def _perico_root_cause_heuristic(
    *,
    task_type: str,
    patch_applied: bool,
    tests_passed: bool | None,
    has_inspection: bool,
    errors_detected: list[str],
) -> str:
    if patch_applied and tests_passed is True:
        return "Parche aplicado y validación pytest en verde (alcance acotado al repo)."
    if patch_applied and tests_passed is False:
        tail = (errors_detected[0] if errors_detected else "")[:400]
        return (
            "Parche aplicado pero pytest sigue en rojo tras el intento de validación; "
            f"revisar salida. {tail}".strip()
        )
    if patch_applied and tests_passed is None:
        return "Parche aplicado; resultado de pytest incompleto o no registrado."
    if is_perico_bugfix_rubric_task(task_type) and has_inspection:
        return "Sin parche aplicado; inspección de repositorio realizada (cierre tipo diagnóstico / sin cambio de código)."
    if has_inspection:
        return "Inspección de repositorio realizada; sin parche aplicado en esta misión."
    return "Sin inspección clara del repo ni parche aplicado en el registro de ejecución."


def evaluate_perico_marked_goal_satisfaction(
    *, mission_prompt: str, execution: dict[str, Any] | None
) -> dict[str, Any]:
    """
    Strict objective check for bugfix/integration_fix Perico missions.

    Other Perico task types keep satisfied=True (no analytics-style rubric).
    """
    executed = _perico_executed_rows(execution)
    task_type = parse_perico_task_type_from_prompt(mission_prompt)
    if not is_perico_bugfix_rubric_task(task_type):
        return {
            "satisfied": True,
            "missing_items": [],
            "reason": "perico_no_bugfix_rubric",
            "auto_retry_recommended": False,
            "evaluator_domain": "perico_software",
        }

    patch_ok = any(
        str(x.get("action_type") or "").strip().lower() == "perico_apply_patch"
        and isinstance(x.get("result"), dict)
        and bool((x.get("result") or {}).get("ok"))
        for x in executed
    )
    pytest_rows = [x for x in executed if str(x.get("action_type") or "").strip().lower() == "perico_run_pytest"]
    inspected = perico_has_repo_inspection(executed)

    # Bugfix / integration_fix must *close* the loop: inspect → patch aplicado → pytest en verde.
    # No "solo diagnóstico" como objetivo cumplido para estos tipos.
    if not inspected:
        return {
            "satisfied": False,
            "missing_items": ["perico_bugfix_inspection_missing"],
            "reason": "perico_bugfix_rubric",
            "auto_retry_recommended": False,
            "evaluator_domain": "perico_bugfix",
        }
    if not patch_ok:
        return {
            "satisfied": False,
            "missing_items": ["perico_bugfix_patch_missing"],
            "reason": "perico_bugfix_rubric",
            "auto_retry_recommended": False,
            "evaluator_domain": "perico_bugfix",
        }
    if not pytest_rows:
        return {
            "satisfied": False,
            "missing_items": ["perico_bugfix_validation_missing"],
            "reason": "perico_bugfix_rubric",
            "auto_retry_recommended": False,
            "evaluator_domain": "perico_bugfix",
        }
    last = pytest_rows[-1].get("result") if isinstance(pytest_rows[-1].get("result"), dict) else {}
    if not last.get("pytest"):
        return {
            "satisfied": False,
            "missing_items": ["perico_bugfix_pytest_incomplete"],
            "reason": "perico_bugfix_rubric",
            "auto_retry_recommended": False,
            "evaluator_domain": "perico_bugfix",
        }
    if not last.get("tests_ok"):
        return {
            "satisfied": False,
            "missing_items": ["perico_bugfix_tests_failed"],
            "reason": "perico_bugfix_rubric",
            "auto_retry_recommended": False,
            "evaluator_domain": "perico_bugfix",
        }
    return {
        "satisfied": True,
        "missing_items": [],
        "reason": "perico_bugfix_rubric",
        "auto_retry_recommended": False,
        "evaluator_domain": "perico_bugfix",
    }


def is_perico_marked_prompt(prompt: str) -> bool:
    return PERICO_AGENT_MARKER in (prompt or "")


def is_perico_software_mission_prompt(prompt: str) -> bool:
    """
    True for Perico software missions, including when the ``[AGENT:PERICO_SOFTWARE]`` prefix
    was lost but the wrapped body remains.

    This prevents analytics heuristics (e.g. substring ``google ads``) from matching the
    static Perico instructions that mention marketing scope.
    """
    if is_perico_marked_prompt(prompt):
        return True
    low = (prompt or "").lower()
    if "operator software task:" not in low:
        return False
    return "registered perico tools" in low or "[perico_task_type:" in low


_PERICO_STRATEGY_CONCRETE_TOOLS: frozenset[str] = frozenset(
    {"perico_repo_read", "perico_apply_patch", "perico_run_pytest"}
)


def perico_should_skip_nonconcrete_strategy_action(action: dict[str, Any], *, mission_prompt: str) -> bool:
    """
    Skip planner rows that are too vague or non-actionable for Perico software missions.

    Used by ExecutionAgent so bugfix-style work prefers repo read / patch / pytest instead of
    placeholders like "prepare a potential fix".
    """
    if not is_perico_software_mission_prompt(mission_prompt):
        return False
    at = str(action.get("action_type") or "").strip().lower()
    if at in _PERICO_STRATEGY_CONCRETE_TOOLS:
        return False
    if at.startswith("diagnose_"):
        return False

    title = str(action.get("title") or "").strip().lower()
    rationale = str(action.get("rationale") or "").strip().lower()
    blob = f"{title} {rationale}".strip()

    vague_needles = (
        "prepare for potential",
        "prepare for",
        "prepare potential",
        "get ready to",
        "plan to run",
        "might want to",
        "could potentially",
        "consider potentially",
        "potential bugfix",
        "potential fix",
        "potential patch",
        "potential approach",
        "potential solution",
        "explore potentially",
    )
    if any(n in blob for n in vague_needles):
        return True
    if title.startswith("prepare ") or title.startswith("preparing "):
        return True
    if "potential" in title and any(
        w in title for w in ("fix", "patch", "change", "solution", "approach", "bug", "issue")
    ):
        return True

    task_type = parse_perico_task_type_from_prompt(mission_prompt)
    if is_perico_bugfix_rubric_task(task_type):
        params = action.get("params") if isinstance(action.get("params"), dict) else {}
        ot = str((params or {}).get("old_text") or "").strip()
        nt = str((params or {}).get("new_text") or "").strip()
        if at in ("code_change", "generic", "software_action", "edit_file", "write_file") and not (ot and nt):
            return True
    return False


def _perico_strategy_action_blob(action: dict[str, Any]) -> str:
    params = action.get("params") if isinstance(action.get("params"), dict) else {}
    return f"{action.get('title', '')} {action.get('rationale', '')} {action.get('action_type', '')} {params}".lower()


def _perico_blob_sensitive_ops(blob: str) -> bool:
    return any(
        x in blob
        for x in (
            "ssm",
            "secret",
            "credential",
            "password",
            "production",
            " deploy",
            "deploy ",
            "kubectl",
            "terraform",
            "restart",
        )
    )


def _perico_blob_blocks_readlike_mapping(blob: str) -> bool:
    """
    True when text suggests mutating infra/config — do not map to perico_repo_read
    or downgrade ``ops_config_change`` to auto_execute.
    """
    if _perico_blob_sensitive_ops(blob):
        return True
    low = blob
    needles = (
        "write ",
        " write",
        "update ",
        " update",
        "replace ",
        " replace",
        "delete ",
        " delete",
        "rotate ",
        " rotate",
        "set env",
        "set ssm",
        "set secret",
        "set credential",
        "set credentials",
        "mutate",
        "patch prod",
        "apply to prod",
        "overwrite",
        "truncate",
    )
    return any(n in low for n in needles)


def _perico_blob_requests_pytest(blob: str) -> bool:
    # Avoid treating "pytest.ini" / config reads as a test *run*.
    scrubbed = (
        blob.replace("pytest.ini", " ")
        .replace("pyproject.toml", " ")
        .replace("conftest.py", " ")
    )
    if "pytest" in scrubbed:
        return True
    return any(
        x in blob
        for x in (
            "run tests",
            "run test",
            "correr test",
            "ejecutar test",
            "full test suite",
            "test suite",
            "unit tests",
        )
    )


def _perico_infer_pytest_relative_path(blob: str, params: dict[str, Any]) -> str:
    for key in ("relative_path", "path", "tests_path", "target", "test_path"):
        v = str(params.get(key) or "").strip().replace("\\", "/")
        if v and ".." not in v.split("/"):
            return v
    if "backend/test" in blob:
        return "tests"
    return ""


def _perico_ops_config_maps_to_repo_read(at: str, blob: str) -> bool:
    if at != "ops_config_change":
        return False
    if _perico_blob_blocks_readlike_mapping(blob):
        return False
    return any(
        x in blob
        for x in (
            "read ",
            "inspect",
            "review ",
            "leer",
            "pytest.ini",
            "conftest",
            "test configuration",
            "config file",
            "list file",
            "open file",
        )
    ) or ("test" in blob and "config" in blob)


def _perico_analysis_codechange_maps_to_repo_read(at: str, blob: str) -> bool:
    if at not in ("analysis", "research", "code_change"):
        return False
    if _perico_blob_blocks_readlike_mapping(blob) or _perico_blob_requests_pytest(blob):
        return False
    return any(
        x in blob
        for x in (
            "read ",
            "inspect",
            "review ",
            "leer",
            "list ",
            "browse",
            "open ",
            "pytest.ini",
            "conftest",
            "source file",
            "codebase",
            "repository",
            "repo ",
        )
    )


def _perico_infer_repo_read_triple(_at: str, blob: str, params: dict[str, Any]) -> tuple[str, str, str]:
    rp = str(params.get("relative_path") or params.get("path") or params.get("file") or "").strip().replace("\\", "/")
    pat = str(params.get("pattern") or params.get("query") or "").strip()
    if "pytest.ini" in blob:
        return "read", "pytest.ini", ""
    if "conftest.py" in blob or ("conftest" in blob and "pytest" in blob):
        if rp:
            return "read", rp, ""
        return "read", "backend/tests/conftest.py", ""
    if "pyproject.toml" in blob:
        return "read", "pyproject.toml", ""
    if rp and pat and len(pat) >= 2:
        return "grep", rp, pat[:200]
    if rp:
        return "read", rp, ""
    if "list" in blob and "test" in blob:
        return "list", "backend/tests", ""
    return "list", "backend", ""


def normalize_perico_strategy_actions(
    actions: list[dict[str, Any]],
    *,
    mission_prompt: str,
) -> list[dict[str, Any]]:
    """
    Rewrite generic strategist rows into registered Perico tools so ExecutionAgent invokes them.

    Paths stay repo-relative under ``PERICO_REPO_ROOT`` (enforced again inside tools).
    """
    if not is_perico_software_mission_prompt(mission_prompt):
        return list(actions)
    from app.jarvis.action_policy import compute_priority_score, get_action_policy

    out: list[dict[str, Any]] = []
    for a0 in actions:
        if not isinstance(a0, dict):
            continue
        a = dict(a0)
        at = str(a.get("action_type") or "").strip().lower()
        blob = _perico_strategy_action_blob(a)
        params = dict(a.get("params") or {}) if isinstance(a.get("params"), dict) else {}

        if at in _PERICO_STRATEGY_CONCRETE_TOOLS:
            pol = get_action_policy(at)
            a["execution_mode"] = str(pol.get("execution_mode") or "auto_execute")
            a["requires_approval"] = a["execution_mode"] == "requires_approval"
            out.append(a)
            continue

        mapped: dict[str, Any] | None = None

        if at == "code_change":
            ot = str(params.get("old_text") or "").strip()
            nt = str(params.get("new_text") or "")
            rp = str(params.get("relative_path") or params.get("path") or "").strip().replace("\\", "/")
            if rp and ot:
                mapped = {k: v for k, v in a.items() if k not in ("action_type", "params")}
                mapped["action_type"] = "perico_apply_patch"
                mapped["params"] = {"relative_path": rp, "old_text": ot, "new_text": nt}

        if mapped is None and (
            _perico_ops_config_maps_to_repo_read(at, blob)
            or _perico_analysis_codechange_maps_to_repo_read(at, blob)
        ):
            op, rel, pat = _perico_infer_repo_read_triple(at, blob, params)
            mapped = {k: v for k, v in a.items() if k not in ("action_type", "params")}
            mapped["action_type"] = "perico_repo_read"
            mapped["params"] = {
                "operation": op,
                "relative_path": rel,
                "pattern": pat,
                "max_results": int(params.get("max_results") or 80),
            }

        if mapped is None and _perico_blob_requests_pytest(blob):
            mapped = {k: v for k, v in a.items() if k not in ("action_type", "params")}
            mapped["action_type"] = "perico_run_pytest"
            mapped["params"] = {
                "relative_path": _perico_infer_pytest_relative_path(blob, params),
                "extra_args": str(params.get("extra_args") or ""),
                "timeout_seconds": int(params.get("timeout_seconds") or 180),
            }

        if mapped is not None:
            pol = get_action_policy(str(mapped["action_type"]))
            mapped["execution_mode"] = str(pol.get("execution_mode") or "auto_execute")
            mapped["requires_approval"] = mapped["execution_mode"] == "requires_approval"
            if not mapped.get("priority_score"):
                mapped["priority_score"] = compute_priority_score(
                    action_type=str(mapped["action_type"]),
                    impact=str(a.get("impact") or "high"),
                    confidence=float(a.get("confidence") or 0.78),
                )
            if not str(mapped.get("title") or "").strip():
                mapped["title"] = str(mapped["action_type"])
            out.append(mapped)
            continue

        if at == "ops_config_change" and not _perico_blob_blocks_readlike_mapping(blob):
            if any(x in blob for x in ("read", "inspect", "review", "leer", "pytest", "test", "config", "file")):
                a["execution_mode"] = "auto_execute"
                a["requires_approval"] = False
        out.append(a)
    return out


def parse_perico_task_type_from_prompt(mission_prompt: str) -> str:
    """Task type from [PERICO_TASK_TYPE: …] marker; falls back to classifying operator line."""
    mp = (mission_prompt or "").strip()
    m = re.search(r"\[PERICO_TASK_TYPE:\s*([^\]]+)\]", mp)
    if m:
        return m.group(1).strip()
    user_line = ""
    if "Operator software task:" in mp:
        user_line = mp.split("Operator software task:", 1)[-1].strip()
    else:
        user_line = mp
    return classify_perico_task_type(user_line)


def is_perico_bugfix_rubric_task(task_type: str) -> bool:
    """Strict software-done rubric (inspection + validation when patching)."""
    t = (task_type or "").strip().lower()
    return t in ("bugfix", "integration_fix")


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


def _perico_wants_bugfix_closure(low: str) -> bool:
    """
    True when the operator asks to fix + validate (patch/pytest), not investigation-only.

    Must run *before* the diagnostics shortcut so phrases like "Investiga la causa" do not
    alone force ``diagnostics`` when the user also asks for a patch and pytest.
    """
    has_tests = any(
        w in low for w in ("test", "tests", "pytest", "unit test", "pruebas", "prueba")
    )
    has_patch = any(
        w in low
        for w in (
            "parche",
            "patch",
            "aplica un parche",
            "apply patch",
            "cambio mínimo",
            "cambio minimo",
            "minimal patch",
        )
    )
    has_pytest_cmd = any(
        w in low for w in ("pytest", "ejecuta pytest", "corre pytest", "run pytest")
    )
    has_validate = any(w in low for w in ("validar", "validate", "validación", "validacion"))
    has_problem = any(
        w in low
        for w in (
            "hay un problema",
            "there is a problem",
            "están fallando",
            "estan fallando",
            "fallan",
            "fallando",
            "failing",
            "broken",
        )
    )
    has_fix = any(
        w in low
        for w in (
            "arregla",
            "fix",
            "corrige",
            "corregir",
            "soluciona",
            "resolve",
            "bug",
            "error",
            "fallo",
            "falla",
        )
    )
    if has_patch and (has_pytest_cmd or has_validate or has_tests):
        return True
    if has_tests and has_problem and (has_fix or has_patch or has_pytest_cmd or has_validate):
        return True
    if any(w in low for w in ("investiga", "investigar")) and has_patch and (
        has_pytest_cmd or has_validate or has_tests
    ):
        return True
    return False


def classify_perico_task_type(user_text: str) -> str:
    low = (user_text or "").lower()
    integ = any(
        x in low
        for x in (
            "integración",
            "integracion",
            "integration",
            "webhook",
            "endpoint",
        )
    )
    if integ and any(
        x in low
        for x in (
            "bug",
            "falla",
            "error",
            "fix",
            "arregla",
            "broken",
            "traceback",
            "no envía",
            "no envia",
            "no llega",
            "fallo",
        )
    ):
        return "integration_fix"
    if _perico_wants_bugfix_closure(low):
        return "integration_fix" if integ else "bugfix"
    # Tests failing + concrete fix/validate language → bugfix, even if the prompt opens with "Investiga…".
    # (Otherwise "Investiga la causa…" can match diagnostics before the stricter bugfix heuristics fire.)
    if any(x in low for x in ("test", "tests", "pytest", "pruebas", "prueba")) and any(
        x in low for x in ("fallan", "fallando", "failing", "falla", "error", "problema", "broken")
    ) and any(
        x in low
        for x in (
            "parche",
            "patch",
            "pytest",
            "validar",
            "validate",
            "validación",
            "validacion",
            "arregla",
            "fix",
            "corrige",
            "aplica",
        )
    ):
        return "integration_fix" if integ else "bugfix"
    # Investigation-only (no explicit patch/pytest validation loop in the ask).
    if any(x in low for x in ("investiga", "investigar", "por qué", "por que", "why", "diagn")):
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
    bugfix_rubric = is_perico_bugfix_rubric_task(task_type)
    bugfix_extra = ""
    if bugfix_rubric:
        bugfix_extra = (
            "\nBugfix / integration-fix closure (this task type is strictly validated):\n"
            "- State a short hypothesis before patching; after changes, summarize root cause vs symptom.\n"
            "- If you change code: apply a minimal patch, then run perico_run_pytest until green or stop after one safe retry path.\n"
            "- If you do not change code: still inspect the repo (read/grep) and explain why no patch is justified.\n"
        )
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
        "7) If a step would be production- or deploy-sensitive, mark it as requiring explicit human approval.\n"
        f"{bugfix_extra}"
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
    has_inspection = perico_has_repo_inspection(executed)
    fix_attempted = _perico_patch_attempted(executed)
    hypothesis_summary = _perico_hypothesis_heuristic(plan=plan, executed=executed)
    root_cause_summary = _perico_root_cause_heuristic(
        task_type=task_type,
        patch_applied=patch_applied,
        tests_passed=tests_passed,
        has_inspection=has_inspection,
        errors_detected=errors_detected,
    )
    if not pytest_rows:
        validation_result_summary = "pytest no ejecutado en esta misión"
    elif validation_run == "perico_run_pytest_incomplete":
        validation_result_summary = "pytest lanzado pero el resultado quedó incompleto"
    elif tests_passed is True:
        validation_result_summary = "pytest (última pasada): OK"
    elif tests_passed is False:
        validation_result_summary = "pytest (última pasada): falló"
    else:
        validation_result_summary = "pytest: estado desconocido"

    retry_reason = ""
    if retry_attempted:
        last_res = pytest_rows[-1].get("result") if pytest_rows else {}
        if isinstance(last_res, dict) and last_res.get("retry_reason"):
            retry_reason = str(last_res["retry_reason"])[:500]
        else:
            retry_reason = "Reintento automático de pytest tras el primer fallo (mismos parámetros)."

    software_closure_state: str | None = None
    if is_perico_bugfix_rubric_task(task_type):
        gate = perico_should_block_for_operator_input(exec0)
        if gate:
            software_closure_state = "blocked"
        elif patch_applied:
            if tests_passed is True:
                software_closure_state = "fixed"
            elif tests_passed is False:
                software_closure_state = "blocked"
            else:
                software_closure_state = "partially_fixed"
        elif has_inspection:
            # Bugfix sin parche aplicado nunca es "fixed" (coherente con evaluate_perico_marked_goal_satisfaction).
            software_closure_state = "blocked"
        else:
            software_closure_state = "blocked"
        if software_closure_state not in {"fixed", "partially_fixed", "blocked"}:
            raise RuntimeError(
                f"Invalid Perico bugfix software_closure_state: {software_closure_state!r}"
            )

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
        "bugfix_rubric": is_perico_bugfix_rubric_task(task_type),
        "root_cause_summary": root_cause_summary[:1200],
        "hypothesis_summary": hypothesis_summary[:1200],
        "fix_attempted": fix_attempted,
        "validation_result_summary": validation_result_summary[:500],
        "retry_reason": retry_reason[:600] if retry_reason else "",
        "software_closure_state": software_closure_state,
    }


def _pytest_numeric_stats_from_execution(execution: dict[str, Any] | None) -> tuple[int | None, int | None]:
    """tests_total / tests_failed from the last perico_run_pytest row (if present)."""
    ex = execution if isinstance(execution, dict) else {}
    rows = [x for x in (ex.get("executed") or []) if isinstance(x, dict)]
    pytest_rows = [x for x in rows if str(x.get("action_type") or "").strip().lower() == "perico_run_pytest"]
    if not pytest_rows:
        return None, None
    last = pytest_rows[-1].get("result")
    if not isinstance(last, dict):
        return None, None
    tt_raw, tf_raw = last.get("tests_total"), last.get("tests_failed")
    try:
        tt_i = int(tt_raw) if tt_raw is not None else None
    except (TypeError, ValueError):
        tt_i = None
    try:
        tf_i = int(tf_raw) if tf_raw is not None else None
    except (TypeError, ValueError):
        tf_i = None
    return tt_i, tf_i


def format_perico_closure_status_display(snap: dict[str, Any]) -> str:
    """
    Token for Estado: in Notion [EXEC_SUMMARY] and Telegram (bugfix-style closure).

    Returns "" when ``software_closure_state`` is absent; caller may use "Completada".
    """
    cs = snap.get("software_closure_state")
    if not cs:
        return ""
    key = str(cs).strip().lower()
    return {
        "fixed": "FIXED",
        "partially_fixed": "PARTIALLY_FIXED",
        "blocked": "BLOCKED",
    }.get(key, key.upper())


def format_perico_closure_key_result(snap: dict[str, Any], execution: dict[str, Any] | None) -> str:
    """
    Resultado clave derived from ``software_closure_state`` and pytest stats — not generic review copy.
    """
    cs_raw = snap.get("software_closure_state")
    cs = str(cs_raw).strip().lower() if cs_raw else ""
    vrs = (snap.get("validation_result_summary") or "").strip()
    tt, tf = _pytest_numeric_stats_from_execution(execution)
    count_suffix = ""
    if tt is not None and tf is not None:
        count_suffix = f" ({int(tf)} fallidos de {int(tt)} tests)"
    elif tt is not None:
        count_suffix = f" ({int(tt)} tests en total)"

    if cs == "fixed":
        return f"Tests en verde. El problema está resuelto.{count_suffix}"[:900]
    if cs == "partially_fixed":
        msg = (
            "El problema está parcialmente resuelto: pytest no cerró con un resultado claro "
            "(revisar salida o reintentar validación)."
        )
        if vrs:
            msg = f"{msg} {vrs}"
        return msg[:900]
    if cs == "blocked":
        base = "No se pudo cerrar el objetivo con la validación actual."
        if vrs:
            base = f"{base} {vrs}"
        return (base + count_suffix)[:900]
    if vrs:
        return vrs[:900]
    return "Misión Perico completada; el detalle técnico queda en Notion."[:900]


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
    rr = "Reintento automático de pytest tras el primer fallo (mismos parámetros)."
    if is_invoke_error_payload(raw) or not isinstance(raw, dict):
        base = dict(raw) if isinstance(raw, dict) else {"error": "non_dict_result"}
        base["retry_reason"] = rr
        synth = {
            "title": "Automatic pytest retry (Perico)",
            "action_type": "perico_run_pytest",
            "params": params,
            "execution_mode": "auto_execute",
            "priority_score": 50,
            "status": "failed",
            "result": base,
        }
        return [synth]
    merged = dict(raw)
    merged["retry_reason"] = rr
    synth = {
        "title": "Automatic pytest retry (Perico)",
        "action_type": "perico_run_pytest",
        "params": params,
        "execution_mode": "auto_execute",
        "priority_score": 50,
        "status": "executed" if raw.get("ok") and raw.get("tests_ok") else "failed",
        "result": merged,
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
