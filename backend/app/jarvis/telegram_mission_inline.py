"""Inline Telegram UX for autonomous Jarvis missions (callbacks + pending reply).

Callback payloads use prefix ``jm:`` (<= 64 bytes with standard Notion UUID page ids):
  ``jm:a:<mission_id>`` approve
  ``jm:r:<mission_id>`` reject (audited default reason)
  ``jm:i:<mission_id>`` start reply flow (ForceReply + pending capture)
  ``jm:d:<mission_id>`` view details (status summary)

Security: reuses Jarvis Telegram allowlists (same cohort as ``/mission``).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from app.jarvis.autonomous_orchestrator import handle_mission_command
from app.jarvis.autonomous_schemas import (
    MISSION_STATUS_WAITING_FOR_APPROVAL,
    MISSION_STATUS_WAITING_FOR_INPUT,
)
from app.jarvis.telegram_control import (
    actor_from_telegram_user,
    format_compact_jarvis_reply,
    is_jarvis_telegram_enabled,
    jarvis_allowlists_configured,
    jarvis_telegram_allowed,
    jarvis_telegram_token_present,
)

logger = logging.getLogger(__name__)

JARVIS_MISSION_CALLBACK_PREFIX = "jm:"

PENDING_JARVIS_MISSION_INPUT: dict[str, dict[str, Any]] = {}
PENDING_JARVIS_MISSION_INPUT_TTL_SECONDS = 900.0

SendFn = Callable[[str], None]


def _pending_key(chat_id: str, user_id: str) -> str:
    return f"{chat_id}:{user_id}"


def _purge_stale_pending() -> None:
    now = time.time()
    dead: list[str] = []
    for k, row in PENDING_JARVIS_MISSION_INPUT.items():
        ts = float(row.get("ts") or 0.0)
        if not ts or (now - ts) > PENDING_JARVIS_MISSION_INPUT_TTL_SECONDS:
            dead.append(k)
    for k in dead:
        PENDING_JARVIS_MISSION_INPUT.pop(k, None)


def register_pending_jarvis_mission_input(chat_id: str, user_id: str, mission_id: str) -> None:
    _purge_stale_pending()
    PENDING_JARVIS_MISSION_INPUT[_pending_key(chat_id, user_id)] = {
        "mission_id": (mission_id or "").strip(),
        "ts": time.time(),
    }


def clear_pending_jarvis_mission_input(chat_id: str, user_id: str) -> None:
    PENDING_JARVIS_MISSION_INPUT.pop(_pending_key(chat_id, user_id), None)


def _jarvis_mission_gate_ok(chat_id: str, actor_user_id: str) -> bool:
    if not is_jarvis_telegram_enabled():
        return False
    if not jarvis_telegram_token_present():
        return False
    if not jarvis_allowlists_configured():
        return False
    return jarvis_telegram_allowed(chat_id, actor_user_id)


def try_consume_pending_jarvis_mission_input(
    *,
    raw_text: str,
    chat_id: str,
    actor_user_id: str,
    from_user: dict[str, Any] | None,
    send: SendFn,
) -> bool:
    """
    If the operator has a pending mission reply, treat this non-command line as
    ``/mission input <id> <text>``.
    """
    text = (raw_text or "").strip()
    if not text or text.startswith("/"):
        return False
    _purge_stale_pending()
    key = _pending_key(chat_id, actor_user_id)
    row = PENDING_JARVIS_MISSION_INPUT.get(key)
    if not row:
        return False
    if not _jarvis_mission_gate_ok(chat_id, actor_user_id):
        return False
    mission_id = str(row.get("mission_id") or "").strip()
    if not mission_id:
        PENDING_JARVIS_MISSION_INPUT.pop(key, None)
        return False
    actor = actor_from_telegram_user(from_user)
    try:
        payload = handle_mission_command(
            raw_args=f"input {mission_id} {text}",
            actor=actor,
            chat_id=chat_id,
        )
        reply = format_compact_jarvis_reply("jarvis", dict(payload))
        send(reply)
    except Exception as e:
        logger.exception("jarvis.mission.pending_input_failed mission_id=%s", mission_id)
        send(f"❌ Error al enviar la respuesta a la misión: {e!s}"[:500])
    finally:
        PENDING_JARVIS_MISSION_INPUT.pop(key, None)
    return True


def _parse_mission_callback(callback_data: str) -> tuple[str, str] | None:
    raw = (callback_data or "").strip()
    if not raw.startswith(JARVIS_MISSION_CALLBACK_PREFIX):
        return None
    rest = raw[len(JARVIS_MISSION_CALLBACK_PREFIX) :]
    if len(rest) < 3 or rest[1] != ":":
        return None
    op, mission_id = rest[0], rest[2:].strip()
    if op not in ("a", "r", "i", "d") or not mission_id:
        return None
    return op, mission_id


def handle_jarvis_mission_telegram_callback(
    *,
    chat_id: str,
    user_id: str,
    from_user: dict[str, Any] | None,
    callback_data: str,
    send: SendFn,
) -> bool:
    """
    Handle ``jm:*`` inline callbacks. Returns True when consumed (including errors).
    """
    parsed = _parse_mission_callback(callback_data)
    if not parsed:
        return False
    op, mission_id = parsed
    if not _jarvis_mission_gate_ok(chat_id, user_id):
        send("⛔ Acciones de misión no permitidas: este chat o usuario no está en la lista (mismas reglas que /mission).")
        return True

    actor = actor_from_telegram_user(from_user)
    from app.jarvis.notion_mission_service import NotionMissionService

    notion = NotionMissionService()
    mission = notion.get_mission(mission_id) if notion.configured() else None

    if op == "d":
        payload = handle_mission_command(raw_args=f"status {mission_id}", actor=actor, chat_id=chat_id)
        send(format_compact_jarvis_reply("jarvis", dict(payload)))
        return True

    if mission is None:
        send(f"No encontré esa misión en Notion (id registrado para auditoría): {mission_id}")
        return True

    status = str(mission.get("status") or "").strip().lower()

    if op == "a":
        if status != MISSION_STATUS_WAITING_FOR_APPROVAL:
            send(
                "Solo puedes aprobar cuando la misión está pendiente de tu visto bueno. "
                f"Estado actual: {status or 'desconocido'}. Pulsa «Ver detalle» para el estado más reciente."
            )
            return True
        payload = handle_mission_command(raw_args=f"approve {mission_id}", actor=actor, chat_id=chat_id)
        send(format_compact_jarvis_reply("jarvis", dict(payload)))
        return True

    if op == "r":
        if status != MISSION_STATUS_WAITING_FOR_APPROVAL:
            send(
                "Solo puedes rechazar cuando la misión está pendiente de aprobación. "
                f"Estado actual: {status or 'desconocido'}."
            )
            return True
        reason = "telegram_inline_reject"
        payload = handle_mission_command(
            raw_args=f"reject {mission_id} {reason}",
            actor=actor,
            chat_id=chat_id,
        )
        send(format_compact_jarvis_reply("jarvis", dict(payload)))
        return True

    if op == "i":
        if status != MISSION_STATUS_WAITING_FOR_INPUT:
            send(
                "Responder solo aplica cuando la misión espera tu respuesta. "
                f"Estado actual: {status or 'desconocido'}."
            )
            return True
        register_pending_jarvis_mission_input(chat_id, user_id, mission_id)
        from app.services.telegram_commands import send_telegram_message_with_markup

        force = {
            "force_reply": True,
            "input_field_placeholder": "Tu respuesta…",
            "selective": True,
        }
        body = (
            "Escribe la respuesta como mensaje normal en este chat (equivalente a /mission input).\n\n"
            f"Referencia interna (soporte / logs): {mission_id}\n\n"
            "Si prefieres, sigue valiendo /mission input con el id."
        )
        ok = send_telegram_message_with_markup(
            chat_id,
            body,
            reply_markup=force,
            parse_mode=None,
        )
        if not ok:
            send(
                "No pude abrir el cuadro de respuesta; usa:\n"
                f"/mission input {mission_id} <tu respuesta>"
            )
        return True

    return False
