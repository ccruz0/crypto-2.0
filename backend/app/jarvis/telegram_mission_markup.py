"""Inline keyboard markup for Jarvis missions (no orchestrator imports — avoids cycles)."""

from __future__ import annotations

import os
from typing import Any, Literal

MissionInlineMode = Literal["input", "approval", "details_only"]


def build_jarvis_mission_inline_markup(mission_id: str, mode: MissionInlineMode) -> dict[str, Any]:
    """
    Inline keyboard for mission actions. Callback data must stay <= 64 bytes (Telegram limit).
    Optional Web App row when JARVIS_TELEGRAM_WEBAPP_URL is set (future structured forms).
    """
    mid = (mission_id or "").strip()
    rows: list[list[dict[str, Any]]] = []
    if mode == "input":
        rows.append(
            [
                {"text": "💬 Responder", "callback_data": f"jm:i:{mid}"},
                {"text": "📋 Ver detalle", "callback_data": f"jm:d:{mid}"},
            ]
        )
    elif mode == "approval":
        rows.append(
            [
                {"text": "✅ Aprobar", "callback_data": f"jm:a:{mid}"},
                {"text": "❌ Rechazar", "callback_data": f"jm:r:{mid}"},
            ]
        )
        rows.append([{"text": "📋 Ver detalle", "callback_data": f"jm:d:{mid}"}])
    else:
        rows.append([{"text": "📋 Ver detalle", "callback_data": f"jm:d:{mid}"}])

    webapp_url = (os.getenv("JARVIS_TELEGRAM_WEBAPP_URL") or "").strip()
    if webapp_url and mode == "input":
        rows.append([{"text": "📝 Abrir formulario", "web_app": {"url": webapp_url}}])

    return {"inline_keyboard": rows}
