"""Telegram IO adapter for autonomous Jarvis mission events."""

from __future__ import annotations

from app.jarvis.telegram_mission_markup import MissionInlineMode, build_jarvis_mission_inline_markup


class TelegramMissionService:
    """Thin wrapper so orchestrator does not depend on telegram_commands internals."""

    def send_message(self, chat_id: str, text: str) -> bool:
        if not (chat_id or "").strip():
            return False
        try:
            from app.services.telegram_commands import send_command_response

            return bool(send_command_response(chat_id, text[:3900]))
        except Exception:
            return False

    def _send_with_mission_buttons(
        self,
        chat_id: str,
        text: str,
        *,
        mission_id: str,
        mode: MissionInlineMode,
    ) -> bool:
        if not (chat_id or "").strip():
            return False
        try:
            from app.services.telegram_commands import send_telegram_message_with_markup

            markup = build_jarvis_mission_inline_markup(mission_id, mode)
            return bool(
                send_telegram_message_with_markup(
                    chat_id,
                    text[:3900],
                    reply_markup=markup,
                    parse_mode=None,
                )
            )
        except Exception:
            return self.send_message(chat_id, text)

    def send_approval_request(self, chat_id: str, mission_id: str, summary: str) -> bool:
        msg = (
            "Hace falta tu visto bueno antes de seguir.\n\n"
            f"Qué está en juego:\n{summary[:700] or '(sin resumen)'}\n\n"
            f"Referencia interna: {mission_id}\n\n"
            "Usa los botones o, si prefieres, /mission approve o /mission reject con ese id."
        )
        ok = self._send_with_mission_buttons(
            chat_id,
            msg,
            mission_id=mission_id,
            mode="approval",
        )
        if ok:
            return True
        return self.send_message(chat_id, msg)

    def send_input_request(self, chat_id: str, mission_id: str, question: str) -> bool:
        msg = (
            "Necesito un dato más para seguir.\n\n"
            f"{question[:900] or 'Indica el contexto que falta.'}\n\n"
            f"Referencia interna: {mission_id}\n\n"
            "Pulsa «Responder», escribe un mensaje normal o usa /mission input."
        )
        ok = self._send_with_mission_buttons(
            chat_id,
            msg,
            mission_id=mission_id,
            mode="input",
        )
        if ok:
            return True
        return self.send_message(chat_id, msg)

    def send_ops_report(self, chat_id: str, ops_output: dict) -> bool:
        if not isinstance(ops_output, dict):
            return False
        diagnostics = [x for x in (ops_output.get("diagnostics") or []) if isinstance(x, dict)]
        waiting = [x for x in (ops_output.get("waiting_for_approval") or []) if isinstance(x, dict)]
        lines: list[str] = []
        for item in diagnostics[:4]:
            msg = str(item.get("message") or "").strip()
            if not msg:
                continue
            msg = _redact_sensitive_text(msg)
            lines.append(f"- {msg}")
        for action in waiting[:2]:
            text = _approval_hint(str(action.get("action_type") or ""))
            if text:
                lines.append(f"- {text}")
        if not lines:
            return False
        header = "Diagnóstico ops\n\n"
        body = "\n".join(lines)[:3400]
        return self.send_message(chat_id, header + body)


def _redact_sensitive_text(text: str) -> str:
    cleaned = text
    for sep in ("=", ":", " token ", "password", "secret"):
        if sep in cleaned.lower():
            # Keep message context while removing potential values.
            parts = cleaned.split("=", 1)
            if len(parts) == 2 and parts[0].upper().startswith("JARVIS_"):
                cleaned = f"{parts[0]}=[REDACTED]"
    return cleaned


def _approval_hint(action_type: str) -> str:
    at = (action_type or "").strip().lower()
    if at == "fix_credentials_path":
        return "¿Apruebas mover credenciales de Google Ads al directorio de secretos y reiniciar el backend?"
    if at == "restart_backend":
        return "¿Apruebas reiniciar el backend para cargar la nueva configuración?"
    if at == "update_runtime_env":
        return "¿Apruebas actualizar variables de entorno en runtime y reiniciar el backend?"
    return ""

