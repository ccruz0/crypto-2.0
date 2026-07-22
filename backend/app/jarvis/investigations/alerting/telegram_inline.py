"""Inline Telegram UX for Jarvis investigation alert CTAs.

Callback payloads use prefix ``jia:`` (<= 64 bytes with ``alert-<12 hex>`` ids):
  ``jia:v:<alert_id>`` view investigation / alert detail (read-only)
  ``jia:t:<alert_id>`` create ACW task (dry-run proposal or queued task; never applies)
  ``jia:s:<alert_id>`` snooze 24h (suppress Telegram for this fingerprint)

Security: reuses Jarvis Telegram allowlists (same cohort as ``/mission``).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Callable

from app.jarvis.telegram_control import (
    actor_from_telegram_user,
    is_jarvis_telegram_enabled,
    jarvis_allowlists_configured,
    jarvis_telegram_allowed,
    jarvis_telegram_token_present,
)

logger = logging.getLogger(__name__)

JARVIS_INVESTIGATION_ALERT_CALLBACK_PREFIX = "jia:"
DEFAULT_SNOOZE_HOURS = 24

SendFn = Callable[[str], None]


def _jarvis_alert_gate_ok(chat_id: str, actor_user_id: str) -> bool:
    if not is_jarvis_telegram_enabled():
        return False
    if not jarvis_telegram_token_present():
        return False
    if not jarvis_allowlists_configured():
        return False
    return jarvis_telegram_allowed(chat_id, actor_user_id)


def _parse_alert_callback(callback_data: str) -> tuple[str, str] | None:
    raw = (callback_data or "").strip()
    if not raw.startswith(JARVIS_INVESTIGATION_ALERT_CALLBACK_PREFIX):
        return None
    rest = raw[len(JARVIS_INVESTIGATION_ALERT_CALLBACK_PREFIX) :]
    if len(rest) < 3 or rest[1] != ":":
        return None
    op, alert_id = rest[0], rest[2:].strip()
    if op not in ("v", "t", "s") or not alert_id:
        return None
    return op, alert_id


def _format_view_detail(alert: Any, investigation: dict[str, Any] | None) -> str:
    evidence_count = len(getattr(alert, "evidence", None) or [])
    lines = [
        "JARVIS ALERT DETAIL",
        "",
        f"Alert: {alert.alert_id}",
        f"Severity: {alert.severity}",
        f"Status: {alert.status}",
        f"Type: {alert.source}",
        f"Occurrences: {alert.occurrence_count}",
        f"Investigation: {alert.investigation_id or 'n/a'}",
        f"Evidence items: {evidence_count}",
        "",
        f"Summary: {(alert.summary or '')[:600]}",
    ]
    if investigation:
        root = (investigation.get("root_cause") or "").strip()
        fix = (investigation.get("recommended_fix") or "").strip()
        nxt = (investigation.get("next_action") or "").strip()
        conf = investigation.get("confidence")
        if root:
            lines.extend(["", f"Root cause: {root[:400]}"])
        if conf is not None:
            lines.append(f"Confidence: {conf}")
        if fix:
            lines.append(f"Recommended fix: {fix[:400]}")
        if nxt:
            lines.append(f"Next action: {nxt[:400]}")
        proposal = (investigation.get("proposal_status") or "").strip()
        proposal_task = (investigation.get("proposal_task_id") or "").strip()
        if proposal or proposal_task:
            lines.append(f"Proposal: {proposal or 'n/a'} ({proposal_task or 'no task'})")
    lines.extend(
        [
            "",
            "Read-only detail — no production writes.",
            "Dashboard: Jarvis → Alerts (acknowledge / resolve there if needed).",
        ]
    )
    return "\n".join(lines)


def _create_acw_task_for_alert(alert: Any, *, actor: str) -> str:
    """Create a human-gated ACW task from the alert's investigation. Never applies patches."""
    inv_id = (alert.investigation_id or "").strip()
    if not inv_id:
        return (
            "No se puede crear tarea: esta alerta no tiene investigation_id.\n"
            f"Alert: {alert.alert_id}"
        )

    from app.jarvis.investigations.persistence import get_investigation

    investigation = get_investigation(inv_id)
    if investigation is None:
        return f"Investigation no encontrada: {inv_id}\nAlert: {alert.alert_id}"

    existing_task = (investigation.get("proposal_task_id") or "").strip()
    existing_status = (investigation.get("proposal_status") or "").strip()
    if existing_status == "no_fix_required":
        return (
            "Esta investigación ya se evaluó: no_fix_required (fix ya en el repo).\n"
            f"Task: {existing_task or 'n/a'}\n"
            f"Investigation: {inv_id}\n"
            "No se re-ejecuta el proposal. Considera Snooze 24h si el ruido continúa."
        )
    if existing_task and existing_status in (
        "proposing",
        "waiting_for_approval",
        "proposed",
        "ready",
        "queued_from_telegram",
    ):
        return (
            "Ya hay una tarea ACW vinculada a esta investigación.\n"
            f"Task: {existing_task}\n"
            f"Status: {existing_status}\n"
            f"Investigation: {inv_id}\n"
            "No se creó otra. Revisa Approval Center / Jarvis tasks."
        )

    fallback_note = "Creando tarea dry-run en cola."

    # Prefer Phase 4B proposal workflow (sandbox + approval gate; no prod apply).
    try:
        from app.jarvis.proposals.config import jarvis_4b_proposals_enabled
        from app.jarvis.proposals.proposal_service import ProposalWorkflowError, submit_patch_proposal

        if jarvis_4b_proposals_enabled():
            detail = submit_patch_proposal(inv_id)
            task_id = str(detail.get("task_id") or "").strip() or "unknown"
            status = str(detail.get("status") or "").strip()
            refreshed = get_investigation(inv_id) or {}
            if (refreshed.get("proposal_status") or "") == "no_fix_required":
                return (
                    "Tarea ACW evaluada: el fix ya está en el repo (no_fix_required).\n"
                    f"Task: {task_id}\n"
                    f"Investigation: {inv_id}\n"
                    "No hay patch que aplicar. Considera Snooze 24h si el ruido continúa."
                )
            return (
                "Tarea ACW creada (dry-run / approval gate).\n"
                f"Task: {task_id}\n"
                f"Status: {status or 'queued'}\n"
                f"Investigation: {inv_id}\n"
                f"Actor: {actor}\n"
                "Ningún cambio se aplicó en producción."
            )
        fallback_note = "Proposals deshabilitadas. Creando tarea dry-run en cola."
    except ProposalWorkflowError as exc:
        logger.info(
            "jia.create_task proposal_not_eligible alert_id=%s inv=%s reasons=%s",
            alert.alert_id,
            inv_id,
            getattr(exc, "reasons", None),
        )
        reasons = ", ".join(exc.reasons) if getattr(exc, "reasons", None) else exc.message
        fallback_note = f"Proposal no elegible ({reasons}). Creando tarea dry-run en cola."
    except Exception as exc:
        logger.warning(
            "jia.create_task proposal_failed alert_id=%s inv=%s err=%s",
            alert.alert_id,
            inv_id,
            exc,
        )
        fallback_note = f"Proposal falló ({exc!s}). Creando tarea dry-run en cola."

    from app.jarvis.execution.persistence import create_execution_task
    from app.jarvis.investigations.persistence import update_investigation_proposal_linkage

    recommended = (investigation.get("recommended_fix") or "").strip()
    root = (investigation.get("root_cause") or "").strip()
    objective = (
        f"ACW follow-up from alert {alert.alert_id}: "
        f"{root or alert.title or alert.source}. "
        f"Recommended: {recommended or 'review investigation evidence'}."
    )[:2000]
    task_id = str(uuid.uuid4())
    create_execution_task(
        task_id=task_id,
        objective=objective,
        priority="normal",
        dry_run=True,
        approval_required=True,
        approval_status="pending",
    )
    update_investigation_proposal_linkage(
        inv_id,
        proposal_task_id=task_id,
        proposal_status="queued_from_telegram",
    )
    return (
        f"{fallback_note}\n"
        f"Task: {task_id}\n"
        f"Investigation: {inv_id}\n"
        f"Actor: {actor}\n"
        "Dry-run + approval_required — ningún cambio en producción."
    )


def _snooze_alert(alert_id: str, *, hours: int = DEFAULT_SNOOZE_HOURS) -> str:
    from app.jarvis.investigations.alerting.persistence import snooze_alert

    record = snooze_alert(alert_id, hours=hours)
    if record is None:
        return f"No encontré la alerta {alert_id}."
    until = (record.snoozed_until or "").strip() or "n/a"
    return (
        f"Alerta silenciada {hours}h.\n"
        f"Alert: {record.alert_id}\n"
        f"Fingerprint: {record.fingerprint[:16]}…\n"
        f"Snoozed until: {until}\n"
        "No se reenviará por Telegram mientras dure el snooze "
        "(sí se registran ocurrencias)."
    )


def handle_jarvis_investigation_alert_callback(
    *,
    chat_id: str,
    user_id: str,
    from_user: dict[str, Any] | None,
    callback_data: str,
    send: SendFn,
) -> bool:
    """
    Handle ``jia:*`` inline callbacks. Returns True when consumed (including errors).
    """
    parsed = _parse_alert_callback(callback_data)
    if not parsed:
        return False

    if not _jarvis_alert_gate_ok(chat_id, user_id):
        send(
            "⛔ Acciones de alerta no permitidas: este chat o usuario no está en la lista "
            "(mismas reglas que /mission)."
        )
        return True

    op, alert_id = parsed
    from app.jarvis.investigations.alerting.persistence import get_alert

    alert = get_alert(alert_id)
    if alert is None:
        send(f"No encontré la alerta: {alert_id}")
        return True

    actor = actor_from_telegram_user(from_user)

    if op == "v":
        investigation = None
        inv_id = (alert.investigation_id or "").strip()
        if inv_id:
            try:
                from app.jarvis.investigations.persistence import get_investigation

                investigation = get_investigation(inv_id)
            except Exception as exc:
                logger.warning("jia.view investigation_load_failed inv=%s err=%s", inv_id, exc)
        send(_format_view_detail(alert, investigation))
        return True

    if op == "t":
        try:
            send(_create_acw_task_for_alert(alert, actor=actor))
        except Exception as exc:
            logger.exception("jia.create_task failed alert_id=%s", alert_id)
            send(f"❌ Error al crear tarea ACW: {exc!s}"[:500])
        return True

    if op == "s":
        try:
            send(_snooze_alert(alert_id, hours=DEFAULT_SNOOZE_HOURS))
        except Exception as exc:
            logger.exception("jia.snooze failed alert_id=%s", alert_id)
            send(f"❌ Error al silenciar alerta: {exc!s}"[:500])
        return True

    return False
