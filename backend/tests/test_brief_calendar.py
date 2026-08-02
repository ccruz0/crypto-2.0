"""Tests for GET /api/brief/calendar."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.brief.calendar_ics import clear_ics_cache_for_tests, fetch_calendar
from app.brief.rate_limit import reset_brief_rate_limit_for_tests
from app.brief.router import router as brief_router

_TZ = ZoneInfo("Asia/Makassar")


@pytest.fixture(autouse=True)
def _reset():
    reset_brief_rate_limit_for_tests()
    clear_ics_cache_for_tests()
    yield
    reset_brief_rate_limit_for_tests()
    clear_ics_cache_for_tests()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(brief_router)
    with patch.dict(
        os.environ,
        {
            "BRIEF_API_KEY": "test-brief-key-123456",
            "BRIEF_RATE_LIMIT_PER_MINUTE": "100",
            "BRIEF_ICS_URLS": "https://example.test/secret-calendar.ics",
        },
    ):
        yield TestClient(app)


def _ics_with_recurring(start_local: datetime) -> bytes:
    """Daily recurring event starting yesterday for 10 days."""
    # DTSTART in UTC for portability
    start_utc = start_local.astimezone(ZoneInfo("UTC"))
    stamp = start_utc.strftime("%Y%m%dT%H%M%SZ")
    end_utc = start_utc + timedelta(hours=1)
    end_stamp = end_utc.strftime("%Y%m%dT%H%M%SZ")
    ics = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//ATP Brief Test//EN
BEGIN:VEVENT
UID:recurring-test-1@brief
DTSTAMP:{stamp}
DTSTART:{stamp}
DTEND:{end_stamp}
RRULE:FREQ=DAILY;COUNT=10
SUMMARY:Standup diario
LOCATION:Bali
DESCRIPTION:Daily standup for the team
END:VEVENT
END:VCALENDAR
"""
    return ics.replace("\n", "\r\n").encode("utf-8")


def test_calendar_unauthorized(client):
    r = client.get("/api/brief/calendar")
    assert r.status_code == 401


def test_calendar_recurrence_and_timezone(client):
    now_local = datetime.now(_TZ).replace(microsecond=0)
    # Start yesterday so today+tomorrow are in the expansion window
    start = (now_local - timedelta(days=1)).replace(hour=13, minute=25, second=0)

    ics_bytes = _ics_with_recurring(start)

    class _Resp:
        content = ics_bytes

        def raise_for_status(self):
            return None

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url):
            assert "secret-calendar" in url
            return _Resp()

    with patch("app.brief.calendar_ics.httpx.Client", _Client):
        r = client.get(
            "/api/brief/calendar?days=2",
            headers={"X-Brief-Key": "test-brief-key-123456"},
        )

    assert r.status_code == 200
    body = r.json()
    assert body["timezone"] == "Asia/Makassar"
    assert body["days"] == 2
    assert body["errors"] == []
    assert len(body["events"]) >= 1
    ev = body["events"][0]
    assert ev["summary"] == "Standup diario"
    assert ev["all_day"] is False
    assert "+08:00" in ev["start"]
    assert ev["location"] == "Bali"
    # Secret URL must not appear in response
    assert "secret-calendar" not in json_dumps(body)


def json_dumps(obj) -> str:
    import json

    return json.dumps(obj)


def test_calendar_one_source_fails_others_ok(client):
    now_local = datetime.now(_TZ).replace(microsecond=0)
    start = now_local.replace(hour=9, minute=0, second=0) + timedelta(hours=1)
    good = _ics_with_recurring(start - timedelta(days=1))

    class _Resp:
        def __init__(self, content):
            self.content = content

        def raise_for_status(self):
            return None

    calls = {"n": 0}

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url):
            calls["n"] += 1
            if "bad" in url:
                raise TimeoutError("slow")
            return _Resp(good)

    with patch.dict(
        os.environ,
        {
            "BRIEF_API_KEY": "test-brief-key-123456",
            "BRIEF_ICS_URLS": "https://example.test/good.ics,https://example.test/bad.ics",
        },
    ):
        with patch("app.brief.calendar_ics.httpx.Client", _Client):
            # Use service directly to avoid client env fixture override confusion
            clear_ics_cache_for_tests()
            with patch("app.brief.calendar_ics.httpx.TimeoutException", TimeoutError):
                # Force classify: raise httpx.TimeoutException-compatible
                import httpx

                class _Client2(_Client):
                    def get(self, url):
                        if "bad" in url:
                            raise httpx.TimeoutException("slow")
                        return _Resp(good)

                with patch("app.brief.calendar_ics.httpx.Client", _Client2):
                    payload = fetch_calendar(days=2)

    assert any(e.get("error") == "timeout" for e in payload["errors"])
    assert len(payload["events"]) >= 1
