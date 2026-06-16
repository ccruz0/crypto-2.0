"""Supervisor result-quality validation before task completion."""

from __future__ import annotations

import re
from typing import Any, Literal

TaskType = Literal["investigation", "numeric", "patch", "remediation", "operational"]

_INVESTIGATION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bwhy\b",
        r"\broot\s+cause\b",
        r"\binvestigate\b",
        r"\bdiagnos",
        r"\bexplain\s+why\b",
        r"\bwhat\s+caused\b",
        r"\bwhat\s+is\s+causing\b",
    )
)

_NUMERIC_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bcount\b",
        r"\bhow\s+many\b",
        r"\bnumber\s+of\b",
        r"\btotal\s+(?:open\s+)?(?:orders|positions|users)\b",
    )
)

_PATCH_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bpatch\b",
        r"\bcreate\s+a?\s*patch\b",
        r"\bgenerate\s+patch\b",
        r"\bimplement\s+change\b",
        r"\bfix\s+(?:the\s+)?bug\b",
    )
)

_REMEDIATION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bsolve\b",
        r"\bfix\b",
        r"\brepair\b",
        r"\bcorrect\b",
    )
)

_EMPTY_VALUES = frozenset({"", "none", "null", "n/a", "not determined", "unknown"})

# Output keys that alone do not constitute useful evidence.
_META_ONLY_KEYS = frozenset(
    {
        "ok",
        "status",
        "read_only",
        "checked_at",
        "duration_ms",
        "tool",
        "action",
        "step_id",
        "error",
    }
)

_GENERIC_ROOT_CAUSE_PHRASES = frozenset(
    {
        "unknown",
        "not determined",
        "unable to determine",
        "could not determine",
        "insufficient data",
        "needs further investigation",
        "requires further investigation",
        "no root cause found",
        "n/a",
    }
)

_NUMERIC_VALUE_RE = re.compile(
    r"(?:\bcount\b|\btotal\b|\bresult\b|\banswer\b)\s*[:=]?\s*(\d+)\b|\b(\d+)\s+(?:open\s+)?(?:orders|positions|users)\b",
    re.IGNORECASE,
)


def classify_task_type(objective: str) -> TaskType:
    """Classify objective into a validation profile (first match wins)."""
    text = (objective or "").strip()
    if not text:
        return "operational"
    if any(p.search(text) for p in _PATCH_PATTERNS):
        return "patch"
    if any(p.search(text) for p in _NUMERIC_PATTERNS):
        return "numeric"
    if any(p.search(text) for p in _INVESTIGATION_PATTERNS):
        return "investigation"
    if any(p.search(text) for p in _REMEDIATION_PATTERNS):
        return "remediation"
    return "operational"


def _is_present(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    if not text:
        return False
    return text.lower() not in _EMPTY_VALUES


def _is_meaningful_root_cause(value: Any) -> bool:
    if not _is_present(value):
        return False
    text = str(value).strip().lower()
    if text in _GENERIC_ROOT_CAUSE_PHRASES:
        return False
    # Require substantive causal explanation (not a bare status label).
    if len(text) < 12:
        return False
    return True


def _output_has_useful_data(output: dict[str, Any]) -> bool:
    if not output:
        return False
    if output.get("evidence"):
        return True
    if output.get("query_executed") and output.get("row_count", 0) > 0:
        return True
    if output.get("matches"):
        return bool(output["matches"])
    if output.get("match_count", 0) > 0:
        return True
    for key, value in output.items():
        if key in _META_ONLY_KEYS:
            continue
        if _is_present(value):
            return True
    return False


def _artifact_has_useful_content(art: dict[str, Any]) -> bool:
    content = art.get("content")
    if isinstance(content, dict) and _output_has_useful_data(content):
        return True
    if art.get("format") == "image" and art.get("size_bytes", 0) > 0:
        return True
    preview = art.get("preview") or art.get("name")
    if _is_present(preview) and str(preview).strip() not in {"plan_preview", "repository_investigation"}:
        return True
    return False


def _tool_output(tool_results: list[dict[str, Any]], action: str) -> dict[str, Any]:
    for entry in tool_results:
        if str(entry.get("action") or "").lower() == action.lower():
            output = entry.get("output")
            return output if isinstance(output, dict) else {}
    return {}


def _tool_output_by_name(tool_results: list[dict[str, Any]], tool: str) -> dict[str, Any]:
    for entry in tool_results:
        if str(entry.get("tool") or "").lower() == tool.lower():
            output = entry.get("output")
            return output if isinstance(output, dict) else {}
    return {}


def _format_structured_evidence(items: list[Any]) -> str | None:
    parts: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        source = item.get("source", "?")
        reference = item.get("reference", "?")
        detail = item.get("detail", "")
        confidence = item.get("confidence", "medium")
        if _is_present(detail):
            parts.append(f"[{source}|{reference}|{confidence}] {detail[:300]}")
    return "\n".join(parts) if parts else None


def extract_structured_evidence(
    *,
    tool_results: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    """Collect structured evidence items from diagnostic tool outputs."""
    items: list[dict[str, str]] = []
    for entry in tool_results or []:
        if not entry.get("ok", True):
            continue
        output = entry.get("output")
        if not isinstance(output, dict):
            continue
        structured = output.get("evidence")
        if isinstance(structured, list):
            for row in structured:
                if isinstance(row, dict) and _is_present(row.get("detail")):
                    items.append(
                        {
                            "source": str(row.get("source", "unknown")),
                            "reference": str(row.get("reference", "")),
                            "detail": str(row.get("detail", ""))[:800],
                            "confidence": str(row.get("confidence", "medium")),
                        }
                    )
        elif output.get("query_executed"):
            items.append(
                {
                    "source": "database",
                    "reference": output.get("preset") or "query",
                    "detail": f"{output.get('query_executed', '')} -> row_count={output.get('row_count', 0)}",
                    "confidence": "high" if output.get("ok") else "low",
                }
            )
        elif output.get("matches"):
            for match in (output.get("matches") or [])[:3]:
                if isinstance(match, dict):
                    items.append(
                        {
                            "source": "repository",
                            "reference": str(match.get("path", "")),
                            "detail": str(match.get("text", ""))[:300],
                            "confidence": str(match.get("confidence", "medium")),
                        }
                    )
        elif output.get("match_count") is not None and output.get("matches") is not None:
            for match in (output.get("matches") or [])[:3]:
                if isinstance(match, dict):
                    items.append(
                        {
                            "source": "logs",
                            "reference": str(match.get("source", "")),
                            "detail": str(match.get("message", ""))[:300],
                            "confidence": "medium",
                        }
                    )
    return items


def extract_root_cause(
    *,
    tool_results: list[dict[str, Any]] | None = None,
    repo_investigation: dict[str, Any] | None = None,
    completion_report: dict[str, Any] | None = None,
) -> str | None:
    """Extract root cause from structured agent outputs."""
    for action in ("identify_root_cause", "analyze_failure"):
        output = _tool_output(tool_results or [], action)
        for key in ("root_cause", "probable_root_cause", "cause"):
            if _is_meaningful_root_cause(output.get(key)):
                return str(output[key]).strip()

    for tool_name in ("diagnose_open_orders",):
        output = _tool_output_by_name(tool_results or [], tool_name)
        if not output:
            output = _tool_output(tool_results or [], tool_name)
        if _is_meaningful_root_cause(output.get("root_cause")):
            return str(output["root_cause"]).strip()

    repo = repo_investigation or {}
    for key in ("root_cause", "root_cause_summary", "probable_root_causes"):
        value = repo.get(key)
        if isinstance(value, list):
            parts = [str(v).strip() for v in value if _is_present(v)]
            if parts:
                return "; ".join(parts)
        elif _is_present(value):
            return str(value).strip()

    report = completion_report or {}
    if _is_present(report.get("conclusion")) and classify_task_type("") != "investigation":
        return str(report["conclusion"]).strip()
    return None


def extract_evidence(
    *,
    tool_results: list[dict[str, Any]] | None = None,
    repo_investigation: dict[str, Any] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
) -> str | None:
    """Collect non-empty evidence from tool outputs and artifacts."""
    structured = extract_structured_evidence(tool_results=tool_results)
    if structured:
        formatted = _format_structured_evidence(structured)
        if formatted:
            parts: list[str] = [formatted]
        else:
            parts = []
    else:
        parts = []
    for entry in tool_results or []:
        if not entry.get("ok", True):
            continue
        output = entry.get("output")
        if isinstance(output, dict) and output:
            if not _output_has_useful_data(output):
                continue
            action = str(entry.get("action") or entry.get("tool") or "step")
            snippet = ", ".join(
                f"{k}={v}" for k, v in list(output.items())[:4] if _is_present(v) and k not in _META_ONLY_KEYS
            )
            if snippet:
                parts.append(f"{action}: {snippet[:400]}")
        elif _is_present(output):
            parts.append(str(output)[:400])

    repo = repo_investigation or {}
    queries = repo.get("queries") or []
    if queries:
        parts.append(f"queries={queries[:5]}")
    findings = repo.get("findings") or {}
    if isinstance(findings, dict) and findings:
        parts.append(f"findings_keys={list(findings.keys())[:5]}")

    for art in artifacts or []:
        preview = art.get("preview") or art.get("name")
        if _is_present(preview):
            parts.append(str(preview)[:200])

    if not parts:
        return None
    return "\n".join(parts)


def extract_numeric_result(
    *,
    tool_results: list[dict[str, Any]] | None = None,
    final_answer: str | None = None,
    completion_report: dict[str, Any] | None = None,
) -> int | float | None:
    """Extract a numeric answer when the task requests a quantity."""
    for entry in tool_results or []:
        output = entry.get("output")
        if isinstance(output, dict):
            for key in ("count", "numeric_result", "total", "value"):
                raw = output.get(key)
                if isinstance(raw, (int, float)):
                    return raw
                if isinstance(raw, str) and raw.strip().isdigit():
                    return int(raw.strip())

    for text in (
        (completion_report or {}).get("conclusion"),
        final_answer,
    ):
        if not _is_present(text):
            continue
        match = _NUMERIC_VALUE_RE.search(str(text))
        if match:
            value = match.group(1) or match.group(2)
            if value is not None:
                return int(value)
    return None


def extract_patch_diff(artifacts: list[dict[str, Any]] | None) -> str | None:
    """Return patch.diff content when present."""
    for art in artifacts or []:
        name = str(art.get("standard_name") or art.get("name") or "")
        if name == "patch.diff" or name.startswith("patch.diff"):
            content = art.get("content") or art.get("preview") or ""
            if _is_present(content) and "--- a/" in str(content):
                return str(content).strip()
    return None


def extract_remediation_plan(
    *,
    tool_results: list[dict[str, Any]] | None = None,
    review: dict[str, Any] | None = None,
    completion_report: dict[str, Any] | None = None,
) -> str | None:
    """Extract remediation plan from recommend_fix output or review."""
    output = _tool_output(tool_results or [], "recommend_fix")
    for key in ("remediation_plan", "recommended_fix", "fix", "plan"):
        if _is_present(output.get(key)):
            return str(output[key]).strip()

    rev = review or {}
    for key in ("remediation_plan", "approval_recommendation", "recommendation"):
        if _is_present(rev.get(key)):
            return str(rev[key]).strip()

    report = completion_report or {}
    if _is_present(report.get("next_action")) and "fix" in str(report.get("next_action")).lower():
        return str(report["next_action"]).strip()
    return None


def build_completion_report(
    *,
    objective: str,
    task_type: TaskType,
    tool_results: list[dict[str, Any]] | None = None,
    repo_investigation: dict[str, Any] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    final_answer: str | None = None,
    root_cause: str | None = None,
    numeric_result: int | float | None = None,
    remediation_plan: str | None = None,
) -> dict[str, str]:
    """Build mandatory completion report sections."""
    evidence = extract_evidence(
        tool_results=tool_results,
        repo_investigation=repo_investigation,
        artifacts=artifacts,
    )
    summary = (objective or "").strip() or "Task executed."
    if final_answer and _is_present(final_answer):
        summary = f"{summary}\n\nExecution: {str(final_answer).strip()[:800]}"

    conclusion_parts: list[str] = []
    if root_cause:
        conclusion_parts.append(f"Root cause: {root_cause}")
    if numeric_result is not None:
        conclusion_parts.append(f"Numeric result: {numeric_result}")
    if remediation_plan:
        conclusion_parts.append(f"Remediation: {remediation_plan}")

    for tool_name in ("diagnose_open_orders",):
        diag = _tool_output_by_name(tool_results or [], tool_name)
        if not diag:
            diag = _tool_output(tool_results or [], tool_name)
        if _is_present(diag.get("conclusion")):
            conclusion_parts.append(str(diag["conclusion"]).strip())
        if _is_present(diag.get("next_action")) and task_type in ("investigation", "operational"):
            next_action_override = str(diag["next_action"]).strip()
        else:
            next_action_override = None
        break
    else:
        next_action_override = None

    if not conclusion_parts and final_answer and _is_present(final_answer):
        conclusion_parts.append(str(final_answer).strip()[:600])
    conclusion = "\n".join(conclusion_parts) if conclusion_parts else ""

    if task_type == "patch":
        next_action = "Review patch.diff and approve or reject the proposed change."
        if not conclusion and extract_patch_diff(artifacts):
            conclusion = "Patch diff generated and ready for human review."
    elif task_type == "investigation" and not root_cause:
        next_action = "Re-run investigation with database/log access or assign to engineer."
    elif task_type == "numeric" and numeric_result is None:
        next_action = "Run a read-only database count query and attach the numeric result."
    elif remediation_plan:
        next_action = remediation_plan
    elif next_action_override:
        next_action = next_action_override
    elif root_cause:
        next_action = "Implement recommended fix behind approval gate."
    else:
        next_action = "Review evidence and confirm no further action is required."

    return {
        "summary": summary[:2000],
        "evidence": (evidence or "")[:2000],
        "conclusion": conclusion[:2000],
        "next_action": next_action[:1000],
    }


def _check(label: str, passed: bool) -> dict[str, Any]:
    return {"label": label, "passed": passed}


def validate_task_result(
    *,
    objective: str,
    task_type: TaskType | None = None,
    tool_results: list[dict[str, Any]] | None = None,
    repo_investigation: dict[str, Any] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    review: dict[str, Any] | None = None,
    final_answer: str | None = None,
    workflow_type: str | None = None,
) -> dict[str, Any]:
    """
    Final supervisor validation before status assignment.

    Returns validation payload with checks, completion_report, passed flag, and final_status.
    """
    resolved_type = task_type or classify_task_type(objective)
    root_cause = extract_root_cause(
        tool_results=tool_results,
        repo_investigation=repo_investigation,
    )
    evidence = extract_evidence(
        tool_results=tool_results,
        repo_investigation=repo_investigation,
        artifacts=artifacts,
    )
    numeric_result = extract_numeric_result(tool_results=tool_results, final_answer=final_answer)
    patch_diff = extract_patch_diff(artifacts)
    remediation_plan = extract_remediation_plan(tool_results=tool_results, review=review)

    completion_report = build_completion_report(
        objective=objective,
        task_type=resolved_type,
        tool_results=tool_results,
        repo_investigation=repo_investigation,
        artifacts=artifacts,
        final_answer=final_answer,
        root_cause=root_cause,
        numeric_result=numeric_result,
        remediation_plan=remediation_plan,
    )

    checks: list[dict[str, Any]] = []
    explanations: list[str] = []
    passed = True
    final_status = "completed"

    failed_tools = [
        r for r in (tool_results or [])
        if r.get("ok") is False or r.get("error")
    ]
    if failed_tools:
        tool_names = [str(r.get("tool") or r.get("action") or "?") for r in failed_tools]
        checks.append(_check("Mandatory tool execution succeeded", False))
        passed = False
        final_status = "failed"
        explanations.append(f"Tool failures: {', '.join(tool_names)}")

    successful_outputs = [
        r for r in (tool_results or [])
        if r.get("ok", True) and isinstance(r.get("output"), dict)
    ]
    if resolved_type == "investigation" and successful_outputs:
        all_empty = all(not _output_has_useful_data(r.get("output") or {}) for r in successful_outputs)
        if all_empty:
            checks.append(_check("Tool outputs contain useful data", False))
            passed = False
            if final_status != "failed":
                final_status = "insufficient_evidence"
            explanations.append("All tool outputs were empty or generic.")

    report_complete = all(_is_present(completion_report.get(k)) for k in ("summary", "evidence", "conclusion", "next_action"))
    checks.append(_check("Completion report complete", report_complete))
    if not report_complete:
        passed = False
        missing = [k for k in ("summary", "evidence", "conclusion", "next_action") if not _is_present(completion_report.get(k))]
        explanations.append(f"Completion report missing sections: {', '.join(missing)}")

    if resolved_type == "investigation":
        has_root = _is_meaningful_root_cause(root_cause)
        has_evidence = _is_present(evidence)
        has_useful_artifacts = any(_artifact_has_useful_content(a) for a in (artifacts or []))
        has_conclusion = _is_present(completion_report.get("conclusion")) and has_root
        checks.extend(
            [
                _check("Root cause present", has_root),
                _check("Evidence present", has_evidence),
                _check("Useful artifacts present", has_useful_artifacts or has_evidence),
                _check("Conclusion present", has_conclusion),
            ]
        )
        if final_status != "failed" and not (has_root and has_evidence and has_conclusion):
            passed = False
            final_status = "insufficient_evidence"
            explanations.append("Investigation requires root cause, evidence, and conclusion.")

    elif resolved_type == "numeric":
        has_numeric = numeric_result is not None
        checks.append(_check("Numeric result present", has_numeric))
        if not has_numeric:
            passed = False
            final_status = "failed"
            explanations.append("Requested numeric result was not produced.")

    elif resolved_type == "patch":
        has_patch = _is_present(patch_diff)
        checks.append(_check("Patch present", has_patch))
        if not has_patch:
            passed = False
            final_status = "failed"
            explanations.append("Patch generation did not produce patch.diff.")
        elif not report_complete:
            # Patch workflow can satisfy conclusion via generated diff metadata.
            completion_report["conclusion"] = completion_report.get("conclusion") or "Patch diff generated."
            completion_report["evidence"] = completion_report.get("evidence") or f"patch.diff ({len(patch_diff or '')} bytes)"
            report_complete = all(
                _is_present(completion_report.get(k)) for k in ("summary", "evidence", "conclusion", "next_action")
            )
            checks = [c for c in checks if c["label"] != "Completion report complete"]
            checks.append(_check("Completion report complete", report_complete))
            if not report_complete:
                passed = False
                final_status = "failed"
                explanations.append("Completion report missing required sections.")

    elif resolved_type == "remediation":
        has_root = _is_present(root_cause)
        has_plan = _is_present(remediation_plan)
        checks.extend(
            [
                _check("Root cause present", has_root),
                _check("Remediation plan present", has_plan),
            ]
        )
        if not (has_root and has_plan):
            passed = False
            final_status = "insufficient_evidence" if not has_root else "failed"
            explanations.append("Remediation requires root cause and remediation plan.")

    else:
        # Operational / read-only inspections: evidence + completion report sections.
        has_evidence = _is_present(evidence)
        checks.append(_check("Evidence present", has_evidence))
        if not has_evidence or not report_complete:
            passed = False
            final_status = "insufficient_evidence" if not has_evidence else "failed"

    if passed and resolved_type == "patch" and workflow_type == "phase4_change":
        final_status = "waiting_for_approval"

    return {
        "task_type": resolved_type,
        "passed": passed,
        "final_status": final_status,
        "checks": checks,
        "completion_report": completion_report,
        "explanation": " ".join(explanations) if explanations else "Validation passed.",
        "root_cause": root_cause,
        "numeric_result": numeric_result,
        "patch_present": bool(patch_diff),
        "remediation_plan": remediation_plan,
        "structured_evidence": extract_structured_evidence(tool_results=tool_results),
    }


def apply_validation_to_review(existing_review: dict[str, Any] | None, validation: dict[str, Any]) -> dict[str, Any]:
    """Merge validation outcome into task review_json."""
    review = dict(existing_review or {})
    review["validation"] = {
        "task_type": validation.get("task_type"),
        "passed": validation.get("passed"),
        "final_status": validation.get("final_status"),
        "checks": validation.get("checks") or [],
        "explanation": validation.get("explanation"),
        "completion_report": validation.get("completion_report") or {},
        "root_cause": validation.get("root_cause"),
        "numeric_result": validation.get("numeric_result"),
        "structured_evidence": validation.get("structured_evidence") or [],
    }
    return review
