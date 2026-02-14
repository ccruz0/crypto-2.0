"""
AI Engine service. Scaffold: writes audit logs under AI_RUNS_DIR; no model calls.
Supports optional tool_calls (search_repo, read_snippet, tail_logs); logs to tools.json.
"""
import json
import os
import re
from datetime import datetime
from typing import Any

from app.services.ai_engine import tools as ai_tools


# Hardening: max length per match "line" in report; max logs excerpt; max report body size.
_MAX_MATCH_LINE_CHARS = 500
_MAX_LOGS_EXCERPT_CHARS = 20000
_MAX_REPORT_JSON_BYTES = 2 * 1024 * 1024  # 2MB


def _get_ai_runs_dir() -> str:
    return os.getenv("AI_RUNS_DIR", "backend/ai_runs")


def _truncate_matches(matches: list[dict[str, Any]], max_matches: int = 15, max_line_chars: int = _MAX_MATCH_LINE_CHARS) -> list[dict[str, Any]]:
    """Return up to max_matches matches with each 'line' capped at max_line_chars."""
    out: list[dict[str, Any]] = []
    for m in matches[:max_matches]:
        if not isinstance(m, dict):
            continue
        m = dict(m)
        if "line" in m and isinstance(m["line"], str):
            m["line"] = m["line"][:max_line_chars]
        out.append(m)
    return out


def _auth_doctor_tool_calls() -> list[dict[str, Any]]:
    """Fixed sequence of tool calls for doctor:auth (order matters)."""
    return [
        {"tool": "search_repo", "args": {"query": "40101", "max_results": 50}},
        {"tool": "search_repo", "args": {"query": "40103", "max_results": 50}},
        {"tool": "search_repo", "args": {"query": "INVALID_SIGNATURE", "max_results": 50}},
        {"tool": "search_repo", "args": {"query": "signature", "max_results": 50}},
        {"tool": "search_repo", "args": {"query": "HMAC", "max_results": 50}},
        {"tool": "search_repo", "args": {"query": "get-time", "max_results": 50}},
        {"tool": "search_repo", "args": {"query": "_log_40101_diagnostics", "max_results": 50}},
        {"tool": "tail_logs", "args": {"service": "backend-aws", "lines": 600}},
    ]


def _sltp_doctor_tool_calls() -> list[dict[str, Any]]:
    """Fixed sequence of tool calls for doctor:sltp (order matters)."""
    return [
        {"tool": "search_repo", "args": {"query": "stop loss", "max_results": 50}},
        {"tool": "search_repo", "args": {"query": "take profit", "max_results": 50}},
        {"tool": "search_repo", "args": {"query": "trigger_condition", "max_results": 50}},
        {"tool": "search_repo", "args": {"query": "tp_price", "max_results": 50}},
        {"tool": "search_repo", "args": {"query": "sl_price", "max_results": 50}},
        {"tool": "search_repo", "args": {"query": "Invalid price format", "max_results": 50}},
        {"tool": "search_repo", "args": {"query": "Error 308", "max_results": 50}},
        {"tool": "search_repo", "args": {"query": "140001", "max_results": 50}},
        {"tool": "search_repo", "args": {"query": "API_DISABLED", "max_results": 50}},
        {"tool": "tail_logs", "args": {"service": "backend-aws", "lines": 400}},
    ]


def _write_sltp_doctor_report(run_dir: str, tool_entries: list[dict[str, Any]]) -> str:
    """Build and write report.json for doctor:sltp. Returns path to report.json."""
    generated_at_utc = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    queries_findings: list[dict[str, Any]] = []
    logs_excerpt = ""
    for entry in tool_entries:
        if entry.get("tool") == "search_repo":
            q = (entry.get("args") or {}).get("query", "")
            matches = entry.get("result") if "result" in entry else []
            if not isinstance(matches, list):
                matches = []
            queries_findings.append({"query": q, "matches": _truncate_matches(matches, 15, _MAX_MATCH_LINE_CHARS)})
        elif entry.get("tool") == "tail_logs":
            res = entry.get("result")
            if isinstance(res, dict) and "output" in res:
                logs_excerpt = str(res["output"])[:_MAX_LOGS_EXCERPT_CHARS]
            elif isinstance(res, dict) and "error" in res:
                logs_excerpt = str(res.get("error", ""))[:_MAX_LOGS_EXCERPT_CHARS]

    payload_numeric_validation = "FAIL" if "payload_numeric_validation FAIL" in (logs_excerpt or "") else "PASS"
    scientific_notation_detected = bool(re.search(r"\d+[eE][+-]?\d+", logs_excerpt or ""))
    # Real env mismatch: excerpt contains both sandbox/uat and prod (api.crypto.com) hints
    _ex = (logs_excerpt or "").lower()
    _has_sandbox_uat = "uat" in _ex or "sandbox" in _ex
    _has_prod = "api.crypto.com" in _ex
    environment_mismatch_detected = bool(_has_sandbox_uat and _has_prod)

    report = {
        "doctor": "sltp",
        "generated_at_utc": generated_at_utc,
        "payload_numeric_validation": payload_numeric_validation,
        "scientific_notation_detected": scientific_notation_detected,
        "environment_mismatch_detected": environment_mismatch_detected,
        "findings": {
            "queries": queries_findings,
            "logs_excerpt": logs_excerpt,
        },
        "next_actions": [
            "Open the top candidate file(s) around the returned line numbers and inspect how price formatting / precision is handled for TP/SL.",
            "Confirm instrument tick size and price precision rules; verify rounding/formatting matches exchange requirements.",
            "Check whether Error 140001 API_DISABLED is permission scope, account setting, or endpoint restriction for trigger orders.",
            "Reproduce in sandbox with one instrument and log the exact payload sent for SL/TP creation (without secrets).",
        ],
    }
    path = os.path.join(run_dir, "report.json")
    _write_report_with_size_cap(path, report)
    return path


def _write_report_with_size_cap(path: str, report: dict[str, Any]) -> None:
    """Write report JSON; if over _MAX_REPORT_JSON_BYTES, truncate findings.logs_excerpt and retry."""
    body = json.dumps(report, indent=2)
    if len(body.encode("utf-8")) > _MAX_REPORT_JSON_BYTES and "findings" in report and isinstance(report["findings"], dict):
        report = dict(report)
        report["findings"] = dict(report["findings"])
        report["findings"]["logs_excerpt"] = (report["findings"].get("logs_excerpt") or "")[:5000]
        body = json.dumps(report, indent=2)
    with open(path, "w") as f:
        f.write(body)


def _write_auth_doctor_report(run_dir: str, tool_entries: list[dict[str, Any]]) -> str:
    """Build and write report.json for doctor:auth. Returns path to report.json."""
    generated_at_utc = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    queries_findings: list[dict[str, Any]] = []
    logs_excerpt = ""
    for entry in tool_entries:
        if entry.get("tool") == "search_repo":
            q = (entry.get("args") or {}).get("query", "")
            matches = entry.get("result") if "result" in entry else []
            if not isinstance(matches, list):
                matches = []
            queries_findings.append({"query": q, "matches": _truncate_matches(matches, 15, _MAX_MATCH_LINE_CHARS)})
        elif entry.get("tool") == "tail_logs":
            res = entry.get("result")
            if isinstance(res, dict) and "output" in res:
                logs_excerpt = str(res["output"])[:_MAX_LOGS_EXCERPT_CHARS]
            elif isinstance(res, dict) and "error" in res:
                logs_excerpt = str(res.get("error", ""))[:_MAX_LOGS_EXCERPT_CHARS]

    tail_logs_source = None
    compose_dir_used = None
    for entry in tool_entries:
        if entry.get("tool") == "tail_logs":
            res = entry.get("result")
            if isinstance(res, dict):
                tail_logs_source = res.get("tail_logs_source")
                compose_dir_used = res.get("compose_dir_used")
            break

    report = {
        "doctor": "auth",
        "generated_at_utc": generated_at_utc,
        "tail_logs_source": tail_logs_source,
        "compose_dir_used": compose_dir_used,
        "findings": {
            "queries": queries_findings,
            "logs_excerpt": logs_excerpt,
        },
        "next_actions": [
            "Confirm server time drift diagnostics are present and compare container_utc vs exchange server time if available.",
            "Verify API key permissions on Crypto.com Exchange for the endpoints being called (trading, order management, trigger orders).",
            "Check signature input construction (method, path, params ordering, nonce/timestamp). Ensure exact match with Crypto.com spec.",
            "Confirm base URL environment (prod vs sandbox) matches the API key environment.",
        ],
    }
    path = os.path.join(run_dir, "report.json")
    _write_report_with_size_cap(path, report)
    return path


def _run_one_tool(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """Dispatch one tool call; return {tool, args, result} or {tool, args, error}."""
    out: dict[str, Any] = {"tool": tool, "args": args}
    try:
        if tool == "search_repo":
            out["result"] = ai_tools.search_repo(
                args.get("query", ""),
                max_results=int(args.get("max_results", 50)),
            )
        elif tool == "read_snippet":
            out["result"] = ai_tools.read_snippet(
                args.get("path", ""),
                line_start=args.get("line_start"),
                line_end=args.get("line_end"),
                max_lines=int(args.get("max_lines", 200)),
            )
        elif tool == "tail_logs":
            out["result"] = ai_tools.tail_logs(
                args.get("service", ""),
                lines=int(args.get("lines", 100)),
            )
        else:
            out["error"] = f"unknown tool: {tool}"
    except Exception as e:
        out["error"] = str(e)
    return out


def run_ai_task(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Run AI task (scaffold). Writes input.json and result.json under a timestamped
    folder in AI_RUNS_DIR. If payload has tool_calls, runs them and writes tools.json.
    No model call; returns placeholder response.
    """
    task = payload.get("task", "")
    mode = payload.get("mode", "sandbox")
    apply_changes = payload.get("apply_changes", False)
    tool_calls = payload.get("tool_calls") or []
    doctor_mode = False
    doctor_name = None
    doctor_index_mode = task.strip().lower().startswith("doctor:index")
    if not doctor_index_mode:
        if task.strip().lower().startswith("doctor:sltp") and not tool_calls:
            tool_calls = _sltp_doctor_tool_calls()
            doctor_mode = True
            doctor_name = "sltp"
        elif task.strip().lower().startswith("doctor:auth") and not tool_calls:
            tool_calls = _auth_doctor_tool_calls()
            doctor_mode = True
            doctor_name = "auth"

    base_dir = _get_ai_runs_dir()
    timestamp = datetime.utcnow().strftime("%Y-%m-%d_%H%M%S")
    run_dir = os.path.join(base_dir, timestamp)
    try:
        os.makedirs(base_dir, exist_ok=True)
        os.makedirs(run_dir, exist_ok=True)
    except OSError:
        run_dir = os.path.join("/tmp", "ai_runs_fallback", timestamp)
        os.makedirs(run_dir, exist_ok=True)

    input_path = os.path.join(run_dir, "input.json")
    with open(input_path, "w") as f:
        json.dump(payload, f, indent=2)

    if doctor_index_mode:
        # Strong guard: doctor:index runs zero tools; do not create tools.json or report.json.
        result = {
            "status": "ok",
            "doctor": "index",
            "available_doctors": [
                {"name": "sltp", "task": "doctor:sltp", "description": "Locate SL/TP builders + recent related errors; produces report.json"},
                {"name": "auth", "task": "doctor:auth", "description": "Collect auth-related code references + backend logs around 40101/40103; produces report.json"},
            ],
            "message": "AI Engine scaffold running. No model call executed.",
            "run_dir": run_dir,
            "mode": mode,
            "apply_changes": apply_changes,
        }
        if payload.get("tool_calls"):
            result["doctor_warning"] = ["doctor:index runs zero tools; payload tool_calls ignored"]
        result_path = os.path.join(run_dir, "result.json")
        with open(result_path, "w") as f:
            json.dump(result, f, indent=2)
        return result

    doctor_warnings: list[str] = []
    tool_entries: list[dict[str, Any]] = []
    # Defensive guard: tool loop must not run when doctor_index_mode (we already returned above).
    if not doctor_index_mode:
        for call in tool_calls:
            if isinstance(call, dict):
                t = call.get("tool") or call.get("name")
                args = call.get("args") or call
                if isinstance(args, dict) and "tool" in args:
                    args = {k: v for k, v in args.items() if k != "tool" and k != "name"}
                if t:
                    tool_entries.append(_run_one_tool(str(t), args if isinstance(args, dict) else {}))

    if tool_entries:
        tools_path = os.path.join(run_dir, "tools.json")
        with open(tools_path, "w") as f:
            json.dump(tool_entries, f, indent=2)
    elif doctor_mode and not tool_entries:
        doctor_warnings.append("tools.json not written: tool_entries empty")

    report_path = None
    if doctor_mode and tool_entries:
        if doctor_name == "sltp":
            report_path = _write_sltp_doctor_report(run_dir, tool_entries)
        elif doctor_name == "auth":
            # Safe assertion: auth report only when doctor_name is auth
            if doctor_name != "auth":
                doctor_warnings.append("auth report skipped: doctor_name != auth")
            else:
                report_path = _write_auth_doctor_report(run_dir, tool_entries)
        else:
            doctor_warnings.append("report not written: doctor_name not sltp or auth")

    result = {
        "status": "ok",
        "mode": mode,
        "apply_changes": apply_changes,
        "message": "AI Engine scaffold running. No model call executed.",
        "run_dir": run_dir,
    }
    if doctor_mode and doctor_name:
        result["doctor"] = doctor_name
        if report_path:
            result["report_path"] = report_path
    if tool_entries:
        result["tools_called"] = len(tool_entries)
        result["tools"] = [{"tool": e["tool"], "error": e.get("error")} for e in tool_entries]
    if doctor_warnings:
        result["doctor_warning"] = doctor_warnings
    result_path = os.path.join(run_dir, "result.json")
    with open(result_path, "w") as f:
        json.dump(result, f, indent=2)

    return result
