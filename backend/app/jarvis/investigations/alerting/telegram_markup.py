"""Inline keyboard markup for Jarvis investigation alerts (no side effects)."""

from __future__ import annotations

from typing import Any

JARVIS_INVESTIGATION_ALERT_CALLBACK_PREFIX = "jia:"


def build_investigation_alert_inline_markup(alert_id: str) -> dict[str, Any]:
    """
    Human-gated CTAs for investigation alerts.

    Callback payloads stay well under Telegram's 64-byte limit:
      ``jia:v:<alert_id>`` view detail
      ``jia:t:<alert_id>`` create ACW task (dry-run / approval gate)
      ``jia:s:<alert_id>`` snooze 24h (suppress Telegram re-fires)
    """
    aid = (alert_id or "").strip()
    return {
        "inline_keyboard": [
            [
                {"text": "📋 Ver detalle", "callback_data": f"jia:v:{aid}"},
                {"text": "🧾 Crear tarea", "callback_data": f"jia:t:{aid}"},
            ],
            [
                {"text": "😴 Snooze 24h", "callback_data": f"jia:s:{aid}"},
            ],
        ]
    }
