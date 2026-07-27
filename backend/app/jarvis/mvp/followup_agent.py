"""Follow-up Agent — detects stale, overdue, and blocked management items.

Read-only detection only. No autonomous execution, AWS writes, trades,
or infrastructure changes. Generates reminders for human review.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.jarvis.mvp.action_plan_persistence import list_action_plans
from app.jarvis.mvp.audit_persistence import list_audit_runs
from app.jarvis.mvp.crypto_audit_persistence import list_crypto_audit_runs
from app.jarvis.mvp.decision_analytics import get_decision_history_index
from app.jarvis.mvp.decision_persistence import list_all_decisions
from app.jarvis.mvp.followup_persistence import (
    dismiss_legacy_day_count_followup_churn,
    upsert_followup,
)
from app.jarvis.mvp.initiative_persistence import (
    is_initiative_overdue,
    is_initiative_stalled,
    list_all_initiatives,
)

STALE_INITIATIVE_DAYS = 14
PENDING_PLAN_DAYS = 7
MISSING_OUTCOME_DAYS = 14
STALE_AUDIT_DAYS = 7
RECURRING_THRESHOLD = 3


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def _days_since(value: str | datetime | None) -> int | None:
    dt = value if isinstance(value, datetime) else _parse_iso(value)
    if dt is None:
        return None
    return (datetime.now(timezone.utc) - dt).days


def _priority_to_severity(priority: str) -> str:
    mapping = {"critical": "critical", "high": "high", "medium": "medium", "low": "low"}
    return mapping.get(str(priority or "").lower(), "medium")


def _detect_initiative_followups() -> list[str]:
    """Rules 1-3: overdue, stale, and blocked initiatives.

    Each rule uses a stable source_id suffix so day-count churn cannot open a
    new row, while blocked/overdue/stale for the same initiative stay distinct.
    """
    created: list[str] = []
    today = datetime.now(timezone.utc).date()

    for initiative in list_all_initiatives():
        iid = initiative["initiative_id"]
        title = initiative.get("title") or "Untitled initiative"
        status = str(initiative.get("status") or "").lower()
        owner = initiative.get("owner")
        priority = str(initiative.get("priority") or "medium")
        target_date = initiative.get("target_date")

        if status in ("completed", "cancelled"):
            continue

        if status == "blocked":
            reason = initiative.get("blocked_reason") or "no reason provided"
            fid = upsert_followup(
                source_type="initiative",
                source_id=f"{iid}:blocked",
                title=f"{title} is blocked.",
                description=f"Blocked initiative requires attention: {reason}",
                severity=_priority_to_severity(priority) if priority in ("critical", "high") else "high",
                due_date=target_date,
                assigned_to=owner,
            )
            created.append(fid)

        if is_initiative_overdue(initiative):
            days_overdue = int(initiative.get("days_overdue") or 0)
            if days_overdue <= 0 and target_date:
                try:
                    target = date.fromisoformat(str(target_date)[:10])
                    days_overdue = (today - target).days
                except ValueError:
                    days_overdue = 0
            fid = upsert_followup(
                source_type="initiative",
                source_id=f"{iid}:overdue",
                title=f"{title} is overdue.",
                description=(
                    f"Initiative target date {target_date} has passed "
                    f"({days_overdue} day(s) overdue)."
                ),
                severity="critical" if days_overdue >= 7 else _priority_to_severity(priority),
                due_date=target_date,
                assigned_to=owner,
            )
            created.append(fid)

        if is_initiative_stalled(initiative):
            days_stale = _days_since(initiative.get("updated_at")) or STALE_INITIATIVE_DAYS
            fid = upsert_followup(
                source_type="initiative",
                source_id=f"{iid}:stale",
                title=f"{title} has had no recent update.",
                description=(
                    f"Active initiative appears stale — no update in {days_stale}+ days. "
                    "Review progress or update status."
                ),
                severity="medium",
                due_date=target_date,
                assigned_to=owner,
            )
            created.append(fid)

    return created


def _detect_action_plan_followups() -> list[str]:
    """Rule 4: proposed action plans older than 7 days."""
    created: list[str] = []
    for plan in list_action_plans(limit=100):
        if str(plan.get("status")) != "proposed":
            continue
        age = _days_since(plan.get("created_at"))
        if age is None or age < PENDING_PLAN_DAYS:
            continue

        plan_id = plan["plan_id"]
        short_id = plan_id[:8]
        title = f"Action plan {short_id} is still awaiting review."
        severity = str(plan.get("severity") or "medium").lower()
        fid = upsert_followup(
            source_type="action_plan",
            source_id=plan_id,
            title=title,
            description=(
                f"Proposed action plan from {plan.get('source_type')} "
                f"has been pending review for {age} days."
            ),
            severity=severity if severity in ("low", "medium", "high", "critical") else "medium",
            assigned_to=None,
        )
        created.append(fid)
    return created


def _detect_decision_followups() -> list[str]:
    """Rule 5: approved decisions with unknown outcome after 14 days."""
    created: list[str] = []
    for decision in list_all_decisions():
        if str(decision.get("decision")) != "approved":
            continue
        if str(decision.get("outcome")) != "unknown":
            continue

        reviewed_at = decision.get("reviewed_at") or decision.get("created_at")
        age = _days_since(reviewed_at)
        if age is None or age < MISSING_OUTCOME_DAYS:
            continue

        did = decision["decision_id"]
        reason = decision.get("decision_reason") or "approved recommendation"
        title = f"Approved decision {did[:8]} still has unknown outcome."
        fid = upsert_followup(
            source_type="decision",
            source_id=did,
            title=title,
            description=(
                f"Decision approved {age} days ago ({reason}) — "
                "outcome has not been recorded."
            ),
            severity="medium",
            assigned_to=decision.get("reviewed_by"),
        )
        created.append(fid)
    return created


def _detect_audit_followups() -> list[str]:
    """Rule 6: no AWS or crypto audit in 7 days.

    Uses stable source_ids so age advancing by one day does not open a new row.
    """
    created: list[str] = []

    aws_audits = list_audit_runs(limit=1)
    if not aws_audits:
        fid = upsert_followup(
            source_type="aws_audit",
            source_id="aws_audit",
            title="AWS audit has not been run recently.",
            description="No AWS infrastructure audit on record — schedule a read-only audit.",
            severity="high",
        )
        created.append(fid)
    else:
        age = _days_since(aws_audits[0].get("created_at"))
        if age is None or age >= STALE_AUDIT_DAYS:
            age_label = "unknown" if age is None else str(age)
            fid = upsert_followup(
                source_type="aws_audit",
                source_id="aws_audit",
                title="AWS audit has not been rerun recently.",
                description=(
                    f"Infrastructure audit data may be stale — last run {age_label} days ago. "
                    "Rerun read-only AWS audit."
                ),
                severity="high" if (age or 0) >= 14 else "medium",
            )
            created.append(fid)

    crypto_audits = list_crypto_audit_runs(limit=1)
    if not crypto_audits:
        fid = upsert_followup(
            source_type="crypto_audit",
            source_id="crypto_audit",
            title="Crypto audit has not been run recently.",
            description="No crypto portfolio audit on record — schedule a read-only audit.",
            severity="high",
        )
        created.append(fid)
    else:
        age = _days_since(crypto_audits[0].get("created_at"))
        if age is None or age >= STALE_AUDIT_DAYS:
            age_label = "unknown" if age is None else str(age)
            fid = upsert_followup(
                source_type="crypto_audit",
                source_id="crypto_audit",
                title="Crypto audit has not been rerun recently.",
                description=(
                    f"Portfolio audit data may be stale — last run {age_label} days ago. "
                    "Rerun read-only crypto audit."
                ),
                severity="high" if (age or 0) >= 14 else "medium",
            )
            created.append(fid)

    return created


def _detect_recurring_findings() -> list[str]:
    """Rule 7: same recommendation 3+ times without successful outcome."""
    created: list[str] = []
    history = get_decision_history_index()

    for key, entry in history.items():
        total = int(entry.get("total") or 0)
        rejected = int(entry.get("rejected") or 0)
        successful = int(entry.get("successful") or 0)

        if successful > 0:
            continue
        if rejected < RECURRING_THRESHOLD and total < RECURRING_THRESHOLD:
            continue

        label = entry.get("label") or key
        count = max(rejected, total)
        if rejected >= RECURRING_THRESHOLD:
            title = f"{label} keeps being rejected."
            description = (
                f"Recurring finding rejected {rejected} times without successful outcome "
                f"({count} decision(s) recorded). Decide whether to deprioritize permanently."
            )
        else:
            title = f"{label} keeps recurring without success."
            description = (
                f"Recurring finding: {count} decision(s) recorded, "
                f"{rejected} rejected, {successful} successful."
            )

        fid = upsert_followup(
            source_type="decision_pattern",
            source_id=key[:64],
            title=title,
            description=description,
            severity="high" if rejected >= RECURRING_THRESHOLD else "medium",
        )
        created.append(fid)

    return created


def detect_followups() -> dict[str, Any]:
    """
    Run all follow-up detection rules and upsert reminders.

    Returns summary of created/updated follow-up IDs.
    """
    created_ids: list[str] = []
    legacy_dismissed = 0
    try:
        legacy_dismissed = dismiss_legacy_day_count_followup_churn()
    except Exception as exc:
        from app.jarvis.mvp.followup_persistence import logger

        logger.warning("legacy followup churn cleanup failed: %s", exc)

    for detector in (
        _detect_initiative_followups,
        _detect_action_plan_followups,
        _detect_decision_followups,
        _detect_audit_followups,
        _detect_recurring_findings,
    ):
        try:
            created_ids.extend(detector())
        except Exception as exc:
            from app.jarvis.mvp.followup_persistence import logger

            logger.warning("followup detection failed for %s: %s", detector.__name__, exc)

    unique_ids = list(dict.fromkeys(created_ids))
    return {
        "followups_touched": len(unique_ids),
        "followup_ids": unique_ids,
        "legacy_duplicates_dismissed": legacy_dismissed,
        "read_only": True,
        "execution_performed": False,
    }
