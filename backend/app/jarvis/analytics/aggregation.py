"""Read-only aggregation helpers for Jarvis investigation analytics."""

from __future__ import annotations

import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from app import database as db_module
from app.database import ensure_jarvis_execution_log_table, ensure_jarvis_investigations_table, ensure_jarvis_task_runs_table
from app.jarvis.investigations.investigation_types import INVESTIGATION_TEMPLATES, InvestigationStatus


def _engine():
    return db_module.engine

_TERMINAL_STATUSES = frozenset(
    {
        InvestigationStatus.COMPLETED.value,
        InvestigationStatus.INSUFFICIENT_EVIDENCE.value,
        InvestigationStatus.PARTIAL_FAILURE.value,
        InvestigationStatus.FAILED.value,
    }
)

_RESOLVED_MARKERS = (
    "no active dashboard/exchange mismatch",
    "no active mismatch",
    "all sources agree: zero open orders",
    "dashboard correctly shows zero",
    "counts match",
    "no action required",
)

_FALSE_POSITIVE_MARKERS = (
    "no active dashboard/exchange mismatch",
    "no active mismatch",
    "all sources agree: zero open orders",
    "dashboard correctly shows zero",
    "no action required",
    "not determined",
)

_PROPOSAL_STATUSES = frozenset(
    {
        "no_fix_required",
        "waiting_for_approval",
        "approved",
        "rejected",
        "failed",
        "proposing",
    }
)

_TEMPLATE_COLLECTORS: dict[str, tuple[str, ...]] = {
    t.template_id: tuple(c.tool for c in t.collectors) for t in INVESTIGATION_TEMPLATES
}
_TEMPLATE_COLLECTORS["generic"] = ("read_logs", "inspect_health", "search_logs", "search_repository")


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text_val = str(value).strip()
        if not text_val:
            return None
        try:
            dt = datetime.fromisoformat(text_val.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _json_load(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _normalize_root_cause(text: str | None) -> str:
    key = str(text or "").lower().strip()
    key = re.sub(r"[^a-z0-9\s]", " ", key)
    key = re.sub(r"\s+", " ", key).strip()
    return key


def is_resolved_investigation(row: dict[str, Any]) -> bool:
    root = str(row.get("root_cause") or "").lower()
    if any(marker in root for marker in _RESOLVED_MARKERS):
        return True
    if row.get("status") == InvestigationStatus.COMPLETED.value and "historical" in root:
        return True
    return False


def is_false_positive(row: dict[str, Any]) -> bool:
    if row.get("status") != InvestigationStatus.COMPLETED.value:
        return False
    root = str(row.get("root_cause") or "").lower()
    if any(marker in root for marker in _FALSE_POSITIVE_MARKERS):
        return True
    confidence = float(row.get("confidence") or 0)
    evidence = _json_load(row.get("evidence_json"), [])
    if confidence < 30 and len(evidence) <= 1:
        return True
    return False


def _row_to_investigation(row: Any) -> dict[str, Any]:
    mapping = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
    evidence = _json_load(mapping.get("evidence_json"), [])
    created_at = mapping.get("created_at")
    if created_at is not None and hasattr(created_at, "isoformat"):
        created_at = created_at.isoformat()
    return {
        "investigation_id": mapping.get("investigation_id"),
        "objective": mapping.get("objective"),
        "category": mapping.get("category"),
        "template_id": mapping.get("template_id") or "generic",
        "status": mapping.get("status"),
        "summary": mapping.get("summary"),
        "root_cause": mapping.get("root_cause"),
        "confidence": float(mapping.get("confidence") or 0),
        "evidence_json": evidence,
        "evidence_count": len(evidence),
        "proposal_task_id": mapping.get("proposal_task_id"),
        "proposal_status": mapping.get("proposal_status"),
        "created_at": created_at,
    }


def fetch_all_investigations(*, limit: int = 5000) -> list[dict[str, Any]]:
    engine = _engine()
    if engine is None or not ensure_jarvis_investigations_table(engine):
        return []
    safe_limit = max(1, min(limit, 10000))
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT investigation_id, objective, category, template_id, status,
                           summary, root_cause, confidence, evidence_json,
                           proposal_task_id, proposal_status, created_at
                    FROM jarvis_investigations
                    ORDER BY created_at DESC
                    LIMIT :limit
                    """
                ),
                {"limit": safe_limit},
            ).fetchall()
        return [_row_to_investigation(row) for row in rows]
    except Exception:
        return []


def fetch_execution_logs(*, limit: int = 20000) -> list[dict[str, Any]]:
    engine = _engine()
    if engine is None or not ensure_jarvis_execution_log_table(engine):
        return []
    safe_limit = max(1, min(limit, 50000))
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT log_id, task_id, agent, tool, input_summary, output_summary,
                           duration_ms, metadata_json, created_at
                    FROM jarvis_execution_log
                    ORDER BY created_at DESC
                    LIMIT :limit
                    """
                ),
                {"limit": safe_limit},
            ).fetchall()
    except Exception:
        return []

    out: list[dict[str, Any]] = []
    for row in rows:
        mapping = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
        meta = _json_load(mapping.get("metadata_json"), {})
        created_at = mapping.get("created_at")
        if created_at is not None and hasattr(created_at, "isoformat"):
            created_at = created_at.isoformat()
        output_summary = str(mapping.get("output_summary") or "")
        out.append(
            {
                "log_id": mapping.get("log_id"),
                "task_id": mapping.get("task_id"),
                "agent": mapping.get("agent"),
                "tool": mapping.get("tool") or "unknown",
                "input_summary": mapping.get("input_summary"),
                "output_summary": output_summary,
                "duration_ms": int(mapping.get("duration_ms") or 0),
                "metadata": meta,
                "created_at": created_at,
                "failed": _log_entry_failed(output_summary, meta),
                "error_message": _extract_error_message(output_summary, meta),
            }
        )
    return out


def fetch_proposal_tasks(*, limit: int = 5000) -> list[dict[str, Any]]:
    engine = _engine()
    if engine is None or not ensure_jarvis_task_runs_table(engine):
        return []
    safe_limit = max(1, min(limit, 10000))
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT task_id, objective, status, approval_status, plan_json,
                           artifacts_json, started_at, completed_at, created_at, error
                    FROM jarvis_task_runs
                    ORDER BY created_at DESC
                    LIMIT :limit
                    """
                ),
                {"limit": safe_limit},
            ).fetchall()
    except Exception:
        return []

    out: list[dict[str, Any]] = []
    for row in rows:
        mapping = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
        plan = _json_load(mapping.get("plan_json"), {})
        if not isinstance(plan, dict):
            continue
        workflow = str(plan.get("workflow_type") or "")
        if workflow != "phase4b_patch_proposal":
            continue
        artifacts = _json_load(mapping.get("artifacts_json"), [])
        if not isinstance(artifacts, list):
            artifacts = []
        started_at = mapping.get("started_at")
        completed_at = mapping.get("completed_at")
        created_at = mapping.get("created_at")
        for field in ("started_at", "completed_at", "created_at"):
            val = mapping.get(field)
            if val is not None and hasattr(val, "isoformat"):
                mapping[field] = val.isoformat()
        out.append(
            {
                "task_id": mapping.get("task_id"),
                "objective": mapping.get("objective"),
                "status": mapping.get("status"),
                "approval_status": mapping.get("approval_status"),
                "workflow_type": workflow,
                "source_investigation_id": plan.get("source_investigation_id"),
                "fix_template_id": plan.get("fix_template_id"),
                "artifacts_count": len(artifacts),
                "started_at": started_at.isoformat() if hasattr(started_at, "isoformat") else started_at,
                "completed_at": completed_at.isoformat() if hasattr(completed_at, "isoformat") else completed_at,
                "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
                "error": mapping.get("error"),
            }
        )
    return out


def _log_entry_failed(output_summary: str, metadata: dict[str, Any]) -> bool:
    if metadata.get("ok") is False:
        return True
    if metadata.get("error"):
        return True
    lowered = output_summary.lower()
    return any(token in lowered for token in ("error", "failed", "exception", "traceback"))


def _extract_error_message(output_summary: str, metadata: dict[str, Any]) -> str | None:
    err = metadata.get("error")
    if isinstance(err, str) and err.strip():
        return err.strip()[:200]
    lowered = output_summary.lower()
    if any(token in lowered for token in ("error", "failed", "exception")):
        return output_summary.strip()[:200]
    return None


def estimate_investigation_duration_ms(row: dict[str, Any], *, default_tool_ms: float = 2500.0) -> float:
    """Estimate investigation duration when explicit timing is unavailable."""
    evidence_count = int(row.get("evidence_count") or len(row.get("evidence_json") or []))
    template_id = row.get("template_id") or "generic"
    collector_count = len(_TEMPLATE_COLLECTORS.get(template_id, _TEMPLATE_COLLECTORS["generic"]))
    base = max(evidence_count, collector_count, 1)
    return base * default_tool_ms


def aggregate_investigation_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    status_counter: Counter[str] = Counter()
    durations: list[float] = []
    resolved = 0
    false_positives = 0
    tool_errors = 0

    for row in rows:
        status = str(row.get("status") or "unknown")
        status_counter[status] += 1
        if is_resolved_investigation(row):
            resolved += 1
        if is_false_positive(row):
            false_positives += 1
        if status in _TERMINAL_STATUSES:
            durations.append(estimate_investigation_duration_ms(row))
        if status == InvestigationStatus.PARTIAL_FAILURE.value:
            tool_errors += 1
        elif status == InvestigationStatus.FAILED.value:
            tool_errors += 2

    terminal = sum(status_counter[s] for s in _TERMINAL_STATUSES)
    completed = status_counter.get(InvestigationStatus.COMPLETED.value, 0)
    insufficient = status_counter.get(InvestigationStatus.INSUFFICIENT_EVIDENCE.value, 0)
    partial = status_counter.get(InvestigationStatus.PARTIAL_FAILURE.value, 0)
    failed = status_counter.get(InvestigationStatus.FAILED.value, 0)
    running = status_counter.get(InvestigationStatus.RUNNING.value, 0)

    avg_duration = round(statistics.mean(durations), 1) if durations else 0.0
    median_duration = round(statistics.median(durations), 1) if durations else 0.0

    success_rate = round(completed / terminal * 100, 1) if terminal else 0.0
    failure_rate = round((partial + failed) / terminal * 100, 1) if terminal else 0.0
    insufficient_rate = round(insufficient / terminal * 100, 1) if terminal else 0.0

    return {
        "total_investigations": len(rows),
        "completed": completed,
        "resolved": resolved,
        "insufficient_evidence": insufficient,
        "partial_failure": partial,
        "failed": failed,
        "running": running,
        "average_duration_ms": avg_duration,
        "median_duration_ms": median_duration,
        "success_rate_pct": success_rate,
        "failure_rate_pct": failure_rate,
        "insufficient_evidence_rate_pct": insufficient_rate,
        "false_positives": false_positives,
        "tool_errors_inferred": tool_errors,
    }


def aggregate_template_metrics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("template_id") or "generic")].append(row)

    results: list[dict[str, Any]] = []
    for template_id, items in grouped.items():
        total = len(items)
        completed = sum(1 for r in items if r.get("status") == InvestigationStatus.COMPLETED.value)
        failed = sum(
            1
            for r in items
            if r.get("status") in (InvestigationStatus.FAILED.value, InvestigationStatus.PARTIAL_FAILURE.value)
        )
        insufficient = sum(
            1 for r in items if r.get("status") == InvestigationStatus.INSUFFICIENT_EVIDENCE.value
        )
        confidences = [float(r.get("confidence") or 0) for r in items]
        avg_confidence = round(statistics.mean(confidences), 1) if confidences else 0.0
        terminal = sum(1 for r in items if r.get("status") in _TERMINAL_STATUSES)
        results.append(
            {
                "template_id": template_id,
                "investigations": total,
                "completed": completed,
                "failed": failed,
                "insufficient_evidence": insufficient,
                "completion_rate_pct": round(completed / terminal * 100, 1) if terminal else 0.0,
                "failure_rate_pct": round(failed / terminal * 100, 1) if terminal else 0.0,
                "insufficient_evidence_rate_pct": round(insufficient / terminal * 100, 1) if terminal else 0.0,
                "average_confidence": avg_confidence,
            }
        )

    results.sort(key=lambda item: (-item["completion_rate_pct"], -item["investigations"]))
    return results


def aggregate_tool_metrics(
    logs: list[dict[str, Any]],
    investigations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "executions": 0,
            "successes": 0,
            "failures": 0,
            "total_duration_ms": 0,
            "error_messages": Counter(),
        }
    )

    for entry in logs:
        tool = str(entry.get("tool") or "unknown")
        bucket = stats[tool]
        bucket["executions"] += 1
        bucket["total_duration_ms"] += int(entry.get("duration_ms") or 0)
        if entry.get("failed"):
            bucket["failures"] += 1
            err = entry.get("error_message")
            if err:
                bucket["error_messages"][err] += 1
        else:
            bucket["successes"] += 1

    for row in investigations:
        if row.get("status") not in _TERMINAL_STATUSES:
            continue
        template_id = str(row.get("template_id") or "generic")
        collectors = _TEMPLATE_COLLECTORS.get(template_id, _TEMPLATE_COLLECTORS["generic"])
        failed = row.get("status") in (
            InvestigationStatus.FAILED.value,
            InvestigationStatus.PARTIAL_FAILURE.value,
        )
        for tool in collectors:
            bucket = stats[tool]
            bucket["executions"] += 1
            bucket["total_duration_ms"] += 2500
            if failed:
                bucket["failures"] += 1
                bucket["error_messages"][f"investigation {row.get('status')}"] += 1
            else:
                bucket["successes"] += 1

    results: list[dict[str, Any]] = []
    for tool, bucket in stats.items():
        executions = int(bucket["executions"])
        successes = int(bucket["successes"])
        failures = int(bucket["failures"])
        avg_duration = round(bucket["total_duration_ms"] / executions, 1) if executions else 0.0
        common_errors = [
            {"message": msg, "count": count}
            for msg, count in bucket["error_messages"].most_common(5)
        ]
        results.append(
            {
                "tool": tool,
                "executions": executions,
                "successes": successes,
                "failures": failures,
                "success_rate_pct": round(successes / executions * 100, 1) if executions else 0.0,
                "failure_rate_pct": round(failures / executions * 100, 1) if executions else 0.0,
                "average_duration_ms": avg_duration,
                "common_errors": common_errors,
            }
        )

    results.sort(key=lambda item: (-item["executions"], item["tool"]))
    return results


def aggregate_proposal_metrics(
    investigations: list[dict[str, Any]],
    proposal_tasks: list[dict[str, Any]],
) -> dict[str, Any]:
    status_counter: Counter[str] = Counter()
    generated = 0

    for row in investigations:
        proposal_status = str(row.get("proposal_status") or "").strip().lower()
        if row.get("proposal_task_id") or proposal_status:
            generated += 1
        if proposal_status:
            status_counter[proposal_status] += 1

    for task in proposal_tasks:
        generated += 1
        task_status = str(task.get("status") or "").lower()
        approval = str(task.get("approval_status") or "").lower()
        if task_status == "failed" or task.get("error"):
            status_counter["failed"] += 1
        elif approval == "approved" or task_status == "approved":
            status_counter["approved"] += 1
        elif approval == "rejected":
            status_counter["rejected"] += 1
        elif task_status in ("waiting_for_approval", "waiting_for_pr_approval"):
            status_counter["waiting_for_approval"] += 1

    useful = status_counter.get("approved", 0) + status_counter.get("waiting_for_approval", 0)
    funnel = {
        "proposals_generated": max(generated, sum(status_counter.values())),
        "no_fix_required": status_counter.get("no_fix_required", 0),
        "waiting_for_approval": status_counter.get("waiting_for_approval", 0),
        "approved": status_counter.get("approved", 0),
        "rejected": status_counter.get("rejected", 0),
        "failed": status_counter.get("failed", 0),
        "proposing": status_counter.get("proposing", 0),
        "useful_proposals": useful,
        "useful_rate_pct": round(useful / generated * 100, 1) if generated else 0.0,
    }
    return funnel


def aggregate_root_cause_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    cause_counter: Counter[str] = Counter()
    recurring: list[dict[str, Any]] = []
    resolved_incidents: list[dict[str, Any]] = []
    active_incidents: list[dict[str, Any]] = []

    label_by_key: dict[str, str] = {}
    for row in rows:
        root = str(row.get("root_cause") or "").strip()
        if not root:
            continue
        key = _normalize_root_cause(root)
        if not key:
            continue
        cause_counter[key] += 1
        label_by_key.setdefault(key, root)

    for key, count in cause_counter.most_common(20):
        recurring.append({"root_cause": label_by_key[key], "occurrences": count, "key": key})

    for row in rows:
        root = str(row.get("root_cause") or "").strip()
        if not root:
            continue
        entry = {
            "investigation_id": row.get("investigation_id"),
            "objective": row.get("objective"),
            "root_cause": root,
            "status": row.get("status"),
            "confidence": float(row.get("confidence") or 0),
            "created_at": row.get("created_at"),
        }
        if is_resolved_investigation(row):
            resolved_incidents.append(entry)
        elif row.get("status") == InvestigationStatus.COMPLETED.value:
            active_incidents.append(entry)

    return {
        "most_common_root_causes": recurring[:10],
        "recurring_incidents": [r for r in recurring if r["occurrences"] >= 2][:10],
        "resolved_incidents": resolved_incidents[:50],
        "active_incidents": active_incidents[:50],
        "unique_root_causes": len(cause_counter),
    }


def filter_rows_since(rows: list[dict[str, Any]], days: int) -> list[dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    filtered: list[dict[str, Any]] = []
    for row in rows:
        created = _parse_ts(row.get("created_at"))
        if created is None or created >= cutoff:
            filtered.append(row)
    return filtered


def count_tool_errors(logs: list[dict[str, Any]], investigations: list[dict[str, Any]]) -> int:
    log_errors = sum(1 for entry in logs if entry.get("failed"))
    inv_errors = sum(
        1
        for row in investigations
        if row.get("status")
        in (InvestigationStatus.PARTIAL_FAILURE.value, InvestigationStatus.FAILED.value)
    )
    return log_errors + inv_errors


_QUALITY_PENALTIES = {
    InvestigationStatus.PARTIAL_FAILURE.value: 5,
    InvestigationStatus.FAILED.value: 10,
    InvestigationStatus.INSUFFICIENT_EVIDENCE.value: 3,
}
_TOOL_ERROR_PENALTY = 1
_TERMINAL_FOR_SCORE = frozenset(_QUALITY_PENALTIES.keys()) | {InvestigationStatus.COMPLETED.value}


def compute_quality_score(
    investigations: list[dict[str, Any]],
    *,
    tool_errors: int = 0,
) -> float:
    """Investigation Quality Score (0–100) from status penalties and tool errors."""
    if not investigations:
        return 100.0

    terminal = [row for row in investigations if row.get("status") in _TERMINAL_FOR_SCORE]
    if not terminal:
        return 100.0

    total_penalty = 0
    for row in terminal:
        status = str(row.get("status") or "")
        total_penalty += _QUALITY_PENALTIES.get(status, 0)
    total_penalty += tool_errors * _TOOL_ERROR_PENALTY

    per_inv_penalty = total_penalty / len(terminal)
    return round(max(0.0, min(100.0, 100.0 - per_inv_penalty)), 1)
