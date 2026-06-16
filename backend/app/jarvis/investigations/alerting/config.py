"""Environment configuration for Phase 6B autonomous alerting."""

from __future__ import annotations

import os

_DEFAULT_SUPPRESSION_HOURS = 24
_DEFAULT_DAILY_REPORT_HOUR_UTC = 8


def _bool_env(name: str, default: bool = False) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def jarvis_alerting_enabled() -> bool:
    return _bool_env("JARVIS_ALERTING_ENABLED", default=True)


def jarvis_alert_info_telegram_enabled() -> bool:
    """When false, INFO alerts are stored but not sent via Telegram."""
    return _bool_env("JARVIS_ALERT_INFO_TELEGRAM_ENABLED", default=False)


def jarvis_alert_suppression_window_hours() -> int:
    raw = (os.environ.get("JARVIS_ALERT_SUPPRESSION_WINDOW_HOURS") or "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return _DEFAULT_SUPPRESSION_HOURS


def jarvis_daily_report_enabled() -> bool:
    return _bool_env("JARVIS_DAILY_REPORT_ENABLED", default=True)


def jarvis_daily_report_hour_utc() -> int:
    raw = (os.environ.get("JARVIS_DAILY_REPORT_HOUR_UTC") or "").strip()
    if raw:
        try:
            return max(0, min(23, int(raw)))
        except ValueError:
            pass
    return _DEFAULT_DAILY_REPORT_HOUR_UTC


def jarvis_alerting_should_autostart() -> bool:
    """Daily report loop autostarts with the primary Telegram poller process."""
    run_poller = (os.environ.get("RUN_TELEGRAM_POLLER") or "true").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    return run_poller and jarvis_daily_report_enabled()


def alerting_status() -> dict:
    from app.jarvis.investigations.alerting.loop import get_daily_report_runtime_state

    return {
        "enabled": jarvis_alerting_enabled(),
        "info_telegram_enabled": jarvis_alert_info_telegram_enabled(),
        "suppression_window_hours": jarvis_alert_suppression_window_hours(),
        "daily_report_enabled": jarvis_daily_report_enabled(),
        "daily_report_hour_utc": jarvis_daily_report_hour_utc(),
        **get_daily_report_runtime_state(),
    }
