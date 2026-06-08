"""Read-only Telegram alerts for Jarvis Crypto Auditor (no remediation)."""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_ALERT_THRESHOLD_PCT = 5.0


def _chat_id() -> str:
    return (
        os.environ.get("JARVIS_TELEGRAM_CHAT_ID")
        or os.environ.get("TELEGRAM_CHAT_ID")
        or ""
    ).strip()


def _should_alert(audit_output: dict[str, Any]) -> tuple[bool, str]:
    diff_pct = float(audit_output.get("portfolio_difference_pct") or 0)
    wallet = audit_output.get("wallet_findings") or []
    valuation = audit_output.get("valuation_findings") or []

    if diff_pct > _ALERT_THRESHOLD_PCT:
        return True, f"Portfolio difference {diff_pct}% exceeds {_ALERT_THRESHOLD_PCT}% threshold"

    for finding in wallet + valuation:
        if finding.get("type") == "missing_asset":
            return True, f"Missing asset detected: {finding.get('currency', 'unknown')}"
        if str(finding.get("severity") or "").lower() == "critical":
            return True, f"Critical finding: {finding.get('finding', finding.get('type'))}"

    for finding in wallet:
        if finding.get("type") == "balance_mismatch" and diff_pct > 0:
            return True, "Dashboard value differs from exchange value"

    return False, ""


def format_crypto_alert(audit_output: dict[str, Any]) -> str:
    """Format CRYPTO AUDITOR ALERT message (read-only, no remediation)."""
    summary = audit_output.get("summary") or {}
    exchange = float(summary.get("exchange_total_usd") or 0)
    dashboard = float(summary.get("dashboard_total_usd") or 0)
    diff_usd = float(audit_output.get("portfolio_difference_usd") or 0)
    diff_pct = float(audit_output.get("portfolio_difference_pct") or 0)
    recs = audit_output.get("recommendations") or []
    recommended = recs[0] if recs else "Review findings manually. No automatic remediation."

    return (
        "CRYPTO AUDITOR ALERT\n\n"
        f"Difference: ${diff_usd:,.2f} ({diff_pct}%)\n"
        f"Exchange: ${exchange:,.2f}\n"
        f"Dashboard: ${dashboard:,.2f}\n"
        f"Impact: {summary.get('reconciliation_status', 'unknown')} — "
        f"{summary.get('total_findings', 0)} finding(s)\n\n"
        f"Recommended action:\n{recommended}\n\n"
        "(Read-only alert — no trades or balance changes executed.)"
    )


def send_crypto_audit_alert(audit_output: dict[str, Any]) -> bool:
    """Send Telegram alert when crypto audit thresholds are exceeded."""
    should, reason = _should_alert(audit_output)
    if not should:
        logger.info("crypto_audit alert skipped: %s", reason or "thresholds not met")
        return False

    chat_id = _chat_id()
    if not chat_id:
        logger.warning("crypto_audit alert skipped: no TELEGRAM_CHAT_ID configured")
        return False

    try:
        from app.jarvis.telegram_service import TelegramMissionService

        message = format_crypto_alert(audit_output)
        sent = TelegramMissionService().send_message(chat_id, message)
        logger.info("crypto_audit alert sent=%s reason=%s", sent, reason)
        return bool(sent)
    except Exception as exc:
        logger.warning("crypto_audit alert failed: %s", exc)
        return False
