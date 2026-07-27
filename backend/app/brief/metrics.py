"""Prometheus metrics for brief endpoints. Never label with secrets or message content."""

from __future__ import annotations

try:
    from prometheus_client import Counter

    brief_requests_total = Counter(
        "brief_requests_total",
        "Brief API requests",
        ["endpoint", "status"],
    )
    brief_mail_messages_total = Counter(
        "brief_mail_messages_total",
        "Messages returned by /brief/mail",
    )
    brief_mail_account_errors_total = Counter(
        "brief_mail_account_errors_total",
        "Per-account mail fetch failures",
        ["error"],
    )
    brief_calendar_events_total = Counter(
        "brief_calendar_events_total",
        "Events returned by /brief/calendar",
    )
    brief_calendar_source_errors_total = Counter(
        "brief_calendar_source_errors_total",
        "ICS source fetch/parse failures",
        ["error"],
    )
    brief_telegram_messages_total = Counter(
        "brief_telegram_messages_total",
        "Messages returned by /brief/telegram",
    )
    brief_telegram_chats_total = Counter(
        "brief_telegram_chats_total",
        "Chats returned by /brief/telegram",
    )
    brief_send_parts_total = Counter(
        "brief_send_parts_total",
        "Message parts sent by /brief/send",
    )
    _PROM_OK = True
except Exception:  # pragma: no cover
    brief_requests_total = None  # type: ignore[assignment]
    brief_mail_messages_total = None  # type: ignore[assignment]
    brief_mail_account_errors_total = None  # type: ignore[assignment]
    brief_calendar_events_total = None  # type: ignore[assignment]
    brief_calendar_source_errors_total = None  # type: ignore[assignment]
    brief_telegram_messages_total = None  # type: ignore[assignment]
    brief_telegram_chats_total = None  # type: ignore[assignment]
    brief_send_parts_total = None  # type: ignore[assignment]
    _PROM_OK = False


def inc_request(endpoint: str, status: str) -> None:
    if _PROM_OK and brief_requests_total is not None:
        brief_requests_total.labels(endpoint=endpoint, status=status).inc()


def inc_mail_messages(n: int) -> None:
    if _PROM_OK and brief_mail_messages_total is not None and n:
        brief_mail_messages_total.inc(n)


def inc_mail_error(error: str) -> None:
    if _PROM_OK and brief_mail_account_errors_total is not None:
        brief_mail_account_errors_total.labels(error=error).inc()


def inc_calendar_events(n: int) -> None:
    if _PROM_OK and brief_calendar_events_total is not None and n:
        brief_calendar_events_total.inc(n)


def inc_calendar_error(error: str) -> None:
    if _PROM_OK and brief_calendar_source_errors_total is not None:
        brief_calendar_source_errors_total.labels(error=error).inc()


def inc_telegram_messages(n: int) -> None:
    if _PROM_OK and brief_telegram_messages_total is not None and n:
        brief_telegram_messages_total.inc(n)


def inc_telegram_chats(n: int) -> None:
    if _PROM_OK and brief_telegram_chats_total is not None and n:
        brief_telegram_chats_total.inc(n)


def inc_send_parts(n: int) -> None:
    if _PROM_OK and brief_send_parts_total is not None and n:
        brief_send_parts_total.inc(n)
