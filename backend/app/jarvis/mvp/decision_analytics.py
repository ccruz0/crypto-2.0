"""Decision intelligence analytics for Jarvis (read-only)."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from app.jarvis.mvp.decision_persistence import list_all_decisions
from app.jarvis.mvp.initiative_persistence import list_all_initiatives

_REPEATED_FINDING_PATTERNS = (
    "security group",
    "tagging",
    "ebs",
    "portfolio",
    "reconciliation",
    "cache",
    "snapshot",
    "elastic ip",
)


def normalize_recommendation_key(text: str) -> str:
    """Normalize recommendation text for decision history matching."""
    key = str(text or "").lower().strip()
    key = re.sub(r"[^a-z0-9\s]", " ", key)
    key = re.sub(r"\s+", " ", key).strip()
    return key


def _recommendation_label(decision: dict[str, Any]) -> str:
    reason = str(decision.get("decision_reason") or "").strip()
    if reason:
        return reason
    source = str(decision.get("source_type") or "unknown")
    plan = decision.get("plan_id")
    if plan:
        return f"{source} plan {str(plan)[:8]}"
    return source


def get_decision_history_index() -> dict[str, dict[str, Any]]:
    """
    Build index keyed by normalized recommendation label.

    Each entry tracks rejection/approval counts and outcome tallies.
    """
    index: dict[str, dict[str, Any]] = {}

    for decision in list_all_decisions():
        label = _recommendation_label(decision)
        key = normalize_recommendation_key(label)
        if not key:
            continue

        entry = index.setdefault(
            key,
            {
                "label": label,
                "approved": 0,
                "rejected": 0,
                "deferred": 0,
                "successful": 0,
                "unsuccessful": 0,
                "partial": 0,
                "unknown": 0,
                "total": 0,
            },
        )
        entry["total"] += 1
        dtype = str(decision.get("decision") or "").lower()
        if dtype in ("approved", "rejected", "deferred"):
            entry[dtype] += 1
        outcome = str(decision.get("outcome") or "unknown").lower()
        if outcome in ("successful", "unsuccessful", "partial", "unknown"):
            entry[outcome] += 1

    return index


def get_initiative_outcome_index() -> dict[str, dict[str, Any]]:
    """
    Build index keyed by normalized initiative title for confidence adjustments.

    Completed initiatives count as successes; cancelled/blocked count as failures.
    """
    index: dict[str, dict[str, Any]] = {}
    for initiative in list_all_initiatives():
        title = str(initiative.get("title") or "").strip()
        key = normalize_recommendation_key(title)
        if not key:
            continue
        entry = index.setdefault(
            key,
            {"label": title, "completed": 0, "cancelled": 0, "blocked": 0, "failed": 0, "total": 0},
        )
        entry["total"] += 1
        status = str(initiative.get("status") or "").lower()
        if status == "completed":
            entry["completed"] += 1
        elif status == "cancelled":
            entry["cancelled"] += 1
            entry["failed"] += 1
        elif status == "blocked":
            entry["blocked"] += 1
            entry["failed"] += 1
    return index


def apply_initiative_confidence_adjustments(
    item: dict[str, Any],
    initiative_index: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Adjust priority score based on linked initiative track record."""
    index = initiative_index or get_initiative_outcome_index()
    if not index:
        return item

    title_key = normalize_recommendation_key(str(item.get("title") or ""))
    history = index.get(title_key)
    if not history:
        for hist_key, hist_val in index.items():
            if hist_key and (hist_key in title_key or title_key in hist_key):
                history = hist_val
                break
    if not history:
        return item

    score = float(item.get("priority_score") or 0)
    impact = int(item.get("impact") or 5)
    notes: list[str] = list(item.get("decision_context", "").split("; ") if item.get("decision_context") else [])
    notes = [n for n in notes if n]

    completed = int(history.get("completed") or 0)
    failed = int(history.get("failed") or 0)

    if failed >= 2:
        score *= 0.5 if failed < 3 else 0.25
        notes.append(f"Related initiative failed {failed} time(s) — lowered confidence")
    elif completed >= 2:
        boost = min(1.5, 1.0 + (completed * 0.1))
        score *= boost
        impact = min(10, impact + 1)
        notes.append(f"Related initiative succeeded {completed} time(s) — increased confidence")

    item = dict(item)
    item["priority_score"] = round(score, 2)
    item["impact"] = impact
    if notes:
        item["decision_context"] = "; ".join(notes)
    return item


def apply_decision_adjustments(
    item: dict[str, Any],
    history_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """
    Adjust priority score based on Carlos's past decisions.

    - 5+ rejections: lower priority significantly
    - Prior successful approvals on similar items: boost confidence
    - Prior unsuccessful outcomes: slight penalty
    """
    title_key = normalize_recommendation_key(str(item.get("title") or ""))
    reason_key = normalize_recommendation_key(str(item.get("reason") or ""))

    history = history_index.get(title_key) or history_index.get(reason_key)
    if not history:
        for hist_key, hist_val in history_index.items():
            if hist_key and (hist_key in title_key or hist_key in reason_key or title_key in hist_key):
                history = hist_val
                break

    if not history:
        return item

    score = float(item.get("priority_score") or 0)
    impact = int(item.get("impact") or 5)
    notes: list[str] = []

    rejected = int(history.get("rejected") or 0)
    approved = int(history.get("approved") or 0)
    successful = int(history.get("successful") or 0)
    unsuccessful = int(history.get("unsuccessful") or 0)

    if rejected >= 5:
        score *= 0.25
        notes.append(f"Rejected {rejected} times previously — lowered priority")
    elif rejected >= 3:
        score *= 0.5
        notes.append(f"Rejected {rejected} times previously — reduced priority")

    if approved > 0 and successful > 0:
        boost = min(1.5, 1.0 + (successful * 0.1))
        score *= boost
        impact = min(10, impact + 1)
        notes.append(f"Prior success on similar items ({successful} successful) — increased confidence")

    if unsuccessful >= 2:
        score *= 0.7
        notes.append(f"Similar actions failed {unsuccessful} times — reduced priority")

    item = dict(item)
    item["priority_score"] = round(score, 2)
    item["impact"] = impact
    if notes:
        item["decision_context"] = "; ".join(notes)
    return apply_initiative_confidence_adjustments(item)


def generate_lessons_learned(history_index: dict[str, dict[str, Any]] | None = None) -> list[str]:
    """Generate human-readable lessons from decision history."""
    index = history_index or get_decision_history_index()
    lessons: list[str] = []

    for entry in sorted(index.values(), key=lambda e: e.get("total", 0), reverse=True):
        label = entry.get("label") or "Recommendation"
        approved = int(entry.get("approved") or 0)
        rejected = int(entry.get("rejected") or 0)
        successful = int(entry.get("successful") or 0)
        unsuccessful = int(entry.get("unsuccessful") or 0)
        total = int(entry.get("total") or 0)

        if successful >= 2 and approved > 0:
            rate = round(successful / max(approved, 1) * 100)
            lessons.append(f"{label} has solved {successful} similar finding(s) ({rate}% success rate).")
        elif rejected >= 5:
            lessons.append(f"{label} has been rejected {rejected} times — consider deprioritizing.")
        elif rejected >= 3:
            lessons.append(f"{label} has been ignored {rejected} times.")
        elif unsuccessful >= 2:
            lessons.append(f"{label} failed {unsuccessful} time(s) — review approach before retrying.")
        elif total >= 3 and rejected > approved:
            lessons.append(f"{label} is frequently deferred or rejected ({rejected}/{total} decisions).")

    if not lessons:
        lessons.append("No decision history yet — record approvals and rejections to build institutional memory.")

    return lessons[:8]


def count_repeated_findings(history_index: dict[str, dict[str, Any]] | None = None) -> int:
    """Count recommendation types that keep recurring across decisions."""
    index = history_index or get_decision_history_index()
    count = 0
    for entry in index.values():
        total = int(entry.get("total") or 0)
        rejected = int(entry.get("rejected") or 0)
        if total >= 3 or rejected >= 2:
            count += 1
    return count


def get_decision_analytics() -> dict[str, Any]:
    """Compute decision intelligence metrics for dashboard and reports."""
    decisions = list_all_decisions()
    history_index = get_decision_history_index()

    approved = sum(1 for d in decisions if str(d.get("decision")) == "approved")
    rejected = sum(1 for d in decisions if str(d.get("decision")) == "rejected")
    deferred = sum(1 for d in decisions if str(d.get("decision")) == "deferred")

    successful = sum(1 for d in decisions if str(d.get("outcome")) == "successful")
    unsuccessful = sum(1 for d in decisions if str(d.get("outcome")) == "unsuccessful")
    partial = sum(1 for d in decisions if str(d.get("outcome")) == "partial")
    unknown = sum(1 for d in decisions if str(d.get("outcome")) == "unknown")

    reviewed_outcomes = successful + unsuccessful + partial
    decision_success_rate = round(successful / reviewed_outcomes * 100, 1) if reviewed_outcomes > 0 else 0.0

    rejected_counter: Counter[str] = Counter()
    success_counter: Counter[str] = Counter()

    for decision in decisions:
        label = _recommendation_label(decision)
        dtype = str(decision.get("decision") or "")
        outcome = str(decision.get("outcome") or "")
        if dtype == "rejected":
            rejected_counter[label] += 1
        if outcome == "successful":
            success_counter[label] += 1

    most_rejected = rejected_counter.most_common(1)
    most_successful = success_counter.most_common(1)

    initiative_index = get_initiative_outcome_index()
    initiative_lessons: list[str] = []
    for entry in sorted(initiative_index.values(), key=lambda e: e.get("total", 0), reverse=True):
        label = entry.get("label") or "Initiative"
        completed = int(entry.get("completed") or 0)
        failed = int(entry.get("failed") or 0)
        if completed >= 2:
            initiative_lessons.append(f"{label} completed successfully {completed} time(s) — high confidence.")
        elif failed >= 2:
            initiative_lessons.append(f"{label} failed or stalled {failed} time(s) — lower confidence.")

    objective_analytics: dict[str, Any] = {}
    try:
        from app.jarvis.mvp.objective_analytics import get_objective_analytics

        objective_analytics = get_objective_analytics()
    except Exception:
        objective_analytics = {}

    return {
        "decision_success_rate": decision_success_rate,
        "approved_count": approved,
        "rejected_count": rejected,
        "deferred_count": deferred,
        "successful_outcomes": successful,
        "failed_outcomes": unsuccessful,
        "partial_outcomes": partial,
        "unknown_outcomes": unknown,
        "total_decisions": len(decisions),
        "most_common_rejected_recommendation": most_rejected[0][0] if most_rejected else None,
        "most_common_rejected_count": most_rejected[0][1] if most_rejected else 0,
        "most_successful_recommendation_type": most_successful[0][0] if most_successful else None,
        "most_successful_count": most_successful[0][1] if most_successful else 0,
        "repeated_findings_count": count_repeated_findings(history_index),
        "lessons_learned": generate_lessons_learned(history_index) + initiative_lessons[:3],
        "initiative_outcomes": {
            "tracked_initiatives": len(initiative_index),
            "completed_initiatives": sum(int(e.get("completed") or 0) for e in initiative_index.values()),
            "failed_initiatives": sum(int(e.get("failed") or 0) for e in initiative_index.values()),
        },
        "objective_outcomes": objective_analytics,
        "read_only": True,
    }
