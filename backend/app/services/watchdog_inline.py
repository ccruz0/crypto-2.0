"""Telegram inline keyboard + callback handling for the logic watchdog.

Callback payloads (well under Telegram's 64-byte limit):
    wd:i:<anomaly_id>   Ignore  - never alert this fingerprint again
    wd:f:<anomaly_id>   Fix     - queue a WatchdogFixRequest for the Cowork fixer
    wd:d:<anomaly_id>   Detail  - dump the stored evidence

IMPORTANT: these messages MUST be sent with the *polling* bot token
(TELEGRAM_ATP_CONTROL_BOT_TOKEN). The trading bot (TELEGRAM_BOT_TOKEN) is
outbound-only - nothing polls it, so its button presses would never arrive.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

WATCHDOG_CALLBACK_PREFIX = "wd:"

_SEVERITY_EMOJI = {"high": "🔴", "medium": "🟠", "low": "🟡"}


def build_watchdog_inline_markup(anomaly_id: int) -> dict[str, Any]:
    """Ignore / Fix code / Detail keyboard for one anomaly."""
    aid = str(anomaly_id)
    return {
        "inline_keyboard": [
            [
                {"text": "🙈 Ignorar", "callback_data": f"wd:i:{aid}"},
                {"text": "🛠️ Corregir código", "callback_data": f"wd:f:{aid}"},
            ],
            [
                {"text": "🔍 Ver detalle", "callback_data": f"wd:d:{aid}"},
            ],
        ]
    }


def _control_token() -> Optional[str]:
    """The token whose getUpdates loop actually receives our callbacks."""
    try:
        from app.services.telegram_commands import _get_effective_bot_token

        tok = _get_effective_bot_token()
        if tok:
            return tok.strip()
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"[WATCHDOG] could not resolve control token via telegram_commands: {e}")
    return (
        os.getenv("TELEGRAM_ATP_CONTROL_BOT_TOKEN")
        or os.getenv("TELEGRAM_BOT_TOKEN")
        or ""
    ).strip() or None


def _watchdog_chat_id() -> Optional[str]:
    """Where watchdog reports go. Defaults to the ops channel."""
    return (
        os.getenv("WATCHDOG_CHAT_ID")
        or os.getenv("TELEGRAM_ATP_CONTROL_CHAT_ID")
        or os.getenv("TELEGRAM_CHAT_ID_OPS")
        or os.getenv("TELEGRAM_CHAT_ID_TRADING")
        or os.getenv("TELEGRAM_CHAT_ID")
        or ""
    ).strip() or None


def format_anomaly_message(anomaly) -> str:
    """HTML body for one anomaly alert."""
    emoji = _SEVERITY_EMOJI.get((anomaly.severity or "medium").lower(), "🟠")
    lines = [
        f"{emoji} <b>WATCHDOG: {anomaly.title}</b>",
        "",
        f"🧩 Tipo: <code>{anomaly.kind}</code>",
    ]
    if anomaly.symbol:
        lines.append(f"📊 Símbolo: <b>{anomaly.symbol}</b>")
    lines.append(f"⚠️ Severidad: {(anomaly.severity or 'medium').upper()}")
    if anomaly.occurrences and anomaly.occurrences > 1:
        lines.append(f"🔁 Repeticiones: {anomaly.occurrences}")
    if anomaly.detail:
        lines.append("")
        lines.append(anomaly.detail.strip())
    if anomaly.suspect_paths:
        lines.append("")
        lines.append("🧭 <b>Código sospechoso:</b>")
        for p in [x for x in (anomaly.suspect_paths or "").splitlines() if x.strip()][:5]:
            lines.append(f"   • <code>{p.strip()}</code>")
    lines.append("")
    lines.append("<i>¿Ignorar o corregir el código?</i>")
    return "\n".join(lines)


def send_anomaly_alert(anomaly) -> tuple[bool, Optional[int], Optional[str]]:
    """Post one anomaly with buttons. Returns (ok, message_id, chat_id)."""
    from app.utils.http_client import http_post

    token = _control_token()
    chat_id = _watchdog_chat_id()
    if not token or not chat_id:
        logger.warning(
            "[WATCHDOG] cannot send alert: missing token or chat id "
            f"(token={'set' if token else 'MISSING'}, chat_id={'set' if chat_id else 'MISSING'})"
        )
        return False, None, None

    prefix = ""
    try:
        from app.core.runtime import get_runtime_origin

        prefix = f"[{get_runtime_origin()}] "
    except Exception:
        prefix = ""

    payload = {
        "chat_id": chat_id,
        "text": prefix + format_anomaly_message(anomaly),
        "parse_mode": "HTML",
        "reply_markup": build_watchdog_inline_markup(anomaly.id),
        "disable_web_page_preview": True,
    }
    try:
        resp = http_post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json=payload,
            timeout=10,
            calling_module="logic_watchdog",
        )
        data = resp.json() if hasattr(resp, "json") else {}
        if not data.get("ok"):
            logger.error(f"[WATCHDOG] Telegram rejected alert for anomaly {anomaly.id}: {data}")
            return False, None, chat_id
        return True, (data.get("result") or {}).get("message_id"), chat_id
    except Exception as e:
        logger.error(f"[WATCHDOG] failed sending alert for anomaly {anomaly.id}: {e}", exc_info=True)
        return False, None, chat_id


def _append_to_message(chat_id: str, message_id: int, extra_html: str, original_html: str) -> None:
    """Strip the keyboard and append a resolution footer."""
    from app.utils.http_client import http_post

    token = _control_token()
    if not token or not chat_id or not message_id:
        return
    try:
        http_post(
            f"https://api.telegram.org/bot{token}/editMessageText",
            json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": f"{original_html}\n\n{extra_html}",
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
            calling_module="logic_watchdog",
        )
    except Exception as e:
        logger.warning(f"[WATCHDOG] could not edit message {message_id}: {e}")


def handle_watchdog_callback(
    callback_data: str,
    chat_id: str,
    user_id: str,
    db,
) -> str:
    """Process a wd: button press. Returns the text to answer with."""
    from app.models.watchdog import (
        WatchdogAnomaly,
        WatchdogFixRequest,
        ANOMALY_STATUS_IGNORED,
        ANOMALY_STATUS_FIX_REQUESTED,
        FIX_STATUS_PENDING,
    )

    raw = (callback_data or "").strip()
    parts = raw.split(":")
    if len(parts) != 3 or parts[0] != "wd":
        return "❌ Callback de watchdog no reconocido."
    action = parts[1]
    try:
        anomaly_id = int(parts[2])
    except ValueError:
        return "❌ ID de anomalía inválido."

    # Validate the action before touching the DB, so an unknown action reports
    # itself as such instead of as a missing anomaly.
    if action not in ("i", "f", "d"):
        return "\u274c Acci\u00f3n de watchdog no reconocida."

    anomaly = db.query(WatchdogAnomaly).filter(WatchdogAnomaly.id == anomaly_id).first()
    if not anomaly:
        return f"❌ Anomalía #{anomaly_id} no encontrada."

    now = datetime.now(timezone.utc)
    body = format_anomaly_message(anomaly)

    if action == "d":
        try:
            evidence = json.loads(anomaly.evidence_json or "{}")
        except Exception:
            evidence = {"raw": anomaly.evidence_json}
        pretty = json.dumps(evidence, indent=2, ensure_ascii=False, default=str)[:3000]
        return (
            f"🔍 <b>Anomalía #{anomaly.id}</b> — <code>{anomaly.kind}</code>\n"
            f"Estado: <b>{anomaly.status}</b>\n\n"
            f"<pre>{pretty}</pre>"
        )

    if action == "i":
        anomaly.status = ANOMALY_STATUS_IGNORED
        anomaly.resolved_at = now
        db.commit()
        _append_to_message(
            anomaly.telegram_chat_id or chat_id,
            anomaly.telegram_message_id,
            f"🙈 <b>Ignorada</b> por {user_id} — no se volverá a avisar de esta condición.",
            body,
        )
        logger.info(f"[WATCHDOG] anomaly {anomaly.id} ignored by user {user_id}")
        return f"🙈 Anomalía #{anomaly.id} ignorada."

    if action == "f":
        existing = (
            db.query(WatchdogFixRequest)
            .filter(
                WatchdogFixRequest.anomaly_id == anomaly.id,
                WatchdogFixRequest.status.in_(["pending", "in_progress"]),
            )
            .first()
        )
        if existing:
            return f"⏳ Ya hay un fix en curso para #{anomaly.id} (petición #{existing.id})."

        fix = WatchdogFixRequest(
            anomaly_id=anomaly.id,
            status=FIX_STATUS_PENDING,
            requested_by=str(user_id or "")[:50],
        )
        db.add(fix)
        anomaly.status = ANOMALY_STATUS_FIX_REQUESTED
        db.commit()
        db.refresh(fix)
        _append_to_message(
            anomaly.telegram_chat_id or chat_id,
            anomaly.telegram_message_id,
            f"🛠️ <b>Corrección solicitada</b> por {user_id} — petición #{fix.id} en cola.\n"
            f"<i>El fixer creará la rama <code>watchdog/fix-{anomaly.id}</code>, "
            f"ejecutará los tests y avisará aquí.</i>",
            body,
        )
        logger.info(f"[WATCHDOG] fix requested for anomaly {anomaly.id} by user {user_id} (fix #{fix.id})")
        return f"🛠️ Fix #{fix.id} encolado para la anomalía #{anomaly.id}."

    return "❌ Acción de watchdog no reconocida."
