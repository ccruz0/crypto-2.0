"""ICS calendar reader for GET /brief/calendar (Outlook published calendars)."""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx
from icalendar import Calendar
import recurring_ical_events

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Asia/Makassar")
_FETCH_TIMEOUT_S = 20.0
_CACHE_TTL_S = 30 * 60
_DESC_MAX = 300

_lock = threading.Lock()
# key -> (expires_monotonic, bytes)
_cache: dict[str, tuple[float, bytes]] = {}


def _ics_urls() -> list[tuple[str, str]]:
    """Return list of (source_id, url). Never log URLs."""
    raw = (os.getenv("BRIEF_ICS_URLS") or "").strip()
    if not raw:
        return []
    out: list[tuple[str, str]] = []
    for i, part in enumerate(raw.split(",")):
        url = part.strip()
        if not url:
            continue
        # Stable non-secret label for response `source`
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
        source = "outlook" if i == 0 else f"cal-{digest}"
        if "google" in url.lower():
            source = "google" if i == 0 else f"google-{digest}"
        out.append((source, url))
    return out


def _cache_key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _get_cached(url: str) -> Optional[bytes]:
    key = _cache_key(url)
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if not hit:
            return None
        expires, body = hit
        if now > expires:
            _cache.pop(key, None)
            return None
        return body


def _set_cached(url: str, body: bytes) -> None:
    key = _cache_key(url)
    with _lock:
        _cache[key] = (time.monotonic() + _CACHE_TTL_S, body)


def clear_ics_cache_for_tests() -> None:
    with _lock:
        _cache.clear()


def _download_ics(url: str) -> bytes:
    cached = _get_cached(url)
    if cached is not None:
        return cached
    with httpx.Client(timeout=_FETCH_TIMEOUT_S, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        body = resp.content
    _set_cached(url, body)
    return body


def _as_local(dt: datetime | date) -> tuple[str, bool]:
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone(_TZ)
        return local.isoformat(timespec="seconds"), False
    # date → all-day in local TZ
    return dt.isoformat(), True


def _event_row(component: Any, source: str) -> Optional[dict[str, Any]]:
    summary = component.get("SUMMARY")
    summary_s = str(summary) if summary is not None else ""
    location = component.get("LOCATION")
    location_s = str(location) if location is not None else ""
    description = component.get("DESCRIPTION")
    desc_s = str(description) if description is not None else ""
    if len(desc_s) > _DESC_MAX:
        desc_s = desc_s[:_DESC_MAX]

    dtstart = component.get("DTSTART")
    dtend = component.get("DTEND")
    if dtstart is None:
        return None
    start_val = dtstart.dt
    end_val = dtend.dt if dtend is not None else None

    start_s, all_day_from_start = _as_local(start_val)
    all_day = all_day_from_start or (isinstance(start_val, date) and not isinstance(start_val, datetime))

    if end_val is None:
        if all_day and isinstance(start_val, date) and not isinstance(start_val, datetime):
            end_s = (start_val + timedelta(days=1)).isoformat()
        else:
            # Default: same instant if no DTEND
            if isinstance(start_val, datetime):
                if start_val.tzinfo is None:
                    start_val = start_val.replace(tzinfo=timezone.utc)
                end_s = start_val.astimezone(_TZ).isoformat(timespec="seconds")
            else:
                end_s = start_s
    else:
        end_s, _ = _as_local(end_val)

    # Normalize all-day start/end to date-only ISO when all_day
    if all_day:
        if "T" in start_s:
            start_s = start_s.split("T", 1)[0]
        if "T" in end_s:
            end_s = end_s.split("T", 1)[0]

    return {
        "summary": summary_s,
        "start": start_s if all_day else start_s,
        "end": end_s,
        "all_day": bool(all_day),
        "location": location_s,
        "description": desc_s,
        "source": source,
    }


def _classify_error(exc: BaseException) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        return "http_error"
    if isinstance(exc, httpx.RequestError):
        return "connection_error"
    if isinstance(exc, ValueError):
        return "parse_error"
    return "error"


def fetch_calendar(days: int = 2) -> dict[str, Any]:
    days = max(1, min(int(days), 7))
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(_TZ)
    window_end = now_local + timedelta(days=days)

    errors: list[dict[str, str]] = []
    events: list[dict[str, Any]] = []
    sources = _ics_urls()

    if not sources:
        logger.warning("brief_calendar no_ics_urls_configured")
        return {
            "timezone": "Asia/Makassar",
            "days": days,
            "errors": [{"id": "_config", "error": "ics_urls_missing"}],
            "events": [],
        }

    for idx, (source, url) in enumerate(sources):
        source_id = source
        try:
            raw = _download_ics(url)
            cal = Calendar.from_ical(raw)
            # Expand recurrences in local window (library accepts aware datetimes)
            expanded = recurring_ical_events.of(cal).between(now_local, window_end)
            for comp in expanded:
                if comp.name != "VEVENT":
                    continue
                row = _event_row(comp, source_id)
                if row:
                    events.append(row)
        except Exception as exc:  # noqa: BLE001 — isolate sources
            err = _classify_error(exc)
            errors.append({"id": source_id, "error": err})
            logger.warning("brief_calendar source=%s error=%s", source_id, err)

    def _sort_key(ev: dict[str, Any]) -> tuple:
        return (ev.get("start") or "", ev.get("summary") or "")

    events.sort(key=_sort_key)

    logger.info(
        "brief_calendar days=%s events=%s sources=%s errors=%s",
        days,
        len(events),
        len(sources),
        len(errors),
    )
    return {
        "timezone": "Asia/Makassar",
        "days": days,
        "errors": errors,
        "events": events,
    }
