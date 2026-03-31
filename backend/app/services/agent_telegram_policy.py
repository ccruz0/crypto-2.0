"""
Agent Telegram policy: reduce noise; only surface deploy approval and critical failures.

Message levels:
- INFO       → never sent to Telegram (logs only)
- IMPORTANT  → batched into summary (optional); in quiet mode not sent
- CRITICAL   → sent immediately (task stuck after max retries, system cannot recover, deployment failed)
- DEPLOY     → sent immediately (task ready-for-deploy approval request)

When AGENT_TELEGRAM_ONLY_DEPLOY_AND_CRITICAL is enabled, only DEPLOY and CRITICAL are sent.
Everything else remains in logs only. User receives only actionable messages.

TELEGRAM_NOTIFICATION_MODE (see also agent_telegram_approval._get_notification_mode):
- minimal (default): only high-signal ATP messages — release-candidate/deploy approvals,
  blockers, and CRITICAL health alerts. No investigation info, subtask decomposition,
  stuck-task nudges, patch-not-applied, or needs-revision Telegram.
- verbose: intermediate status messages are also sent (more noise, easier debugging).
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# Message level constants
AGENT_MSG_INFO = "INFO"
AGENT_MSG_IMPORTANT = "IMPORTANT"
AGENT_MSG_CRITICAL = "CRITICAL"
AGENT_MSG_DEPLOY = "DEPLOY"


def is_quiet_mode() -> bool:
    """
    True when Telegram should only receive deploy approval and critical failures.
    No scheduler activity, recovery attempts, or intermediate alerts.
    """
    v = (os.environ.get("AGENT_TELEGRAM_ONLY_DEPLOY_AND_CRITICAL") or "").strip().lower()
    return v in ("1", "true", "yes")


def is_verbose_notification_mode() -> bool:
    """True when TELEGRAM_NOTIFICATION_MODE requests extra status messages (not default)."""
    raw = (os.environ.get("TELEGRAM_NOTIFICATION_MODE") or "").strip().lower()
    return raw in ("verbose", "1", "true", "yes")


def should_send_atp_intermediate_telegram() -> bool:
    """
    Whether to send non-essential ATP Telegram (investigation info, decomposition, stuck
    nudges, patch-not-applied, needs-revision). Default is False (minimal / high-signal only).
    """
    if is_quiet_mode():
        return False
    return is_verbose_notification_mode()


def should_send_agent_telegram(level: str) -> bool:
    """
    Whether to send this message to Telegram given the current policy.

    - INFO: never send
    - IMPORTANT: send only when not in quiet mode
    - CRITICAL: always send
    - DEPLOY: always send
    """
    if level == AGENT_MSG_INFO:
        return False
    if level == AGENT_MSG_CRITICAL or level == AGENT_MSG_DEPLOY:
        return True
    if level == AGENT_MSG_IMPORTANT:
        return not is_quiet_mode()
    return not is_quiet_mode()


def send_daily_summary_if_enabled(
    tasks_completed: int = 0,
    tasks_in_progress: int = 0,
    issues: list[str] | None = None,
) -> bool:
    """
    Optional: send a once-per-day summary to Telegram (tasks completed, in progress, issues).
    Call from a scheduled job (cron/celery). When in quiet mode, does not send.
    Returns True if message was sent.
    """
    if is_quiet_mode():
        logger.debug("agent_telegram_policy: daily summary skipped (quiet mode)")
        return False
    issues = issues or []
    try:
        from app.services.claw_telegram import send_claw_message
        lines = [
            "<b>Daily agent summary</b>",
            "",
            f"Tasks completed: {tasks_completed}",
            f"Tasks in progress: {tasks_in_progress}",
        ]
        if issues:
            lines.append("")
            lines.append("<b>Issues</b>")
            for i in issues[:10]:
                lines.append(f"• {str(i)[:150]}")
        msg = "\n".join(lines)
        sent, _ = send_claw_message(msg, message_type="TASK", source_module="agent_telegram_policy")
        return sent
    except Exception as e:
        logger.debug("agent_telegram_policy: daily summary failed %s", e)
    return False
