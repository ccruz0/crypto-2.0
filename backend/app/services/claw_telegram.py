"""
ATP Control Telegram client — routes task-system and orchestration messages to ATP Control bot.

Routing (per TELEGRAM_ROUTING_AUDIT.md):
- ATP Control (@ATP_control_bot) = tasks, investigations, approvals, needs revision, agent logs
- Claw (@Claw_cruz_bot) = control plane, user commands, /task /help (responses go to user chat)
- ATP Alerts = trading (via telegram_notifier)
- AWS Alerts = infra (via telegram_notifier chat_destination=ops)

Message tagging: [TASK], [INVESTIGATION], [PATCH], [ERROR]
"""

from __future__ import annotations

import logging
import os
from typing import Any, Literal, Optional

logger = logging.getLogger(__name__)

TELEGRAM_TEXT_LIMIT = 4096

MessageType = Literal["TASK", "INVESTIGATION", "PATCH", "ERROR"]


def _get_claw_bot_token() -> str:
    """ATP Control bot token. Prefer TELEGRAM_ATP_CONTROL_BOT_TOKEN, fallback CLAW, then generic."""
    return (
        (os.environ.get("TELEGRAM_ATP_CONTROL_BOT_TOKEN")
         or os.environ.get("TELEGRAM_CLAW_BOT_TOKEN")
         or os.environ.get("TELEGRAM_BOT_TOKEN")
         or "").strip()
    )


def _get_claw_chat_id() -> str:
    """ATP Control chat ID. Prefer TELEGRAM_ATP_CONTROL_CHAT_ID, fallback CLAW, then generic."""
    return (
        (os.environ.get("TELEGRAM_ATP_CONTROL_CHAT_ID")
         or os.environ.get("TELEGRAM_CLAW_CHAT_ID")
         or os.environ.get("TELEGRAM_CHAT_ID")
         or "").strip()
    )


def _ensure_tag(text: str, message_type: MessageType) -> str:
    """Ensure message starts with [message_type] tag."""
    tag = f"[{message_type}]"
    if not text.strip().startswith(tag):
        return f"{tag} {text.strip()}"
    return text


def send_claw_message(
    message: str,
    message_type: str = "TASK",
    source_module: str = "",
    reply_markup: Optional[dict[str, Any]] = None,
) -> tuple[bool, Optional[int]]:
    """
    Send a message to the Claw Telegram bot (task-system channel).

    Args:
        message: Message text (HTML supported)
        message_type: [TASK], [INVESTIGATION], [PATCH], or [ERROR]
        source_module: Caller module for logging (e.g. agent_telegram_approval, notion_env)
        reply_markup: Optional inline keyboard

    Returns:
        (success: bool, message_id: int | None)
    """
    token = _get_claw_bot_token()
    chat_id = _get_claw_chat_id()
    if not token or not chat_id:
        logger.warning(
            "[TELEGRAM_ROUTE] category=DEV destination=ATP_CONTROL missing_config=True "
            "source_module=%s message_type=%s hint=set TELEGRAM_ATP_CONTROL_BOT_TOKEN and TELEGRAM_ATP_CONTROL_CHAT_ID",
            source_module, message_type,
        )
        return False, None

    text = _ensure_tag(message, message_type)
    if len(text) > TELEGRAM_TEXT_LIMIT:
        text = text[: TELEGRAM_TEXT_LIMIT - 3] + "..."

    try:
        from app.utils.http_client import http_post
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        r = http_post(url, json=payload, timeout=10, calling_module="claw_telegram")
        if r.status_code != 200:
            logger.warning(
                "claw_telegram send failed status=%s body=%s source_module=%s message_type=%s",
                r.status_code, (r.text or "")[:200], source_module, message_type,
            )
            return False, None
        data = r.json()
        if not data.get("ok"):
            return False, None
        result = data.get("result") or {}
        msg_id = result.get("message_id")
        chat_id_masked = "****" + chat_id[-4:] if len(chat_id) > 4 else "****"
        logger.info(
            "[TELEGRAM_ROUTE] category=DEV destination=ATP_CONTROL bot=ATP_control_bot "
            "message_type=%s source_module=%s sent=True message_id=%s chat_id_last4=%s",
            message_type, source_module, msg_id, chat_id_masked,
        )
        return True, msg_id
    except Exception as e:
        logger.exception(
            "claw_telegram send failed source_module=%s message_type=%s: %s",
            source_module, message_type, e,
        )
        return False, None
